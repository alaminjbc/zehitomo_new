cd /Users/mdalamintokder/zehitomo
    python3 -m venv .venv && source .venv/bin/activate
    pip install -U browser-use playwright python-dotenv
    playwright install chromium --with-deps --no-shell
    python test.py