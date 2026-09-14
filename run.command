#!/bin/zsh

cd "$(dirname "$0")"
open "http://127.0.0.1:8000"
python3 server.py
