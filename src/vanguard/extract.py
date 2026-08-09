"""
Requirement extraction: advert text -> term list R.

The hardest and least-specified component in the system. C = |matched| / |R|,
so anything wrong here is wrong everywhere downstream.

Deliberately crude by design, per BUILD_PLAN §2.2. It extracts from person-
specification sections in preference to body prose, because a term inside
"Essential" is a requirement and the same term in a benefits paragraph is not.
Refinement happens against real adverts, not in advance.

Two extraction kinds:

  tool        a named technology from a curated vocabulary. High confidence.
  competency  a requirement phrase with no named technology. Lower confidence,
              matched semantically downstream.

Extraction is deterministic and inspectable: every Requirement records the
section it came from, so a wrong coverage score can always be traced back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

__all__ = [
    "Requirement",
    "html_to_text",
    "closing_date",
    "is_closed",
    "looks_like_html",
    "TECHNOLOGY_VOCABULARY",
    "extract",
    "extract_sections",
]

Kind = Literal["tool", "competency"]


# ---------------------------------------------------------------------------
# Curated technology vocabulary
# ---------------------------------------------------------------------------
# Canonical form -> surface variants. Matching is whole-phrase, case-insensitive,
# word-boundary anchored. Bare-substring matching is prohibited: "R" would fire
# on every capital R, and "Go" on "Google".

TECHNOLOGY_VOCABULARY: dict[str, tuple[str, ...]] = {
    # languages
    "Python": ("python", "python3", "python 3"),
    "SQL": ("sql", "t-sql", "tsql", "pl/sql"),
    "R": ("r programming", "r language"),
    "Java": ("java",),
    "Scala": ("scala",),
    "JavaScript": ("javascript", "typescript", "node.js", "nodejs"),
    "Bash": ("bash", "shell scripting"),
    # data stack
    "pandas": ("pandas",),
    "NumPy": ("numpy",),
    "Spark": ("spark", "pyspark", "apache spark"),
    "Hadoop": ("hadoop",),
    "Airflow": ("airflow", "apache airflow"),
    "dbt": ("dbt",),
    "Kafka": ("kafka", "apache kafka"),
    "Snowflake": ("snowflake",),
    "Databricks": ("databricks",),
    # databases
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",),
    "SQL Server": ("sql server", "microsoft sql", "mssql"),
    "MongoDB": ("mongodb", "mongo"),
    "Redis": ("redis",),
    # ml
    "scikit-learn": ("scikit-learn", "sklearn", "scikit learn"),
    "TensorFlow": ("tensorflow",),
    "PyTorch": ("pytorch",),
    "MLflow": ("mlflow",),
    # cloud
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure", "microsoft azure"),
    "GCP": ("gcp", "google cloud"),
    "S3": ("s3",),
    "Lambda": ("aws lambda",),
    "Terraform": ("terraform",),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    # engineering practice
    "git": ("git", "version control"),
    "GitHub Actions": ("github actions",),
    "Jenkins": ("jenkins",),
    "CI/CD": ("ci/cd", "continuous integration", "continuous deployment"),
    "pytest": ("pytest", "unit testing", "unit tests"),
    "SDLC": ("software development lifecycle", "sdlc"),
    # bi
    "Tableau": ("tableau",),
    "Power BI": ("power bi", "powerbi"),
    "Looker": ("looker",),
    "Excel": ("excel", "microsoft excel"),
    # networks / infrastructure
    "Cisco": ("cisco",),
    "Juniper": ("juniper",),
    "VSAT": ("vsat",),
    "ITIL": ("itil",),
    "Linux": ("linux", "unix"),
    # methods
    "machine learning": ("machine learning", "ml models", "predictive modelling",
                         "predictive modeling"),
    "ETL": ("etl", "elt", "extract transform load"),
    "A/B testing": ("a/b testing", "ab testing", "split testing"),
    "time series": ("time series", "time-series"),
    "NLP": ("nlp", "natural language processing"),
    "data wrangling": ("data wrangling", "data cleaning", "data manipulation"),
    "data visualisation": ("data visualisation", "data visualization",
                           "dashboards", "business intelligence"),
    "stakeholder management": ("stakeholder management", "stakeholder engagement"),
    "agile": ("agile", "scrum", "kanban"),
}

# Headings that introduce requirements. Ordered by strength.
_SPEC_HEADINGS = (
    "person specification",
    "essential criteria",
    "essential skills",
    "essential",
    "requirements",
    "we are looking for",
    "you will have",
    "about you",
    "skills and experience",
    "key skills",
    "qualifications",
    "desirable",
    "key responsibilities",
    "responsibilities",
)

_DESIRABLE = ("desirable", "nice to have", "bonus", "advantageous")

_BULLET_LINE = re.compile(r"^\s*(?:[-*\u2022\u25cf\u25cb\u25aa\u2043]|\d+[.)])\s+(?P<text>.+?)\s*$")
# Civil Service Behaviours are assessed at INTERVIEW, not in the sift. They are
# not skills to be matched against a CV, and counting them inflates |R| —
# depressing coverage on every Success Profile advert. `submission.detect()`
# extracts them separately, where they belong.
_BEHAVIOURS = frozenset({
    "changing and improving",
    "communicating and influencing",
    "delivering at pace",
    "developing self and others",
    "leadership",
    "making effective decisions",
    "managing a quality service",
    "seeing the big picture",
    "working together",
})

_STOPWORD_ONLY = re.compile(
    r"^(?:and|or|the|a|an|of|in|to|for|with|as|is|are|be|will|you|we|our|your)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Requirement:
    """One extracted requirement. `text` is verbatim from the advert.

    `source_bullet` retains the FULL advert line. `text` may be a trimmed
    phrase, and trimming can discard the clause that carries the evidence:
    "communicating with stakeholders, and translating user needs" trims to the
    first clause, but "translating user needs" is the half that matches the
    alias table. Resolution tries both.
    """

    text: str
    kind: Kind
    section: str
    essential: bool = True
    canonical: str | None = None  # set for tools: the vocabulary key
    source_bullet: str = ""       # full advert line, before trimming

    @property
    def match_texts(self) -> tuple[str, ...]:
        """Strings to try when resolving. Trimmed phrase first, then the full line."""
        out = [self.canonical or self.text]
        if self.source_bullet and self.source_bullet != self.text:
            out.append(self.source_bullet)
        return tuple(out)

    @property
    def key(self) -> str:
        """Identity for deduplication and coverage arithmetic."""
        return (self.canonical or self.text).strip().lower()

    def __str__(self) -> str:
        tag = "tool" if self.kind == "tool" else "comp"
        star = "" if self.essential else " (desirable)"
        return f"[{tag}] {self.canonical or self.text}{star}"



# ---------------------------------------------------------------------------
# HTML normalisation
#
# Reed returns advert bodies as raw HTML. Requirement extraction reads plain
# text and matches bullets at line start, so a `<ul><li>` requirements list is
# invisible to it — there are no line starts in a single string of markup.
#
# A share of the adverts diagnosed as "prose" were structured all along; the
# structure was in tags the parser never stripped.
# ---------------------------------------------------------------------------

_LIST_ITEM = re.compile(r"<li[^>]*>", re.I)
_BREAKS = re.compile(r"</li>|<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>|<hr\s*/?>", re.I)
_BLOCK_START = re.compile(r"<(?:p|div|ul|ol|table|h[1-6])[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&#39;": "'", "&apos;": "'", "&rsquo;": "'", "&lsquo;": "'",
    "&ldquo;": '"', "&rdquo;": '"', "&ndash;": "-", "&mdash;": "-",
    "&bull;": "-", "&pound;": "£", "&hellip;": "...",
}


def looks_like_html(text: str) -> bool:
    return bool(re.search(r"<(?:p|br|li|ul|div|b|strong)\b", text or "", re.I))


def html_to_text(body: str) -> str:
    """Flatten advert HTML to line-structured plain text.

    List items become `- ` bullets so the existing bullet pattern matches;
    block-level closers become newlines so headings sit on their own line.
    """
    if not body:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.I | re.S)
    text = _LIST_ITEM.sub("\n- ", text)
    text = _BREAKS.sub("\n", text)
    text = _BLOCK_START.sub("\n", text)
    text = _TAG.sub(" ", text)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()



# ---------------------------------------------------------------------------
# Closing date
#
# A closed vacancy costs a hydration call against a 60/hour budget and one of
# the 15 result slots per keyword. Filtering BEFORE hydration buys working
# slots, not merely queue hygiene.
# ---------------------------------------------------------------------------

_MONTHS = ("january february march april may june july august september "
           "october november december").split()
_MONTH_INDEX = {m[:3]: i + 1 for i, m in enumerate(_MONTHS)}

_CLOSING_LABEL = re.compile(
    r"(?:closing|close[sd]?|deadline|apply\s+by|applications?\s+close)"
    r"(?:\s+date)?\s*[:\-]?\s*", re.I)

_DATE_PATTERNS = (
    re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})"),        # 9 July 2026
    re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})"),       # July 9, 2026
    re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})"),             # 09/07/2026 (UK)
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),                       # 2026-07-09
)


def closing_date(advert_text: str) -> date | None:
    """Employer's stated closing date, or None. Never guessed.

    An unparseable or absent date returns None, and the caller treats the
    vacancy as open — refusing to process a vacancy on a date we invented
    would be worse than processing a closed one.
    """
    if not advert_text:
        return None
    text = html_to_text(advert_text) if looks_like_html(advert_text) else advert_text

    for label in _CLOSING_LABEL.finditer(text):
        window = text[label.end(): label.end() + 60]
        parsed = _parse_date(window)
        if parsed:
            return parsed
    return None


def _parse_date(fragment: str) -> date | None:
    for i, pattern in enumerate(_DATE_PATTERNS):
        m = pattern.search(fragment)
        if not m:
            continue
        try:
            if i == 0:
                day, month, year = int(m.group(1)), m.group(2)[:3].lower(), int(m.group(3))
                return date(year, _MONTH_INDEX[month], day)
            if i == 1:
                month, day, year = m.group(1)[:3].lower(), int(m.group(2)), int(m.group(3))
                return date(year, _MONTH_INDEX[month], day)
            if i == 2:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except (KeyError, ValueError):
            continue
    return None


def is_closed(advert_text: str, *, today: date | None = None) -> bool:
    """True only when a closing date is stated AND has passed."""
    closes = closing_date(advert_text)
    if closes is None:
        return False
    return closes < (today or date.today())


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------

def extract_sections(text: str) -> dict[str, list[str]]:
    """Split advert text into named blocks keyed by the heading above them.

    Lines before any recognised heading go under 'preamble'. Terms found there
    are weaker evidence than terms under 'Essential'.
    """
    if looks_like_html(text):
        text = html_to_text(text)
    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"

    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue

        stripped = line.strip().rstrip(":").lower()
        matched = next((h for h in _SPEC_HEADINGS if stripped == h or stripped.startswith(h)), None)

        if matched and len(line.strip()) < 70 and not _BULLET_LINE.match(line):
            current = matched
            sections.setdefault(current, [])
            continue

        # A section runs until the next RECOGNISED heading. Unrecognised title
        # lines do not close it: advert lead-ins such as "As a Senior Data
        # Engineer your work might involve:" look like headings and would
        # otherwise discard every bullet beneath them.
        sections.setdefault(current, []).append(line)

    return sections


# ---------------------------------------------------------------------------
# Tool matching
# ---------------------------------------------------------------------------

def _find_tools(text: str) -> list[str]:
    """Canonical tool names present in `text`, whole-phrase anchored."""
    low = text.lower()
    found: list[str] = []
    for canonical, variants in TECHNOLOGY_VOCABULARY.items():
        for variant in variants:
            if re.search(rf"(?<![\w/-]){re.escape(variant)}(?![\w-])", low):
                found.append(canonical)
                break
    return found


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract(advert_text: str, *, include_desirable: bool = True,
            job_title: str = "") -> list[Requirement]:
    """Extract the requirement term list R from advert text.

    One `Requirement` per distinct term. Tools are emitted individually so a
    bullet naming three technologies yields three requirements — coverage must
    be able to report exactly which one failed.

    A bullet with no recognised tool becomes a single competency requirement,
    resolved semantically downstream.

    HTML adverts are parsed structurally first. Only bullets under a heading
    classified as REQUIREMENT contribute: a duty list under "What you will do"
    describes the job rather than a qualification, and counting duties and
    benefits as requirements drove |R| to 38 and coverage to 0.026.

    An HTML advert with NO recognised requirement section returns an empty
    list. There is no flat-text fallback for markup — a wrong score that looks
    right is worse than a refusal, and the refusal surfaces the advert for
    manual review instead.
    """
    if looks_like_html(advert_text):
        structured = _extract_structured(advert_text, include_desirable, job_title)
        if structured is not None:
            return structured
        # No recognised requirement section. Falling back to flat extraction
        # would count duties, benefits and application steps as requirements —
        # which produced |R| of 38 with ceiling 1.000, the system asserting an
        # AI Marketing Operations Manager role was fully attainable.
        #
        # Returning nothing is the honest answer: coverage reports UNRELIABLE
        # ("no requirement terms extracted") and the vacancy is FLAGGED for
        # the operator rather than given a plausible-looking wrong number.
        return []
    sections = extract_sections(advert_text)
    seen: set[str] = set()
    out: list[Requirement] = []

    for name, lines in sections.items():
        if name == "preamble":
            continue
        essential = not any(d in name for d in _DESIRABLE)
        if not essential and not include_desirable:
            continue

        for line in lines:
            m = _BULLET_LINE.match(line)
            if not m:
                continue
            body = m.group("text").strip()
            if len(body) < 8:
                continue

            if body.strip().lower().rstrip(".") in _BEHAVIOURS:
                continue  # interview-stage behaviour, not a sift requirement

            tools = _find_tools(body)
            for tool in tools:
                req = Requirement(body, "tool", name, essential,
                                  canonical=tool, source_bullet=body)
                if req.key not in seen:
                    seen.add(req.key)
                    out.append(req)

            if not tools:
                phrase = _to_competency(body)
                if phrase:
                    req = Requirement(phrase, "competency", name, essential,
                                      source_bullet=body)
                    if req.key not in seen:
                        seen.add(req.key)
                        out.append(req)

    # Fallback: an advert with no bullets under any recognised heading still
    # yields its named technologies rather than scoring zero.
    if not out:
        for tool in _find_tools(advert_text):
            req = Requirement(tool, "tool", "preamble", True,
                              canonical=tool, source_bullet=tool)
            if req.key not in seen:
                seen.add(req.key)
                out.append(req)

    return out


def _extract_structured(body: str, include_desirable: bool,
                        job_title: str = "") -> list[Requirement] | None:
    """Requirements from classified HTML sections, or None if unusable.

    Returns None when the advert has no recognisable requirement section, so
    the caller falls back to flat-text extraction rather than reporting zero.
    """
    from vanguard.structure import SectionKind, parse_advert

    structure = parse_advert(body, job_title=job_title)
    if not structure.has_requirement_section:
        return None

    seen: set[str] = set()
    out: list[Requirement] = []

    for block in structure.of_kind(SectionKind.REQUIREMENT):
        essential = "desirable" not in block.heading.lower()
        if not essential and not include_desirable:
            continue
        section = block.heading or "requirements"

        for body_text in [*block.bullets, *block.paragraphs]:
            body_text = body_text.strip()
            if len(body_text) < 8:
                continue
            if body_text.lower().rstrip(".") in _BEHAVIOURS:
                continue

            tools = _find_tools(body_text)
            for tool in tools:
                req = Requirement(body_text, "tool", section, essential,
                                  canonical=tool, source_bullet=body_text)
                if req.key not in seen:
                    seen.add(req.key)
                    out.append(req)

            if not tools:
                phrase = _to_competency(body_text)
                if phrase:
                    req = Requirement(phrase, "competency", section, essential,
                                      source_bullet=body_text)
                    if req.key not in seen:
                        seen.add(req.key)
                        out.append(req)

    return out or None


def _to_competency(bullet: str) -> str | None:
    """Reduce a requirement bullet to a matchable phrase.

    Trims leading filler ("experience of", "ability to"), drops parentheticals
    and trailing clauses, and rejects anything too short or too generic to
    match meaningfully.
    """
    text = re.sub(r"\([^)]*\)", "", bullet).strip()
    text = re.sub(
        r"^(?:proven\s+|demonstrable\s+|strong\s+|significant\s+|excellent\s+)?"
        r"(?:experience(?:\s+(?:of|in|with|working))?|ability\s+to|"
        r"understanding\s+of|knowledge\s+of|skills?\s+in|track\s+record\s+of)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # First clause only — everything before a comma-plus-conjunction or semicolon
    text = re.split(r";|,\s+(?:and|as well as|including|together with)\s+", text)[0].strip()
    text = text.rstrip(".,;: ")

    if len(text) < 12 or len(text.split()) < 3:
        return None
    if _STOPWORD_ONLY.match(text):
        return None
    return text
