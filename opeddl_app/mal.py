import re
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup


def parse_mal_themes_from_soup(soup: BeautifulSoup) -> Tuple[List[str], List[str]]:
    openings: List[str] = []
    endings: List[str] = []

    candidates = soup.select("div.theme-songs")
    text_blocks: List[str] = []
    for c in candidates:
        t = c.get_text("\n", strip=True)
        if t:
            text_blocks.append(t)

    if not text_blocks:
        full_text = soup.get_text("\n", strip=True)
        m = re.search(
            r"Theme Songs(.*?)(?:Edit\s*Theme\s*Songs|Characters & Voice Actors|Staff|Reviews)",
            full_text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            text_blocks = [m.group(1)]
        else:
            text_blocks = [full_text]

    section: Optional[str] = None
    for block in text_blocks:
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if re.search(r"^Opening Theme", line, re.IGNORECASE):
                section = "op"
                continue
            if re.search(r"^Ending Theme", line, re.IGNORECASE):
                section = "ed"
                continue

            m = re.match(r"^(?:#\d+:\s*)?\"(.+?)\"\s*(?:by\s+(.+?))?(?:\s*\(.*\))?$", line)
            if m and section in ("op", "ed"):
                title = m.group(1).strip()
                artist = (m.group(2) or "").strip()
                query = f"{title} {artist}".strip()
                if section == "op":
                    openings.append(query)
                else:
                    endings.append(query)
                continue

            if section in ("op", "ed") and "\"" in line:
                m2 = re.search(r"\"(.+?)\"", line)
                if m2:
                    title = m2.group(1).strip()
                    rest = re.sub(r".*?\".+?\"", "", line).strip()
                    rest = re.sub(r"^by\s+", "", rest, flags=re.IGNORECASE)
                    rest = re.sub(r"\(.*\)$", "", rest).strip()
                    query = f"{title} {rest}".strip()
                    if section == "op":
                        openings.append(query)
                    else:
                        endings.append(query)

    def _dedupe(xs: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for x in xs:
            k = x.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
        return out

    return _dedupe(openings), _dedupe(endings)


def scrape_mal_title_and_themes(mal_url: str, timeout_s: int = 20) -> Tuple[str, List[str], List[str]]:
    r = requests.get(mal_url, timeout=timeout_s, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = ""
    h1 = soup.select_one("h1.title-name")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title:
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            title = str(og.get("content")).strip()

    openings, endings = parse_mal_themes_from_soup(soup)
    return title, openings, endings


def tvdb_search_url(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    return f"https://thetvdb.com/search?query={requests.utils.quote(q)}"
