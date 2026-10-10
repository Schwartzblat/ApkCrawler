#!/bin/bash
source .env
source .venv/bin/activate
python crawler.py "$@"