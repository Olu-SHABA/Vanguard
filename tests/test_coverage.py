"""Coverage engine — three-stage resolution, Tier C enforcement, ceiling."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.coverage import (
    Outcome,
    compute_coverage,
    load_aliases,
    resolve_term,
)
from vanguard.cv import load
from vanguard.extract import Requirement, extract
from vanguard.rank import LexicalEmbedder

ROOT = Path(__file__).parent.parent
ADVERT = Path(__file__).parent / "fixtures" / "moj_senior_data_engineer.txt"


@pytest.fixture
def cv():
    return load(ROOT / "data" / "canonical_cv.md")


@pytest.fixture
def aliases():
    return load_aliases(ROOT / "config" / "alias_table.yaml")


def req(text: str, canonical: str | None = None) -> Requirement:
    kind = "tool" if canonical else "competency"
    return Requirement(text, kind, "essential", True, canonical=canonical)


# --- THE critical behaviour ----------------------------------------------

@pytest.mark.parametrize(
    "term, expected_entry",
    [
        ("pytest", "EXCLUDED_unit_testing"),
        ("AWS", "EXCLUDED_cloud_platforms"),
        ("Spark", "EXCLUDED_distributed_compute"),
        ("git", "EXCLUDED_version_control"),
        ("CI/CD", "EXCLUDED_cicd"),
        ("line management", "EXCLUDED_line_management"),
    ],
)
def test_tier_c_returns_gap_with_reason(cv, aliases, term, expected_entry) -> None:
    r = resolve_term(req(term, term), cv, aliases)
    assert r.outcome is Outcome.GAP
    assert r.alias_canonical == expected_entry
    assert r.exclusion_reason


def test_tier_c_does_not_fall_through_to_embedding(cv, aliases) -> None:
    """The failure mode the gate exists to prevent: an embedding rescuing an
    excluded term and converting a Type 3 gap into a false HIT."""

    class AlwaysMatches:
        def similarity(self, a: str, b: str) -> float:
            return 1.0

    r = resolve_term(req("pytest", "pytest"), cv, aliases, AlwaysMatches())
    assert r.outcome is Outcome.GAP
    assert r.stage == 2, "Tier C must terminate before stage 3"


def test_tier_c_blocks_even_when_term_appears_in_cv(cv, aliases) -> None:
    """'cloud computing' sits in the CV's catch-all line. It must not satisfy AWS."""
    assert "cloud computing" in cv.full_text().lower()
    assert resolve_term(req("AWS", "AWS"), cv, aliases).outcome is Outcome.GAP


def test_moj_advert_reproduces_manual_assessment(cv, aliases) -> None:
    """Python/SQL and data wrangling resolve; the SDLC criterion does not."""
    reqs = extract(ADVERT.read_text(encoding="utf-8"))
    report = compute_coverage(reqs, cv, aliases)
    hit = {r.requirement.canonical for r in report.hits}
    blocked = {r.requirement.canonical for r in report.excluded_gaps}

    assert {"Python", "SQL", "data wrangling"} <= hit
    assert {"pytest", "git", "CI/CD", "GitHub Actions"} <= blocked


# --- stage ordering -------------------------------------------------------

def test_stage_1_exact_match(cv, aliases) -> None:
    r = resolve_term(req("Python", "Python"), cv, aliases)
    assert r.outcome is Outcome.HIT and r.stage == 1 and r.evidence


def test_stage_2_alias_carries_evidence_and_role(cv, aliases) -> None:
    r = resolve_term(req("supplier management", "supplier management"), cv, aliases)
    assert r.outcome is Outcome.HIT and r.stage == 2
    assert r.cv_evidence if hasattr(r, "cv_evidence") else r.evidence
    assert r.source_role


def test_stage_3_soft_hit_is_flagged(cv, aliases) -> None:
    class HighScore:
        def similarity(self, a: str, b: str) -> float:
            return 0.91

    r = resolve_term(req("orchestrating unattended batch workflows"), cv, aliases, HighScore())
    assert r.outcome is Outcome.SOFT_HIT
    assert r.stage == 3 and r.score is not None


def test_below_threshold_is_gap_not_soft_hit(cv, aliases) -> None:
    class LowScore:
        def similarity(self, a: str, b: str) -> float:
            return 0.40

    r = resolve_term(req("underwater basket weaving at scale"), cv, aliases, LowScore())
    assert r.outcome is Outcome.GAP and r.stage == 3


def test_no_embedder_yields_gap_not_crash(cv, aliases) -> None:
    r = resolve_term(req("something entirely unrelated to this cv"), cv, aliases, None)
    assert r.outcome is Outcome.GAP and r.stage == 0


def test_lemma_variants_match(cv, aliases) -> None:
    assert resolve_term(req("dashboard", "dashboard"), cv, aliases).outcome is Outcome.HIT


# --- arithmetic -----------------------------------------------------------

def test_no_requirement_is_dropped(cv, aliases) -> None:
    reqs = extract(ADVERT.read_text(encoding="utf-8"))
    assert compute_coverage(reqs, cv, aliases).total == len(reqs)


def test_coverage_is_matched_over_total(cv, aliases) -> None:
    reqs = extract(ADVERT.read_text(encoding="utf-8"))
    rep = compute_coverage(reqs, cv, aliases, LexicalEmbedder())
    assert rep.coverage == pytest.approx(rep.matched / rep.total)


def test_ceiling_excludes_tier_c_gaps(cv, aliases) -> None:
    """Directive §3: exit UNREACHABLE rather than burning refactor passes."""
    reqs = extract(ADVERT.read_text(encoding="utf-8"))
    rep = compute_coverage(reqs, cv, aliases)
    assert rep.ceiling < 1.0
    assert rep.ceiling == pytest.approx((rep.total - len(rep.excluded_gaps)) / rep.total)
    assert not rep.reachable


def test_empty_requirements_do_not_divide_by_zero(cv, aliases) -> None:
    rep = compute_coverage([], cv, aliases)
    assert rep.coverage == 0.0 and rep.ceiling == 0.0


# --- alias table integrity ------------------------------------------------

def test_every_tier_ab_entry_has_evidence(aliases) -> None:
    for e in aliases.entries:
        if e.tier in ("A", "B"):
            assert e.cv_evidence, f"{e.canonical} is Tier {e.tier} with no cv_evidence"


def test_tier_ab_without_evidence_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\naliases:\n  - canonical: x\n    tier: A\n    aliases: ['x']\n")
    with pytest.raises(ValueError, match="false HIT"):
        load_aliases(bad)


def test_no_duplicate_alias_terms(aliases) -> None:
    terms = [a.lower() for e in aliases.entries for a in e.aliases]
    assert len(terms) == len(set(terms))


# ---------------------------------------------------------------------------
# B-07 — resolution must try the full advert bullet, not only the trimmed phrase
# ---------------------------------------------------------------------------

def test_trimmed_phrase_falls_back_to_full_bullet(cv, aliases) -> None:
    """Discovered on the first real MiniLM run: a term that should resolve
    deterministically at stage 2 was reaching stage 3 and failing at 0.513."""
    bullet = "communicating with stakeholders, and translating user needs into technical requirements"
    req = extract(f"Essential\n- {bullet}")[0]

    resolution = resolve_term(req, cv, aliases)
    assert resolution.outcome is Outcome.HIT
    assert resolution.stage == 2
    assert resolution.alias_canonical == "stakeholder communication"


def test_exclusion_cannot_be_evaded_by_trimming(cv, aliases) -> None:
    """A Tier C term appearing only in the trailing clause must still block."""
    bullet = "strong delivery focus, and hands-on experience with Spark clusters"
    req = extract(f"Essential\n- {bullet}")[0]

    resolution = resolve_term(req, cv, aliases)
    assert resolution.outcome is Outcome.GAP
    assert resolution.exclusion_reason


def test_moj_coverage_improves_after_b06_b07_b08(cv, aliases) -> None:
    """Regression guard on the measured improvement: 0.304 -> 0.381."""
    report = compute_coverage(extract(ADVERT.read_text(encoding="utf-8")),
                              cv, aliases, LexicalEmbedder())
    assert report.total == 21, "behaviours must not count as requirements"
    assert report.coverage > 0.35
