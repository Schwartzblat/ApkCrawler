#!/bin/bash
cd "$(dirname "$0")"
set -a  # export the .env variables to the crawler
source .env
set +a
source .venv/bin/activate
python crawler.py "$@"