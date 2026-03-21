import re
import time
from typing import Callable, List, Optional, Tuple

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


LogCb = Callable[[str], None]


def _extract_mal_anime_id(url: str) -> Optional[int]:
    u = (url or "").strip()
    m = re.search(r"myanimelist\.net/anime/(\d+)", u)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _normalize_mal_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return u
    if u.endswith("/"):
        u = u[:-1]
    return u


def _jikan_get_json(path: str, timeout_s: int, log_cb: Optional[LogCb]) -> dict:
    base = "https://api.jikan.moe/v4"
    url = base + path

    last_exc: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            if log_cb:
                log_cb(f"Debug: Jikan GET {url} (attempt {attempt}/3)")
            r = requests.get(
                url,
                timeout=(min(10, timeout_s), timeout_s),
                headers={"User-Agent": "oped-dl"},
            )
            if r.status_code in (429, 500, 502, 503, 504):
                if log_cb:
                    log_cb(f"Debug: Jikan HTTP {r.status_code}; retrying")
                time.sleep(1.0 * attempt)
                continue
            r.raise_for_status()
            js = r.json()
            if not isinstance(js, dict):
                raise RuntimeError("Unexpected Jikan response")
            return js
        except Exception as e:
            last_exc = e
            if attempt < 3:
                time.sleep(1.0 * attempt)
            continue

    raise RuntimeError(f"Jikan request failed: {last_exc}")


def _jikan_title_and_themes(anime_id: int, timeout_s: int, log_cb: Optional[LogCb]) -> Tuple[str, List[str], List[str], Optional[str]]:
    a = _jikan_get_json(f"/anime/{anime_id}", timeout_s=timeout_s, log_cb=log_cb)
    title = ""
    year = None
    data = a.get("data") if isinstance(a, dict) else None
    if isinstance(data, dict):
        title = str(data.get("title") or "").strip()
        aired = data.get("aired")
        if isinstance(aired, dict):
            from_iso = aired.get("from")
            if from_iso and isinstance(from_iso, str) and len(from_iso) >= 4:
                year = from_iso[:4]

    year = _find_first_season_year(anime_id, timeout_s, log_cb, year)

    t = _jikan_get_json(f"/anime/{anime_id}/themes", timeout_s=timeout_s, log_cb=log_cb)
    td = t.get("data") if isinstance(t, dict) else None
    openings: List[str] = []
    endings: List[str] = []
    if isinstance(td, dict):
        ops = td.get("openings")
        eds = td.get("endings")
        if isinstance(ops, list):
            openings = [str(x).strip() for x in ops if str(x).strip()]
        if isinstance(eds, list):
            endings = [str(x).strip() for x in eds if str(x).strip()]

    if log_cb:
        log_cb(f"Debug: Jikan title '{title}'")
        log_cb(f"Debug: Jikan openings {len(openings)}")
        log_cb(f"Debug: Jikan endings {len(endings)}")
        if year:
            log_cb(f"Debug: First season year: {year}")

    return title, openings, endings, year


def _find_first_season_year(anime_id: int, timeout_s: int, log_cb: Optional[LogCb], current_year: Optional[str]) -> Optional[str]:
    visited = set()
    current_id = anime_id

    while current_id not in visited:
        visited.add(current_id)

        r = _jikan_get_json(f"/anime/{current_id}/relations", timeout_s=timeout_s, log_cb=log_cb)
        relations = r.get("data") if isinstance(r, dict) else None

        prequel_id = None
        if isinstance(relations, list):
            for rel in relations:
                rel_dict = rel if isinstance(rel, dict) else {}
                rel_type = rel_dict.get("relation")
                if rel_type and "prequel" in rel_type.lower():
                    entries = rel_dict.get("entry")
                    if isinstance(entries, list) and entries:
                        first_entry = entries[0]
                        if isinstance(first_entry, dict):
                            mal_url = first_entry.get("url") or ""
                            prequel_id = _extract_mal_anime_id(mal_url)
                            if prequel_id:
                                if log_cb:
                                    prequel_title = first_entry.get("name", "")
                                    log_cb(f"Debug: Found prequel: {prequel_title} (id {prequel_id})")
                                break

        if prequel_id:
            a = _jikan_get_json(f"/anime/{prequel_id}", timeout_s=timeout_s, log_cb=log_cb)
            data = a.get("data") if isinstance(a, dict) else None
            if isinstance(data, dict):
                aired = data.get("aired")
                if isinstance(aired, dict):
                    from_iso = aired.get("from")
                    if from_iso and isinstance(from_iso, str) and len(from_iso) >= 4:
                        current_year = from_iso[:4]
                        if log_cb:
                            log_cb(f"Debug: Prequel year: {current_year}")
            current_id = prequel_id
        else:
            break

    return current_year


def _html_title_and_themes(mal_url: str, timeout_s: int, log_cb: Optional[LogCb]) -> Tuple[str, List[str], List[str]]:
    url = _normalize_mal_url(mal_url)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    if log_cb:
        log_cb(f"Debug: MAL HTML request starting")
        log_cb(f"Debug: GET {url}")
        log_cb(f"Debug: Timeout {timeout_s}s")

    t = (min(10, timeout_s), timeout_s)
    r = requests.get(url, timeout=t, headers=headers, allow_redirects=True)

    if log_cb:
        log_cb(f"Debug: HTTP {r.status_code}")
        if r.url and r.url != url:
            log_cb(f"Debug: Final URL {r.url}")
        ct = (r.headers.get("content-type") or "").strip()
        if ct:
            log_cb(f"Debug: Content-Type {ct}")
        log_cb(f"Debug: Response bytes {len(r.content)}")

    r.raise_for_status()

    text_l = (r.text or "").lower()
    if "captcha" in text_l or "cloudflare" in text_l or "ddos" in text_l:
        raise RuntimeError(
            "MyAnimeList may be blocking automated requests (captcha/bot-check). Try again later or use the API method."
        )

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


def scrape_mal_title_and_themes(
    mal_url: str,
    timeout_s: int = 20,
    log_cb: Optional[LogCb] = None,
) -> Tuple[str, List[str], List[str], Optional[str]]:
    anime_id = _extract_mal_anime_id(mal_url)
    if anime_id:
        if log_cb:
            log_cb(f"Debug: MAL anime id {anime_id}")
        try:
            return _jikan_title_and_themes(anime_id, timeout_s=timeout_s, log_cb=log_cb)
        except Exception as e:
            if log_cb:
                log_cb(f"Debug: Jikan failed, falling back to HTML: {e}")

    title, openings, endings = _html_title_and_themes(mal_url, timeout_s=timeout_s, log_cb=log_cb)
    return title, openings, endings, None


def tvdb_search_url(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    return f"https://thetvdb.com/search?query={requests.utils.quote(q)}"
