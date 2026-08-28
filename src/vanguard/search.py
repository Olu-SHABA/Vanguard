"""
Search links — built, never followed.

LinkedIn's User Agreement prohibits **automated collection**. It does not
prohibit searching: opening a search page in a browser is what the site is
for.

So this constructs the URL and prints it. Vanguard makes no request. The
operator clicks the link, LinkedIn serves the page to their browser as a
normal human visit, and they read the results themselves.

That distinction is the whole basis of this module, and it is worth being
precise about:

    building a URL        writing down where to look
    following a URL       automated collection

Nothing here does the second. There is no HTTP client, no session, no
cookie, and no parsing of anything LinkedIn returns.

## Why it is worth having

A LinkedIn search with the right filters is a long URL nobody types by hand:

    ?keywords=data%20scientist&geoId=...&f_TPR=r21600&sortBy=DD

`f_TPR=r21600` means "posted in the last 21,600 seconds" — six hours. Nobody
remembers that. Vanguard does, and prints the link.

## The same shape works elsewhere

Indeed, Totaljobs and CV-Library all drive their search from the query
string. A board is added by describing its parameters, not by writing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote_plus

__all__ = [
    "SearchWindow",
    "SearchSpec",
    "WINDOWS",
    "build_search_url",
    "SEARCHABLE",
]


#: How recent a posting must be, in seconds.
#:
#: LinkedIn's `f_TPR` parameter takes `r` followed by a number of seconds.
#: Six hours is `r21600`. Nobody remembers that, which is why it is here.
WINDOWS: dict[str, int] = {
    "6h": 6 * 3600,
    "12h": 12 * 3600,
    "24h": 24 * 3600,
    "3d": 3 * 86400,
    "1w": 7 * 86400,
    "2w": 14 * 86400,
    "1m": 30 * 86400,
    "any": 0,
}


@dataclass(frozen=True)
class SearchSpec:
    """One board's search URL, described rather than coded.

    `params` maps a Vanguard concept to that board's parameter name. A board
    that does not support a filter simply omits it — the URL is built from
    what is present, so nothing has to be special-cased.
    """

    board_id: str
    base: str
    params: dict[str, str] = field(default_factory=dict)
    #: How this board expresses "posted within N seconds". `{seconds}` and
    #: `{days}` are substituted.
    recency_format: str = ""
    note: str = ""

    def supports(self, name: str) -> bool:
        return name in self.params or (name == "recency" and
                                       bool(self.recency_format))


#: Boards whose search is driven by the query string.
#:
#: Adding one is a matter of describing its parameters. No adapter, no HTTP,
#: no code — the operator opens the link.
SEARCHABLE: tuple[SearchSpec, ...] = (
    SearchSpec(
        board_id="linkedin",
        base="https://www.linkedin.com/jobs/search/",
        params={
            "keywords": "keywords",
            "location": "location",
            "remote": "f_WT",
            "job_type": "f_JT",
            "experience": "f_E",
            "sort": "sortBy",
        },
        recency_format="r{seconds}",
        note=("Searching is permitted; automated collection is not. Vanguard "
              "builds the link and stops — the operator opens it."),
    ),
    SearchSpec(
        board_id="indeed",
        base="https://uk.indeed.com/jobs",
        params={"keywords": "q", "location": "l", "sort": "sort"},
        recency_format="{days}",
        note="`fromage` takes days rather than seconds.",
    ),
    SearchSpec(
        board_id="totaljobs",
        base="https://www.totaljobs.com/jobs",
        params={"keywords": "Keywords", "location": "Location"},
        recency_format="{days}",
        note="`postedwithin` takes days.",
    ),
    SearchSpec(
        board_id="cv_library",
        base="https://www.cv-library.co.uk/search-jobs",
        params={"keywords": "q", "location": "geo"},
        recency_format="{days}",
        note="`posted` takes days.",
    ),
)

#: Board-specific names for the recency parameter itself.
_RECENCY_PARAM = {
    "linkedin": "f_TPR",
    "indeed": "fromage",
    "totaljobs": "postedwithin",
    "cv_library": "posted",
}

#: Values a board expects for filters Vanguard names generically.
_VALUES = {
    "linkedin": {
        "remote": {"remote": "2", "hybrid": "3", "onsite": "1"},
        "job_type": {"full": "F", "part": "P", "contract": "C",
                     "temporary": "T", "internship": "I"},
        "experience": {"entry": "2", "associate": "3", "mid": "4",
                       "senior": "5", "director": "6"},
        "sort": {"date": "DD", "relevance": "R"},
    },
    "indeed": {"sort": {"date": "date", "relevance": "relevance"}},
}


def spec_for(board_id: str) -> SearchSpec | None:
    return next((s for s in SEARCHABLE if s.board_id == board_id), None)


def build_search_url(board_id: str, *, keywords: str = "", location: str = "",
                     window: str = "any", remote: str = "", job_type: str = "",
                     experience: str = "", sort: str = "date") -> str:
    """Construct a search URL. **Nothing is fetched.**

    Unsupported filters are dropped rather than raising: a board that cannot
    filter by experience should still produce a usable link for the filters
    it does support.
    """
    spec = spec_for(board_id)
    if spec is None:
        known = ", ".join(s.board_id for s in SEARCHABLE)
        raise ValueError(f"no search spec for {board_id!r}. Known: {known}")

    values = _VALUES.get(board_id, {})
    wanted = {
        "keywords": keywords,
        "location": location,
        "remote": values.get("remote", {}).get(remote, "") if remote else "",
        "job_type": values.get("job_type", {}).get(job_type, "") if job_type else "",
        "experience": (values.get("experience", {}).get(experience, "")
                       if experience else ""),
        "sort": values.get("sort", {}).get(sort, "") if sort else "",
    }

    parts: list[str] = []
    for name, value in wanted.items():
        if not value or name not in spec.params:
            continue
        parts.append(f"{spec.params[name]}={quote_plus(str(value))}")

    seconds = WINDOWS.get(window, 0)
    if seconds and spec.recency_format:
        recency = spec.recency_format.format(
            seconds=seconds, days=max(1, seconds // 86400))
        parts.append(f"{_RECENCY_PARAM[board_id]}={quote_plus(recency)}")

    return spec.base + ("?" + "&".join(parts) if parts else "")
