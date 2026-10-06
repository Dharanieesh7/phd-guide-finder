# The one place in the project that talks to SerpApi.
# Every result is saved in the cache/ folder, so the same search is never paid for twice.
from pathlib import Path
import hashlib
import json
import os
import re
import time

import requests
import serpapi
from dotenv import load_dotenv

FOLDER = Path(__file__).parent
CACHE = FOLDER / "cache"
load_dotenv(FOLDER / ".env", encoding="utf-8-sig")

# Counts searches that really went to SerpApi (saved copies are not counted).
spent = {"searches": 0}


RETRIES = 2            # a dropped connection is tried again twice before giving up
REQUEST_TIMEOUT = 60   # seconds; Scholar profile pages can take ~20 s, a stalled connection never ends


class NotSaved(Exception):
    """Raised in offline mode when a search is not saved yet (so nothing is ever spent by accident)."""


class SearchFailed(Exception):
    """SerpApi could not be reached. The message never contains the API key."""


def without_key(message, key=""):
    """Remove the API key from any text (error messages include the request address, key and all)."""
    message = re.sub(r"api_key=[^&\s'\")]+", "api_key=•••", message)
    return message.replace(key, "•••") if key else message


def offline():
    return os.environ.get("SERP_OFFLINE") == "1"


def _saved_file(params):
    name = hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()
    return CACHE / f"{name}.json"


def is_saved(params):
    """True if this exact search was already run, so running it again costs 0 searches."""
    return _saved_file(params).exists()


def env_key():
    """The key from the .env file, or "" if it is missing or still the placeholder."""
    key = os.environ.get("SERPAPI_API_KEY", "").strip()
    return "" if key == "paste-your-key-here" else key


UNKNOWN_LEFT = "?"   # SerpApi couldn't be asked right now (network hiccup) — not the same as a bad key


def searches_left(key):
    """How many searches this key has left this month. SerpApi's Account API is free (costs 0 searches).
    Returns None only if SerpApi REJECTS the key, and UNKNOWN_LEFT if it just couldn't be reached."""
    for attempt in range(RETRIES + 1):
        try:
            response = requests.get("https://serpapi.com/account.json", params={"api_key": key}, timeout=20)
        except requests.RequestException:      # never show this error: it contains the key in the address
            continue
        if response.status_code in (401, 403):
            return None
        if response.status_code == 200:
            return response.json().get("total_searches_left")   # never print the whole reply: it has the key
        time.sleep(attempt + 1)
    return UNKNOWN_LEFT


def search(params, key=None):
    """Run a SerpApi search, or reuse the saved copy if we already ran the same search.
    `key` is a key typed into the web page; without it the key from .env is used."""
    saved = _saved_file(params)
    if saved.exists():
        return json.loads(saved.read_text(encoding="utf-8"))
    if offline():
        raise NotSaved(params)

    api_key = (key or env_key()).strip()
    # A time limit matters: without one, a connection that silently drops makes the search wait forever.
    client = serpapi.Client(api_key=api_key, timeout=REQUEST_TIMEOUT)
    for attempt in range(RETRIES + 1):
        try:
            data = client.search(params).as_dict()
            break
        except Exception as problem:            # e.g. a dropped connection on a flaky network
            if attempt == RETRIES:
                # Error texts contain the request address, which includes the key: never pass that on.
                raise SearchFailed(without_key(str(problem), api_key)) from None
            time.sleep(2 * (attempt + 1))
    spent["searches"] += 1

    # Only keep good results. An error (for example "no results") is not saved.
    if "error" not in data:
        CACHE.mkdir(exist_ok=True)
        saved.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
