"""Test MAL parsing functions against real MAL HTML fixtures.

Fixtures are downloaded by `tests/download_fixtures.py` and stored in
`tests/fixtures/`. Each fixture is a complete HTML page from myanimelist.net.

Run tests with:
    python -m pytest tests/test_mal_parsing.py -v
"""

import os
from typing import Dict, List, Optional, Tuple

import pytest
from bs4 import BeautifulSoup

from opeddl_app.mal import (
    _dedupe,
    _extract_mal_anime_id,
    _html_extract_title,
    _html_extract_year,
    _html_find_prequel_url,
    _normalize_mal_url,
    parse_mal_themes_from_soup,
    tvdb_search_url,
)

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load_fixture(anime_id: int) -> BeautifulSoup:
    path = os.path.join(FIXTURES_DIR, f"mal_{anime_id}.html")
    with open(path, encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


# ---------------------------------------------------------------------------
# Fixture metadata – expected values verified against real MAL pages
# ---------------------------------------------------------------------------

FIXTURE_EXPECTATIONS: Dict[int, Dict] = {
    1: {
        "title": "Cowboy Bebop",
        "year": "1998",
        "prequel": None,
        "openings": ["Tank! The Seatbelts"],
        "endings": [
            "The Real Folk Blues The Seatbelts feat. Mai Yamane",
            "Space Lion The Seatbelts",
            "Blue The Seatbelts feat. Mai Yamane",
        ],
    },
    5114: {
        "title": "Fullmetal Alchemist: Brotherhood",
        "year": "2009",
        "prequel": None,
        "openings": [
            "again YUI",
            "Hologram (ホログラム) NICO Touches the Walls",
            "Golden Time Lover (ゴールデンタイムラバー) Sukima Switch",
            "Period Chemistry",
            "Rain (レイン) SID",
        ],
        "endings": [
            "Uso (嘘) SID",
            "LET IT OUT Miho Fukuhara",
            "Tsunaida Te (つないだ手) Lil'B",
            "Shunkan Sentimental (瞬間センチメンタル) SCANDAL",
            "RAY OF LIGHT Nakagawa Shouko",
            "Rain (レイン) SID",
            "Hologram (ホログラム) NICO Touches the Walls",
        ],
    },
    16498: {
        "title": "Shingeki no Kyojin",
        "year": "2013",
        "prequel": None,
        "openings": [
            "Guren no Yumiya (紅蓮の弓矢) Linked Horizon",
            "Jiyuu no Tsubasa (自由の翼) Linked Horizon",
        ],
        "endings": [
            "Utsukushiki Zankoku na Sekai (美しき残酷な世界) Yoko Hikasa",
            "great escape Cinema Staff",
        ],
    },
    30276: {
        "title": "One Punch Man",
        "year": "2015",
        "prequel": None,
        "openings": [
            "THE HERO !! ~Okoreru Kobushi ni Hi wo Tsukero~ "
            "(THE HERO !! ～怒れる拳に火をつけろ～) JAM Project",
        ],
        "endings": [
            "Hoshi yori Saki ni Mitsukete Ageru "
            "(星より先に見つけてあげる) Hiroko Moriguchi",
            "Kanashimitachi wo Dakishimete "
            "(悲しみたちを抱きしめて) Hiroko Moriguchi",
        ],
    },
    21: {
        "title": "One Piece",
        "year": "1999",
        "prequel": None,
        "openings_count": 30,
        "endings_count": 27,
    },
    11061: {
        "title": "Hunter x Hunter (2011)",
        "year": "2011",
        "prequel": None,
        "openings": [
            "departure! Ono Masatoshi",
            "departure! -second version- Ono Masatoshi",
            "departure! -Opening Tokubetsu-hen- Ono Masatoshi",
        ],
        "endings_count": 9,
    },
    32551: {
        "title": "Digimon Adventure tri. 3: Kokuhaku",
        "year": "2016",
        "prequel": "https://myanimelist.net/anime/32108/Digimon_Adventure_tri_2__Ketsui",
        "openings": ["Butter-Fly～tri. Version～ Kouji Wada"],
        "endings": ["Boku ni Totte (僕にとって) KNIFE OF DAY"],
    },
    35760: {
        "title": "Shingeki no Kyojin Season 3",
        "year": "2018",
        "prequel": "https://myanimelist.net/anime/25777/Shingeki_no_Kyojin_Season_2",
        "openings": ["Red Swan YOSHIKI feat. HYDE"],
        "endings": ["Akatsuki no Chinkonka (暁の鎮魂歌) Linked Horizon"],
    },
}


# ---------------------------------------------------------------------------
# Parametrized fixture IDs
# ---------------------------------------------------------------------------

ALL_FIXTURE_IDS = list(FIXTURE_EXPECTATIONS.keys())
FIXTURE_IDS_WITH_PREQUEL = [
    aid for aid, exp in FIXTURE_EXPECTATIONS.items() if exp.get("prequel")
]
FIXTURE_IDS_WITHOUT_PREQUEL = [
    aid for aid, exp in FIXTURE_EXPECTATIONS.items() if not exp.get("prequel")
]


# ---------------------------------------------------------------------------
# Tests: _html_extract_title
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anime_id", ALL_FIXTURE_IDS)
def test_extract_title(anime_id: int):
    soup = _load_fixture(anime_id)
    expected = FIXTURE_EXPECTATIONS[anime_id]["title"]
    assert _html_extract_title(soup) == expected


# ---------------------------------------------------------------------------
# Tests: _html_extract_year
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anime_id", ALL_FIXTURE_IDS)
def test_extract_year(anime_id: int):
    soup = _load_fixture(anime_id)
    expected = FIXTURE_EXPECTATIONS[anime_id]["year"]
    assert _html_extract_year(soup) == expected


# ---------------------------------------------------------------------------
# Tests: _html_find_prequel_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anime_id", FIXTURE_IDS_WITH_PREQUEL)
def test_find_prequel_url_present(anime_id: int):
    soup = _load_fixture(anime_id)
    expected = FIXTURE_EXPECTATIONS[anime_id]["prequel"]
    assert _html_find_prequel_url(soup) == expected


@pytest.mark.parametrize("anime_id", FIXTURE_IDS_WITHOUT_PREQUEL)
def test_find_prequel_url_absent(anime_id: int):
    soup = _load_fixture(anime_id)
    assert _html_find_prequel_url(soup) is None


# ---------------------------------------------------------------------------
# Tests: parse_mal_themes_from_soup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anime_id", ALL_FIXTURE_IDS)
def test_parse_openings(anime_id: int):
    soup = _load_fixture(anime_id)
    exp = FIXTURE_EXPECTATIONS[anime_id]
    ops, _eds = parse_mal_themes_from_soup(soup)
    if "openings" in exp:
        assert ops == exp["openings"]
    elif "openings_count" in exp:
        assert len(ops) == exp["openings_count"]


@pytest.mark.parametrize("anime_id", ALL_FIXTURE_IDS)
def test_parse_endings(anime_id: int):
    soup = _load_fixture(anime_id)
    exp = FIXTURE_EXPECTATIONS[anime_id]
    _ops, eds = parse_mal_themes_from_soup(soup)
    if "endings" in exp:
        assert eds == exp["endings"]
    elif "endings_count" in exp:
        assert len(eds) == exp["endings_count"]


@pytest.mark.parametrize("anime_id", ALL_FIXTURE_IDS)
def test_parse_themes_non_empty(anime_id: int):
    """Every fixture should have at least one opening and one ending."""
    soup = _load_fixture(anime_id)
    ops, eds = parse_mal_themes_from_soup(soup)
    assert len(ops) >= 1, f"anime {anime_id}: expected at least 1 opening"
    assert len(eds) >= 1, f"anime {anime_id}: expected at least 1 ending"


# ---------------------------------------------------------------------------
# Tests: _dedupe
# ---------------------------------------------------------------------------


def test_dedupe_basic():
    assert _dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_dedupe_case_insensitive():
    assert _dedupe(["Tank!", "tank!", "TANK!"]) == ["Tank!"]


def test_dedupe_empty():
    assert _dedupe([]) == []


def test_dedupe_preserves_order():
    assert _dedupe(["c", "a", "b", "a"]) == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# Tests: _extract_mal_anime_id
# ---------------------------------------------------------------------------


def test_extract_mal_anime_id_standard():
    assert _extract_mal_anime_id("https://myanimelist.net/anime/5114/Fullmetal_Alchemist__Brotherhood") == 5114


def test_extract_mal_anime_id_trailing_slash():
    assert _extract_mal_anime_id("https://myanimelist.net/anime/1/Cowboy_Bebop/") == 1


def test_extract_mal_anime_id_no_slug():
    assert _extract_mal_anime_id("https://myanimelist.net/anime/21") == 21


def test_extract_mal_anime_id_invalid_url():
    assert _extract_mal_anime_id("https://example.com/anime/123") is None


def test_extract_mal_anime_id_empty():
    assert _extract_mal_anime_id("") is None


def test_extract_mal_anime_id_none():
    assert _extract_mal_anime_id(None) is None


# ---------------------------------------------------------------------------
# Tests: _normalize_mal_url
# ---------------------------------------------------------------------------


def test_normalize_url_trailing_slash():
    assert _normalize_mal_url("https://myanimelist.net/anime/1/") == "https://myanimelist.net/anime/1"


def test_normalize_url_no_trailing_slash():
    assert _normalize_mal_url("https://myanimelist.net/anime/1") == "https://myanimelist.net/anime/1"


def test_normalize_url_empty():
    assert _normalize_mal_url("") == ""


def test_normalize_url_none():
    assert _normalize_mal_url(None) == ""


# ---------------------------------------------------------------------------
# Tests: tvdb_search_url
# ---------------------------------------------------------------------------


def test_tvdb_search_url_basic():
    url = tvdb_search_url("Cowboy Bebop")
    assert "thetvdb.com/search" in url
    assert "Cowboy%20Bebop" in url


def test_tvdb_search_url_empty():
    assert tvdb_search_url("") == ""
    assert tvdb_search_url(None) == ""


def test_tvdb_search_url_special_chars():
    url = tvdb_search_url("Shingeki no Kyojin")
    assert "thetvdb.com/search" in url
    assert "Shingeki" in url


# ---------------------------------------------------------------------------
# Tests: parse_mal_themes_from_soup on empty/minimal soup
# ---------------------------------------------------------------------------


def test_parse_themes_empty_html():
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    ops, eds = parse_mal_themes_from_soup(soup)
    assert ops == []
    assert eds == []


def test_parse_themes_no_theme_section():
    soup = BeautifulSoup(
        "<html><body><div>Some content</div></body></html>",
        "html.parser",
    )
    ops, eds = parse_mal_themes_from_soup(soup)
    assert ops == []
    assert eds == []


# ---------------------------------------------------------------------------
# Tests: _html_extract_title on empty soup
# ---------------------------------------------------------------------------


def test_extract_title_empty_soup():
    soup = BeautifulSoup("<html></html>", "html.parser")
    assert _html_extract_title(soup) == ""


def test_extract_year_empty_soup():
    soup = BeautifulSoup("<html></html>", "html.parser")
    assert _html_extract_year(soup) is None


def test_find_prequel_empty_soup():
    soup = BeautifulSoup("<html></html>", "html.parser")
    assert _html_find_prequel_url(soup) is None
