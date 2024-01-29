Abebooks
================

Overview
========

Code for downloading, and analyzing offers from abebooks.de.

Process description
===================

Prerequisities
--------------

Create Python virtual environment and install necessary packages::

    python3 -m venv --clear venv
    source ./venv/bin/activate
    pip3 install -r requirements.txt

Set up environment variables::
    export HTTP_PROXY_LIST = [...]

Downloading the data
------------------------------------------------------

The script ``abebooks.py`` contains code that downloads offers from the website and saves them to a CSV file. To use it run::

    python3 abebooks.py

Analyzing the offers
------------------------------------------------------

The notebook ``analysis.ipynb`` answers analytical questions about the offers. You can run it in an editor of your choice, or inspect here on the website.