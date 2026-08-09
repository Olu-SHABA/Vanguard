"""Advert structure parsing — heading binding and section classification."""
from __future__ import annotations

import pytest

from vanguard.extract import extract
from vanguard.structure import SectionKind, classify_heading, parse_advert

# Real Reed markup: headings are inline <strong> followed by <br /><br />,
# not <h3> or <p>. Duties, requirements and benefits all use <ul><li>.
REED = """We have an opportunity for a <strong>Group Finance Manager</strong>.<br /><br />
<strong>What you will do </strong><br /><br />
<ul><li>Lead the preparation and delivery of financial information.</li>
<li>Oversee key areas of the month-end close processes.</li>
<li>Manage delivery of the Group year-end process.</li></ul>
<strong>What you will have</strong><br /><br />
<ul><li>Qualified accountant with strong Excel and SQL skills</li>
<li>Experience with Python for reporting automation</li></ul>
<strong>What we offer</strong><br /><br />
<ul><li>25 days holiday</li><li>Pension and private healthcare</li></ul>"""


@pytest.fixture
def structure():
    return parse_advert(REED)


# --- the defect this module exists for ------------------------------------

def test_duties_are_not_requirements(structure) -> None:
    """"Lead the preparation of financial statements" describes the job, not a
    qualification. Counting duties as requirements drove |R| to 38 and
    coverage to 0.026 with a ceiling of 1.000."""
    bullets = " ".join(structure.requirement_bullets).lower()
    assert "month-end" not in bullets
    assert "year-end process" not in bullets


def test_benefits_are_not_requirements(structure) -> None:
    bullets = " ".join(structure.requirement_bullets).lower()
    assert "holiday" not in bullets and "pension" not in bullets


def test_only_requirement_bullets_survive(structure) -> None:
    assert len(structure.requirement_bullets) == 2
    joined = " ".join(structure.requirement_bullets)
    assert "Excel and SQL" in joined and "Python" in joined


def test_extraction_ignores_duty_lists() -> None:
    found = {r.canonical for r in extract(REED)}
    assert {"SQL", "Excel", "Python"} <= found


# --- heading binding ------------------------------------------------------

def test_inline_strong_is_recognised_as_a_heading(structure) -> None:
    """Reed uses <strong>, not <h3>. Flattening lost the binding entirely."""
    headings = {b.heading for b in structure.blocks}
    assert "What you will do" in headings
    assert "What you will have" in headings


def test_each_list_binds_to_the_heading_above_it(structure) -> None:
    duties = structure.of_kind(SectionKind.RESPONSIBILITY)
    requirements = structure.of_kind(SectionKind.REQUIREMENT)
    benefits = structure.of_kind(SectionKind.BENEFIT)
    assert len(duties[0].bullets) == 3
    assert len(requirements[0].bullets) == 2
    assert len(benefits[0].bullets) == 2


def test_long_inline_strong_is_emphasis_not_a_heading() -> None:
    long = "<p>We need <strong>" + "a very long emphasised run " * 5 + "</strong></p>"
    assert not any(b.kind is not SectionKind.UNKNOWN for b in parse_advert(long).blocks)


# --- classification -------------------------------------------------------

@pytest.mark.parametrize(
    "heading, kind",
    [
        ("What you will have", SectionKind.REQUIREMENT),
        ("About you", SectionKind.REQUIREMENT),
        ("Person Specification", SectionKind.REQUIREMENT),
        ("Essential Criteria", SectionKind.REQUIREMENT),
        ("The ideal candidate", SectionKind.REQUIREMENT),
        ("What you will do", SectionKind.RESPONSIBILITY),
        ("Key Responsibilities", SectionKind.RESPONSIBILITY),
        ("The Role", SectionKind.RESPONSIBILITY),
        ("What we offer", SectionKind.BENEFIT),
        ("Benefits", SectionKind.BENEFIT),
        ("How to apply", SectionKind.PROCESS),
        ("Closing date", SectionKind.PROCESS),
        ("About us", SectionKind.COMPANY),
        ("Widgets and sprockets", SectionKind.UNKNOWN),
        ("", SectionKind.UNKNOWN),
    ],
)
def test_heading_classification(heading: str, kind: SectionKind) -> None:
    assert classify_heading(heading) is kind


def test_narrow_phrases_beat_broad_ones() -> None:
    """"what you will do" must not be caught by a requirement rule."""
    assert classify_heading("What you will do") is SectionKind.RESPONSIBILITY
    assert classify_heading("What you will have") is SectionKind.REQUIREMENT


def test_unknown_sections_do_not_carry_requirements() -> None:
    assert not SectionKind.UNKNOWN.carries_requirements
    assert not SectionKind.RESPONSIBILITY.carries_requirements
    assert SectionKind.REQUIREMENT.carries_requirements


# --- robustness -----------------------------------------------------------

def test_html_prose_without_a_requirement_section_refuses() -> None:
    """Superseded 9 Aug 2026. This previously asserted a flat-text fallback.

    The fallback counted duties and benefits as requirements, so an advert
    with no recognised requirement heading produced a confident-looking wrong
    number. It now returns nothing and the vacancy is reported UNRELIABLE.
    """
    prose = "<p>We need a Python developer with SQL experience for this role.</p>"
    assert extract(prose) == []


def test_malformed_markup_does_not_lose_the_advert() -> None:
    broken = "<p><strong>What you will have<ul><li>Python skills</li>"
    assert parse_advert(broken).plain_text


def test_empty_input() -> None:
    result = parse_advert("")
    assert result.blocks == [] and result.plain_text == ""


def test_plain_text_input_is_handled() -> None:
    result = parse_advert("Essential\n- Python and SQL")
    assert result.plain_text


def test_entities_decoded_in_headings() -> None:
    result = parse_advert("<strong>R&amp;D requirements</strong><ul><li>Python</li></ul>")
    assert any("R&D" in b.heading for b in result.blocks)


def test_script_content_excluded() -> None:
    result = parse_advert("<p>Real</p><script>var x='Python';</script>")
    assert "var x" not in result.plain_text


# ---------------------------------------------------------------------------
# No flat fallback for HTML — a refusal beats a plausible wrong number
# ---------------------------------------------------------------------------

def test_unrecognised_heading_yields_nothing() -> None:
    """Falling back to flat extraction counted duties, benefits and
    application steps as requirements: |R| reached 38 with ceiling 1.000, the
    system asserting an AI Marketing role was fully attainable."""
    advert = ("<strong>Our Ideal Teammate Vibe</strong><br /><br />"
              "<ul><li>25 days holiday</li><li>Free parking</li>"
              "<li>Deliver quarterly reports</li></ul>")
    assert extract(advert) == []


def test_benefits_only_advert_yields_nothing() -> None:
    advert = ("<strong>What we offer</strong><br /><br />"
              "<ul><li>Competitive salary</li><li>Private healthcare</li></ul>")
    assert extract(advert) == []


def test_duties_only_advert_yields_nothing() -> None:
    """A duty list is not a requirements list, however long it is."""
    advert = ("<strong>What you will do</strong><br /><br /><ul>"
              + "".join(f"<li>Deliver workstream {i} to schedule</li>" for i in range(12))
              + "</ul>")
    assert extract(advert) == []


def test_recognised_heading_still_extracts() -> None:
    advert = ("<strong>What you will have</strong><br /><br /><ul>"
              "<li>Python and SQL</li><li>AWS experience</li>"
              "<li>ETL pipelines</li></ul>")
    assert {r.canonical for r in extract(advert)} >= {"Python", "SQL", "AWS", "ETL"}


def test_plain_text_still_uses_flat_extraction() -> None:
    """The refusal applies to MARKUP only. Plain-text adverts, including
    pasted ones, keep the section-heading path."""
    assert {r.canonical for r in extract("Essential\n- strong Python and SQL skills")} \
        >= {"Python", "SQL"}


def test_refusal_reports_unreliable_not_zero_coverage() -> None:
    """C=0.000 would read as 'no match'. UNRELIABLE reads as 'not measured'."""
    from vanguard.coverage import compute_coverage, load_aliases
    from vanguard.cv import load as load_cv

    root = __import__("pathlib").Path(__file__).parent.parent
    report = compute_coverage(
        extract("<strong>Vibe</strong><ul><li>Free parking</li></ul>"),
        load_cv(root / "data" / "canonical_cv.md"),
        load_aliases(root / "config" / "alias_table.yaml"),
    )
    assert report.unreliable
    assert "no requirement terms" in report.unreliable_reason


# ---------------------------------------------------------------------------
# Heading detector — tightened from live diagnostics, 9 Aug 2026
#
# The first diagnose run showed the detector firing on job titles, field
# labels, recruiter names, contract terms and bare punctuation. A false
# heading opens a new block, orphaning the content that belonged to the real
# one — which is how `empty_requirement_section` refusals arose.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [",", "*", "-", "Location:", "Daily Rate:", "Databases:",
     "3-month initial contract", "6 month initial",
     "Alexander Booth - Talent Acquisition Specialist",
     "PLEASE NOTE YOU MUST BE BASED IN THE UK AND HAVE FULL RIGHT TO WORK",
     "Sanderson", "Widgets"],
)
def test_observed_false_headings_are_rejected(text: str) -> None:
    from vanguard.structure import is_probable_heading

    assert not is_probable_heading(text)


@pytest.mark.parametrize(
    "text",
    ["What you will have", "Person Specification", "About you",
     "What you'll work on", "Why consider it?", "Apply Now"],
)
def test_real_headings_survive(text: str) -> None:
    from vanguard.structure import is_probable_heading

    assert is_probable_heading(text)


@pytest.mark.parametrize("text", ["Essential", "Requirements", "Benefits",
                                  "Responsibilities", "Qualifications"])
def test_known_single_word_headings_survive(text: str) -> None:
    """A single word is usually a label — but not when it names a section."""
    from vanguard.structure import is_probable_heading

    assert is_probable_heading(text)


def test_repeated_job_title_is_not_a_heading() -> None:
    """Reed adverts restate the role in bold before the body."""
    from vanguard.structure import is_probable_heading

    assert not is_probable_heading("Machine Learning Engineer",
                                   job_title="Machine Learning Engineer")
    assert is_probable_heading("Machine Learning Engineer",
                               job_title="Data Scientist")


def test_noise_headings_do_not_orphan_requirements() -> None:
    """The end-to-end effect: bullets stay bound to the real heading."""
    advert = ("<strong>Machine Learning Engineer</strong><br />"
              "<strong>Location:</strong> London<br />"
              "<strong>What you will have</strong><br /><br />"
              "<ul><li>Python and SQL</li><li>PyTorch</li><li>AWS</li></ul>"
              "<strong>,</strong>")
    parsed = parse_advert(advert, job_title="Machine Learning Engineer")
    assert [b.heading for b in parsed.blocks if b.heading] == ["What you will have"]
    assert len(parsed.requirement_bullets) == 3
