import re
from typing import Callable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup


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


def _parse_theme_section(soup: BeautifulSoup, css_class: str) -> List[str]:
    results: List[str] = []
    div = soup.select_one(f"div.theme-songs.{css_class}")
    if not div:
        return results
    for popup in div.select("div.oped-popup"):
        popup.decompose()
    for script in div.find_all("script"):
        script.decompose()
    for row in div.select("tr"):
        artist_span = row.select_one("span.theme-song-artist")
        artist = ""
        if artist_span:
            artist = artist_span.get_text(strip=True)
            artist = re.sub(r"^by\s+", "", artist, flags=re.IGNORECASE).strip()

        title_span = row.select_one("span.theme-song-title")
        if title_span:
            song_title = title_span.get_text(strip=True).strip().strip('"').strip()
        else:
            content_td = None
            for td in row.select("td"):
                if td.get("width") == "84%":
                    content_td = td
                    break
            if not content_td:
                content_td = row.select_one("td")
            if not content_td:
                continue
            for s in content_td.find_all("span"):
                s.extract()
            for hidden in content_td.find_all("input"):
                hidden.extract()
            raw = content_td.get_text(strip=True)
            raw = raw.lstrip(":").strip()
            m = re.match(r'^"(.+)"', raw)
            if m:
                song_title = m.group(1).strip()
            else:
                m2 = re.match(r'^(.+?)(?:\s*\(eps.*)?$', raw)
                song_title = (m2.group(1) if m2 else raw).strip().strip('"').strip()

        if not song_title:
            continue
        query = f"{song_title} {artist}".strip()
        if query:
            results.append(query)
    return results


def _parse_themes_regex_fallback(soup: BeautifulSoup) -> Tuple[List[str], List[str]]:
    openings: List[str] = []
    endings: List[str] = []

    candidates = soup.select("div.theme-songs")
    text_blocks: List[str] = []
    for c in candidates:
        for script in c.find_all("script"):
            script.decompose()
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

    return _dedupe(openings), _dedupe(endings)


def parse_mal_themes_from_soup(soup: BeautifulSoup) -> Tuple[List[str], List[str]]:
    openings = _parse_theme_section(soup, "opnening")
    endings = _parse_theme_section(soup, "ending")

    if not openings and not endings:
        openings, endings = _parse_themes_regex_fallback(soup)

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


_MAL_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_BOT_TITLES = ("just a moment", "attention required", "access denied", "cloudflare")


def _html_fetch_page(url: str, timeout_s: int, log_cb: Optional[LogCb]) -> BeautifulSoup:
    url = _normalize_mal_url(url)

    if log_cb:
        log_cb("Debug: MAL HTML request starting")
        log_cb(f"Debug: GET {url}")
        log_cb(f"Debug: Timeout {timeout_s}s")

    t = (min(10, timeout_s), timeout_s)
    r = requests.get(url, timeout=t, headers=_MAL_HEADERS, allow_redirects=True)

    if log_cb:
        log_cb(f"Debug: HTTP {r.status_code}")
        if r.url and r.url != url:
            log_cb(f"Debug: Final URL {r.url}")
        ct = (r.headers.get("content-type") or "").strip()
        if ct:
            log_cb(f"Debug: Content-Type {ct}")
        log_cb(f"Debug: Response bytes {len(r.content)}")

    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    page_title = (soup.title.string or "").strip().lower() if soup.title else ""
    if any(bt in page_title for bt in _BOT_TITLES):
        raise RuntimeError(
            "MyAnimeList may be blocking automated requests (captcha/bot-check). Try again later."
        )

    return soup


def _html_extract_title(soup: BeautifulSoup) -> str:
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return str(og.get("content")).strip()

    h1 = soup.select_one("h1.title-name")
    if h1:
        return h1.get_text(" ", strip=True)

    breadcrumbs = soup.select("div.breadcrumb span[itemprop='name']")
    if breadcrumbs:
        return breadcrumbs[-1].get_text(strip=True)

    return ""


def _html_extract_year(soup: BeautifulSoup) -> Optional[str]:
    season_span = soup.select_one("span.information.season a")
    if season_span:
        text = season_span.get_text(strip=True)
        m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        if m:
            return m.group(1)

    for info_div in soup.select("div.spaceit_pad"):
        text = info_div.get_text(" ", strip=True)
        if text.startswith("Aired:"):
            m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
            if m:
                return m.group(1)

    return None


def _html_find_prequel_url(soup: BeautifulSoup) -> Optional[str]:
    related = soup.select_one("div.related-entries")
    if not related:
        return None

    for entry in related.select("div.entry"):
        rel_div = entry.select_one("div.relation")
        if not rel_div:
            continue
        rel_text = rel_div.get_text(" ", strip=True).lower()
        if "prequel" not in rel_text:
            continue
        title_div = entry.select_one("div.title a")
        if title_div and title_div.get("href"):
            href = str(title_div["href"])
            if "myanimelist.net/anime/" in href:
                return href

    return None


def _html_find_first_season_year(
    mal_url: str,
    timeout_s: int,
    log_cb: Optional[LogCb],
    current_year: Optional[str],
) -> Optional[str]:
    visited: set = set()
    current_url = mal_url

    while current_url and current_url not in visited:
        visited.add(current_url)

        soup = _html_fetch_page(current_url, timeout_s=timeout_s, log_cb=log_cb)

        year = _html_extract_year(soup)
        if year:
            current_year = year
            if log_cb:
                log_cb(f"Debug: Prequel year: {year}")

        prequel_url = _html_find_prequel_url(soup)
        if not prequel_url:
            break

        if log_cb:
            prequel_id = _extract_mal_anime_id(prequel_url)
            log_cb(f"Debug: Found prequel: {prequel_url} (id {prequel_id})")

        current_url = prequel_url

    return current_year


def scrape_mal_title_and_themes(
    mal_url: str,
    timeout_s: int = 20,
    log_cb: Optional[LogCb] = None,
    skip_relation_check: bool = False,
) -> Tuple[str, List[str], List[str], Optional[str]]:
    anime_id = _extract_mal_anime_id(mal_url)
    if log_cb:
        log_cb(f"Debug: MAL anime id {anime_id}")
        if skip_relation_check:
            log_cb("Debug: Skipping prequel year lookup")

    soup = _html_fetch_page(mal_url, timeout_s=timeout_s, log_cb=log_cb)

    title = _html_extract_title(soup)
    openings, endings = parse_mal_themes_from_soup(soup)
    year = _html_extract_year(soup)

    if not skip_relation_check:
        prequel_url = _html_find_prequel_url(soup)
        if prequel_url:
            year = _html_find_first_season_year(
                prequel_url, timeout_s=timeout_s, log_cb=log_cb, current_year=year
            )

    if log_cb:
        log_cb(f"Debug: HTML title '{title}'")
        log_cb(f"Debug: HTML openings {len(openings)}")
        log_cb(f"Debug: HTML endings {len(endings)}")
        if year:
            log_cb(f"Debug: First season year: {year}")

    return title, openings, endings, year


def tvdb_search_url(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    return f"https://thetvdb.com/search?query={requests.utils.quote(q)}"
