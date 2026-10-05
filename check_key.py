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

response = requests.get("https://serpapi.com/account.json", params={"api_key": key}, timeout=30)
if response.status_code != 200:
    print("SerpApi did not accept this key. Copy it again from your dashboard and make sure nothing is missing.")
    raise SystemExit

# Never print the whole reply: it contains your key.
info = response.json()
print("Key works.")
print("Plan:", info.get("plan_name"))
print("Searches left this month:", info.get("total_searches_left"))
