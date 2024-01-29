import json
import logging
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from urllib.parse import urljoin

import pandas as pd
import requests
from lxml import html

logger = logging.getLogger("abebooks")
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

START_URL = "https://www.abebooks.de/servlet/SearchResults?bi=0&ch_sort=t&cm_sp=sort-_-SRP-_-Results&ds=30&sortby=1&vci=87044093"
ISBN_SEARCH_URL = "https://www.abebooks.de/servlet/SearchResults?ch_sort=t&cm_sp=sort-_-SRP-_-Results&kn={}&sortby=2"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6.1 Safari/605.1.15"
REFERER = "https://www.abebooks.de/"
OFFERS_OUTPUT_FILE = "abebooks.csv"
SOLUTION_OUTPUT_FILE = "part_1_solution.csv"

PROXY_LIST = json.loads(os.getenv("HTTP_PROXY_LIST"))


def extract_isbns_from_url(
    url: str, n_items: int = 1_000, isbns: Optional[List[str]] = None
) -> List[str]:
    if isbns is None:
        isbns = list()
    try:
        response = requests.get(url)
        response.raise_for_status()

    except Exception as e:
        logger.error("Failed to access %s due to %s", url, e)
        return None

    tree = html.fromstring(response.content)

    for entry in tree.xpath("//li[@data-cy='listing-item']"):
        if isbn_element := entry.xpath(".//meta[@itemprop='isbn']/@content"):
            if isbn_match := re.search(r"\d{13}", isbn_element[0]):
                if (isbn := isbn_match.group()) not in isbns:
                    isbns.append(isbn)

    logger.info("Extracted ISBNs from URL %s", response.url)

    while len(isbns) < n_items:
        if next_page_element := tree.xpath("//a[@id='page-next-bottom-nav']/@href"):
            next_page_url = next_page_element[0]
            extract_isbns_from_url(urljoin(START_URL, next_page_url), n_items, isbns)
        else:
            logger.warning("Could not find next_page_url at %s", response.url)

    return isbns[:n_items]


def fetch_url_response(
    path: str, max_retries: int = 10, next_page_url: bool = False
) -> Optional[requests.models.Response]:
    retry_count = 0

    url = urljoin(START_URL, path) if next_page_url else ISBN_SEARCH_URL.format(path)

    while retry_count <= max_retries:
        proxy_url = random.choice(PROXY_LIST)

        response = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": REFERER,
            },
            proxies={
                "http": proxy_url,
                "https": proxy_url,
            },
        )
        if response.status_code == 429:
            wait_time = 2**retry_count
            logger.info(
                "Received 429 status code at URL: %s. Waiting for %s seconds before retrying.",
                response.url,
                wait_time,
            )
            time.sleep(wait_time)
            retry_count += 1

        elif response.status_code == 200:
            logger.info("Accessed URL %s after %s retries", response.url, retry_count)
            return response

        else:
            logger.warning(
                "Unexpected status code: %s at URL: %s",
                response.status_code,
                response.url,
            )
            return None

    logger.warning(
        "Reached max retry attempts (%s) at URL: %s. Exiting.",
        max_retries,
        response.url,
    )

    return None


def extract_books_from_url(
    path: str, next_page_url: bool = False, books=None
) -> List[Dict]:
    if books is None:
        books = list()

    response = fetch_url_response(path, next_page_url=next_page_url)

    isbn = re.findall(r"kn\=(\d{13})", response.url)[0]

    tree = html.fromstring(response.content)

    for entry in tree.xpath("//li[@data-cy='listing-item']"):
        book = dict()

        book["isbn"] = isbn

        book["title"] = entry.xpath(".//meta[@itemprop='name']/@content")[0]

        if author := entry.xpath(".//meta[@itemprop='author']/@content"):
            book["author"] = author[0]

        if seller := entry.xpath(
            "normalize-space(.//div[contains(@class,'bookseller-info')]//a)"
        ):
            if seller in [b.get("seller", "") for b in books]:
                continue
            else:
                book["seller"] = seller

        if seller_info := entry.xpath(
            "normalize-space(.//div[contains(@class,'bookseller-info')]//p)"
        ):
            book["seller_country"] = seller_info.split(", ")[-1]

        if price := re.findall(
            r"EUR (.+)", entry.xpath("normalize-space(.//p[@class='item-price'])")
        ):
            book["price"] = float(price[0].replace(".", "").replace(",", "."))

        books.append(book)

    if next_page_element := tree.xpath("//a[@id='page-next-bottom-nav']/@href"):
        next_page_url = next_page_element[0]
        logger.info("Jumping to the next page at path: %s", next_page_url)
        extract_books_from_url(next_page_url, next_page_url=True, books=books)

    logger.info("Obtained book data for ISBN %s", isbn)

    return books


def get_sellers_per_title(df: pd.DataFrame) -> pd.DataFrame:
    try:
        sellers_by_title = df.groupby(["isbn", "title"], as_index=False).agg(
            {"seller": "unique"}
        )
        sellers_expanded = sellers_by_title["seller"].apply(pd.Series)
        sellers_expanded.columns = [
            f"seller_{str(c+1)}" for c in sellers_expanded.columns
        ]

        result = pd.concat(
            [sellers_by_title.drop(columns="seller"), sellers_expanded], axis=1
        )
        return result
    except Exception:
        logger.error("Failed to create sellers per title dataframe", exc_info=True)


def main():
    try:
        bookbot_isbns = extract_isbns_from_url(START_URL, n_items=1_000)

        with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            books = list(executor.map(extract_books_from_url, bookbot_isbns))

        data = [offer for isbn in books for offer in isbn]

        df = pd.DataFrame(data)

        part_1_solution = get_sellers_per_title(df)
        part_1_solution.to_csv(SOLUTION_OUTPUT_FILE, index=False)

        df.to_csv(OFFERS_OUTPUT_FILE, index=False)

        logger.info(
            "Stored offers data to a CSV file %s. and solution of part 1 to %s",
            OFFERS_OUTPUT_FILE,
            SOLUTION_OUTPUT_FILE,
        )

        return 0

    except Exception:
        logger.error("Failed to obtain book data due to error:", exc_info=True)
        return 1


if __name__ == "__main__":
    status = main()
    sys.exit(status)
