"""Search links — built, never followed."""
from __future__ import annotations

import pytest

from vanguard.search import (
    SEARCHABLE,
    WINDOWS,
    build_search_url,
    spec_for,
)


# --- the distinction this module rests on ---------------------------------

def test_nothing_in_this_module_fetches_anything() -> None:
    """LinkedIn's User Agreement prohibits automated COLLECTION, not
    searching. Building a URL is writing down where to look; following it is
    the thing that must not happen here.

    Asserted structurally, because a later edit could introduce it by
    accident.
    """
    from pathlib import Path

    import vanguard.search as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    code = "\n".join(line.split("#")[0] for line in source.splitlines()
                     if not line.strip().startswith("#"))

    for forbidden in ("import httpx", "import requests", "urlopen",
                      "urllib.request", "requests.Session", "webbrowser",
                      "selenium", "playwright", "client.get", "client.post"):
        assert forbidden not in code, f"{forbidden} has no business here"

    # The only network-adjacent import permitted is URL quoting.
    imports = [line.strip() for line in code.splitlines()
               if line.strip().startswith(("import ", "from "))]
    assert all("urllib.parse" in line or "urllib" not in line
               for line in imports)


# --- windows --------------------------------------------------------------

@pytest.mark.parametrize(
    "window, seconds",
    [("6h", 21600), ("12h", 43200), ("24h", 86400), ("1w", 604800),
     ("2w", 1209600)],
)
def test_recency_windows_are_correct(window: str, seconds: int) -> None:
    """`f_TPR=r21600` means "posted in the last 21,600 seconds". Nobody
    remembers that, which is the point of the command."""
    assert WINDOWS[window] == seconds
    url = build_search_url("linkedin", keywords="data scientist", window=window)
    assert f"f_TPR=r{seconds}" in url


def test_any_time_omits_the_filter() -> None:
    assert "f_TPR" not in build_search_url("linkedin", keywords="x", window="any")


def test_a_board_taking_days_gets_days() -> None:
    """Indeed's `fromage` is days, not seconds."""
    assert "fromage=7" in build_search_url("indeed", keywords="x", window="1w")


# --- filters --------------------------------------------------------------

def test_filters_combine() -> None:
    url = build_search_url("linkedin", keywords="data scientist",
                           location="Bristol", window="24h", remote="remote",
                           experience="senior", sort="date")
    for fragment in ("keywords=data+scientist", "location=Bristol",
                     "f_WT=2", "f_E=5", "sortBy=DD", "f_TPR=r86400"):
        assert fragment in url, fragment


def test_an_unsupported_filter_is_dropped_not_raised() -> None:
    """A board that cannot filter by seniority should still produce a usable
    link for the filters it does support."""
    url = build_search_url("totaljobs", keywords="data scientist",
                           location="Bristol", experience="senior")
    assert "Keywords=data+scientist" in url
    assert "Location=Bristol" in url


def test_keywords_are_encoded() -> None:
    url = build_search_url("linkedin", keywords="data scientist & analyst")
    assert " " not in url
    assert "&analyst" not in url, "an unescaped ampersand would split the query"


def test_an_unknown_board_is_refused() -> None:
    with pytest.raises(ValueError, match="no search spec"):
        build_search_url("nonesuch", keywords="x")


# --- the specs themselves -------------------------------------------------

def test_every_spec_has_a_base_and_keywords() -> None:
    for spec in SEARCHABLE:
        assert spec.base.startswith("https://")
        assert "keywords" in spec.params, f"{spec.board_id} cannot be searched"


def test_linkedin_records_why_it_is_here() -> None:
    """The note is the reasoning. Losing it would leave the next reader to
    guess whether this is permitted."""
    spec = spec_for("linkedin")
    assert spec is not None
    assert "collection" in spec.note.lower()
