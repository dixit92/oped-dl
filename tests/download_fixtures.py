"""Download real MAL anime pages and save them as HTML fixtures for testing.

Run this script to (re)download the fixture files:
    python tests/download_fixtures.py
"""

import os
import sys
import time

import requests

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

MAL_PAGES = {
    # anime_id -> URL
    1: "https://myanimelist.net/anime/1/Cowboy_Bebop",
    5114: "https://myanimelist.net/anime/5114/Fullmetal_Alchemist__Brotherhood",
    16498: "https://myanimelist.net/anime/16498/Shingeki_no_Kyojin",
    30276: "https://myanimelist.net/anime/30276/One_Punch_Man",
    21: "https://myanimelist.net/anime/21/One_Piece",
    11061: "https://myanimelist.net/anime/11061/Fate_Zero",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def download_fixtures():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    for anime_id, url in MAL_PAGES.items():
        filepath = os.path.join(FIXTURES_DIR, f"mal_{anime_id}.html")
        print(f"Downloading {url} ...")
        try:
            r = requests.get(url, timeout=20, headers=HEADERS, allow_redirects=True)
            r.raise_for_status()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"  Saved {len(r.text)} bytes to {filepath}")
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
        time.sleep(2)


if __name__ == "__main__":
    download_fixtures()
