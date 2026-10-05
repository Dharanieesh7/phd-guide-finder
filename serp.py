# The one place in the project that talks to SerpApi.
# Every result is saved in the cache/ folder, so the same search is never paid for twice.
from pathlib import Path
import hashlib
import json
import os

import requests
import serpapi
from dotenv import load_dotenv

FOLDER = Path(__file__).parent
CACHE = FOLDER / "cache"
load_dotenv(FOLDER / ".env", encoding="utf-8-sig")

# Counts searches that really went to SerpApi (saved copies are not counted).
spent = {"searches": 0}


class NotSaved(Exception):
    """Raised in offline mode when a search is not saved yet (so nothing is ever spent by accident)."""


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


def searches_left(key):
    """How many searches this key has left this month. SerpApi's Account API is free (costs 0 searches).
    Returns None if the key is not accepted."""
    try:
        response = requests.get("https://serpapi.com/account.json", params={"api_key": key}, timeout=20)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    return response.json().get("total_searches_left")   # never print the whole reply: it contains the key


def search(params, key=None):
    """Run a SerpApi search, or reuse the saved copy if we already ran the same search.
    `key` is a key typed into the web page; without it the key from .env is used."""
    saved = _saved_file(params)
    if saved.exists():
        return json.loads(saved.read_text(encoding="utf-8"))
    if offline():
        raise NotSaved(params)

    client = serpapi.Client(api_key=(key or env_key()).strip())
    data = client.search(params).as_dict()
    spent["searches"] += 1

    # Only keep good results. An error (for example "no results") is not saved.
    if "error" not in data:
        CACHE.mkdir(exist_ok=True)
        saved.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
