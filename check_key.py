# Checks that your SerpApi key works.
# It uses SerpApi's free Account API, so it does NOT spend any of your 250 searches.
from pathlib import Path
import os

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", encoding="utf-8-sig")
key = os.getenv("SERPAPI_API_KEY", "").strip()

if not key or key == "paste-your-key-here":
    print("No key found. Open the .env file and paste your key after SERPAPI_API_KEY=")
    raise SystemExit

try:
    response = requests.get("https://serpapi.com/account.json", params={"api_key": key}, timeout=30)
except requests.RequestException:
    # Don't print the error itself: it contains the request address, which includes your key.
    print("Could not reach SerpApi. Check your internet connection and try again.")
    raise SystemExit
if response.status_code in (401, 403):
    print("SerpApi did not accept this key. Copy it again from your dashboard and make sure nothing is missing.")
    raise SystemExit
if response.status_code != 200:
    print(f"SerpApi had a temporary problem (status {response.status_code}). Try again in a minute.")
    raise SystemExit

# Never print the whole reply: it contains your key.
info = response.json()
print("Key works.")
print("Plan:", info.get("plan_name"))
print("Searches left this month:", info.get("total_searches_left"))
