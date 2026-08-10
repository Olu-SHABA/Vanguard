"""Requirement extraction — sections, tools, competencies."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.extract import Requirement, extract, extract_sections

FIXTURE = Path(__file__).parent / "fixtures" / "moj_senior_data_engineer.txt"


@pytest.fixture
def advert() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def reqs(advert: str) -> list[Requirement]:
    return extract(advert)


# --- sections -------------------------------------------------------------

def test_essential_section_detected(advert: str) -> None:
    sections = extract_sections(advert)
    assert "essential" in sections and sections["essential"]


def test_lead_in_line_does_not_discard_bullets(advert: str) -> None:
    """'As a Senior Data Engineer your work might involve:' looks like a
    heading. It must not close the section and lose the bullets beneath it."""
    sections = extract_sections(advert)
    assert len(sections["key responsibilities"]) >= 10


# --- tools ----------------------------------------------------------------

@pytest.mark.parametrize(
    "tool", ["Python", "SQL", "git", "pytest", "CI/CD", "GitHub Actions", "AWS", "ETL"]
)
def test_named_technology_extracted(reqs: list[Requirement], tool: str) -> None:
    assert any(r.canonical == tool for r in reqs)


def test_one_requirement_per_tool_not_per_bullet(reqs: list[Requirement]) -> None:
    """A bullet naming Python and SQL yields two requirements — coverage must
    be able to report which one failed."""
    essential = [r for r in reqs if r.section == "essential" and r.kind == "tool"]
    assert {"Python", "SQL"} <= {r.canonical for r in essential}


def test_no_duplicate_terms(reqs: list[Requirement]) -> None:
    keys = [r.key for r in reqs]
    assert len(keys) == len(set(keys))


def test_substring_matching_is_prohibited() -> None:
    """'git' must not fire on 'digital', 'R' must not fire on every capital R."""
    reqs = extract("Essential\n- experience in a digital government organisation")
    assert not any(r.canonical == "git" for r in reqs)


def test_word_boundary_respected() -> None:
    reqs = extract("Essential\n- strong Python and SQL skills required here")
    assert {"Python", "SQL"} <= {r.canonical for r in reqs}


# --- competencies ---------------------------------------------------------

def test_bullet_without_tool_becomes_competency(reqs: list[Requirement]) -> None:
    comps = [r for r in reqs if r.kind == "competency"]
    assert comps
    assert any("stakeholder" in r.text.lower() for r in comps)


def test_leading_filler_trimmed() -> None:
    reqs = extract("Essential\n- proven experience of building resilient data pipelines")
    comp = [r for r in reqs if r.kind == "competency"]
    if comp:
        assert not comp[0].text.lower().startswith(("proven", "experience"))


def test_very_short_bullets_ignored() -> None:
    assert extract("Essential\n- SC\n- ok\n- yes") == []


# --- shape ----------------------------------------------------------------

def test_requirements_record_their_section(reqs: list[Requirement]) -> None:
    assert all(r.section for r in reqs)


def test_empty_advert_yields_nothing() -> None:
    assert extract("") == []


def test_advert_without_headings_still_yields_tools() -> None:
    """Fallback: an unstructured advert must not score zero."""
    reqs = extract("We need someone strong in Python and Tableau for this role.")
    assert {"Python", "Tableau"} <= {r.canonical for r in reqs}


def test_desirable_can_be_excluded() -> None:
    text = "Essential\n- strong Python development skills\n\nDesirable\n- exposure to Kubernetes clusters"
    assert any(r.canonical == "Kubernetes" for r in extract(text))
    assert not any(r.canonical == "Kubernetes" for r in extract(text, include_desirable=False))


# ---------------------------------------------------------------------------
# B-06 / B-08 — trimming must not discard evidence; behaviours are not skills
# ---------------------------------------------------------------------------

def test_full_source_bullet_is_retained(reqs: list[Requirement]) -> None:
    """Trimming loses clauses that carry alias-matching evidence."""
    comp = [r for r in reqs if r.kind == "competency" and r.source_bullet]
    assert comp
    assert any(len(r.source_bullet) > len(r.text) for r in comp)


def test_match_texts_offers_trimmed_then_full() -> None:
    bullet = "communicating with stakeholders, and translating user needs into technical requirements"
    req = extract(f"Essential\n- {bullet}")[0]
    assert req.match_texts[0] == req.text
    assert bullet in req.match_texts[-1]


@pytest.mark.parametrize(
    "behaviour",
    ["Changing and Improving", "Managing a Quality Service", "Delivering at Pace",
     "Seeing the Big Picture", "Working Together"],
)
def test_named_behaviours_are_not_requirements(behaviour: str) -> None:
    """Behaviours are assessed at interview, not in the sift. Counting them
    inflates |R| and depresses coverage on every Success Profile advert."""
    reqs = extract(f"Essential\n- {behaviour}")
    assert not any(behaviour.lower() in r.text.lower() for r in reqs)


def test_behaviours_excluded_from_moj_advert(reqs: list[Requirement]) -> None:
    terms = " ".join(r.text.lower() for r in reqs)
    assert "changing and improving" not in terms
    assert "managing a quality service" not in terms


def test_behaviour_exclusion_does_not_remove_real_requirements(reqs: list[Requirement]) -> None:
    """'Leadership' is a behaviour name, but real requirements survive."""
    assert any(r.canonical == "Python" for r in reqs)
    assert any(r.canonical == "SQL" for r in reqs)


# ---------------------------------------------------------------------------
# HTML normalisation — a <li> list is a requirements list
# ---------------------------------------------------------------------------

def test_html_list_becomes_bullets() -> None:
    """Reed returns raw HTML. The bullet pattern matches line starts, and a
    single string of markup has none — so `<ul><li>` lists were invisible."""
    from vanguard.extract import html_to_text

    out = html_to_text("<ul><li>Python and SQL</li><li>AWS and Docker</li></ul>")
    assert out.count("\n- ") >= 2 or out.startswith("- ")


def test_requirements_extracted_from_html() -> None:
    html = ("<p><b>What you will need</b></p><ul>"
            "<li>Strong Python programming skills</li>"
            "<li>Experience with PyTorch or TensorFlow</li>"
            "<li>Familiarity with SQL and data pipelines</li>"
            "<li>Understanding of MLOps and model deployment</li>"
            "<li>Experience with AWS or Azure</li></ul>")
    found = {r.canonical for r in extract(html)}
    assert {"Python", "SQL", "PyTorch", "TensorFlow", "AWS", "Azure"} <= found


def test_entities_are_decoded() -> None:
    from vanguard.extract import html_to_text

    out = html_to_text("<p>R&amp;D team &ndash; &pound;50,000</p>")
    assert "&amp;" not in out and "R&D" in out and "£" in out


def test_script_and_style_removed() -> None:
    from vanguard.extract import html_to_text

    out = html_to_text("<p>Real text</p><script>var x = 'Python';</script>")
    assert "Real text" in out and "var x" not in out


def test_plain_text_is_untouched() -> None:
    from vanguard.extract import html_to_text, looks_like_html

    plain = "Essential\n- strong Python and SQL skills"
    assert not looks_like_html(plain)
    assert extract(plain)


# ---------------------------------------------------------------------------
# Closing date — a closed vacancy costs a hydration slot
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("<p><b>Closing Date</b></p> 9 July 2026", (2026, 7, 9)),
        ("Closing date: 30 September 2026", (2026, 9, 30)),
        ("Applications close 01/09/2026", (2026, 9, 1)),
        ("Apply by July 9, 2026", (2026, 7, 9)),
        ("Deadline: 2026-12-01", (2026, 12, 1)),
    ],
)
def test_closing_date_formats(text: str, expected: tuple) -> None:
    from datetime import date

    from vanguard.extract import closing_date

    assert closing_date(text) == date(*expected)


@pytest.mark.parametrize(
    "text", ["No date stated anywhere", "Closing date: sometime soon", ""]
)
def test_absent_or_unparseable_date_is_none(text: str) -> None:
    """Never guessed. An invented date could discard an open vacancy."""
    from vanguard.extract import closing_date, is_closed

    assert closing_date(text) is None
    assert not is_closed(text)


def test_expired_vacancy_detected() -> None:
    from datetime import date

    from vanguard.extract import is_closed

    assert is_closed("Closing Date 9 July 2026", today=date(2026, 8, 9))
    assert not is_closed("Closing Date 9 July 2026", today=date(2026, 6, 1))


def test_closing_today_is_still_open() -> None:
    from datetime import date

    from vanguard.extract import is_closed

    assert not is_closed("Closing date: 9 August 2026", today=date(2026, 8, 9))


def test_single_tool_bullet_is_not_dropped() -> None:
    """The length floor exists to skip fragments. A bullet reading just "AWS"
    is a legitimate requirement — three characters and unambiguous."""
    advert = ("<strong>What you will have</strong>"
              "<ul><li>AWS</li><li>SQL</li><li>ETL</li></ul>")
    assert {r.canonical for r in extract(advert)} == {"AWS", "SQL", "ETL"}


def test_short_fragment_without_a_tool_is_still_skipped() -> None:
    advert = ("<strong>What you will have</strong>"
              "<ul><li>Python and SQL</li><li>x</li><li>-</li></ul>")
    terms = {(r.canonical or r.text) for r in extract(advert)}
    assert "x" not in terms and "-" not in terms
