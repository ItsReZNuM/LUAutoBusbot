#!/usr/bin/env bash

# Autobus Telegram Bot Linux Runner
cd "$(dirname "$0")" || exit 1

# Optional: Load environment variables if .env file exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Create virtual environment if not present
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt --quiet

echo "Starting Autobus Bot..."
python bot.py
