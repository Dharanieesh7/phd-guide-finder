# Saves finished searches into the demo/ folder, so the web page can show them
# to anyone (no API key, no searches spent). Runs OFFLINE: it only uses saved search results.
import json
import os
import re
from pathlib import Path

os.environ["SERP_OFFLINE"] = "1"

import finder  # noqa: E402  (must come after SERP_OFFLINE is set)
from serp import NotSaved  # noqa: E402

DEMO = Path(__file__).parent / "demo"
SEARCHES = [
    ("medical image analysis", None),
    ("medical image analysis", "India"),
    ("medical image analysis", "Singapore"),
    ("natural language processing", None),
    ("natural language processing", "India"),
    ("renewable energy", None),
    ("renewable energy", "India"),
]


def file_name(topic, country):
    return re.sub(r"[^a-z0-9]+", "-", f"{topic} {country or 'global'}".lower()).strip("-") + ".json"


if __name__ == "__main__":
    DEMO.mkdir(exist_ok=True)
    for topic, country in SEARCHES:
        try:
            result = finder.run(topic, country)
        except NotSaved:
            print(f"SKIPPED (would need new searches): {topic} / {country or 'global'}")
            continue
        (DEMO / file_name(topic, country)).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                                      encoding="utf-8")
        print(f"saved: {topic} / {country or 'global'}  ->  {len(result['here'])} researchers")
