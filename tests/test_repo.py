"""Repository evidence — proposing Type 1 bullets from work actually done."""
from __future__ import annotations

from pathlib import Path

import pytest

from vanguard.repo import (
    SIGNALS,
    Evidence,
    RepositoryScan,
    propose_bullets,
    scan_repository,
)

ROOT = Path(__file__).parent.parent


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with a test suite and documentation, and nothing else."""
    directory = tmp_path / "project"
    (directory / "tests").mkdir(parents=True)
    (directory / "docs").mkdir()
    for i in range(8):
        (directory / "tests" / f"test_{i}.py").write_text("def test(): pass\n")
    for i in range(6):
        (directory / "docs" / f"guide{i}.md").write_text("# Guide\n")
    (directory / "main.py").write_text("print('hello')\n")
    return directory


# --- the binding constraint -----------------------------------------------

def test_a_repository_evidences_only_what_was_built(repo: Path) -> None:
    """The whole point. AWS is not evidenced by a repository that never
    touched AWS, however thoroughly it is mined."""
    scan = scan_repository(repo)
    found = {e.competency for e in scan.sufficient_evidence}

    assert "automated testing" in found
    assert "technical documentation" in found
    assert "containerisation" not in found
    assert "infrastructure as code" not in found
    assert "orchestration" not in found


def test_absent_competencies_yield_no_proposals(repo: Path) -> None:
    scan = scan_repository(repo)
    proposals = propose_bullets([scan], ["AWS", "Azure", "Terraform",
                                         "Kubernetes", "Docker"])
    assert proposals == []


def test_present_competencies_do_yield_proposals(repo: Path) -> None:
    scan = scan_repository(repo)
    proposals = propose_bullets([scan], ["pytest", "documentation"])
    assert {p.requirement for p in proposals} == {"pytest", "documentation"}


# --- what counts as evidence ----------------------------------------------

def test_a_single_incidental_file_is_not_experience(tmp_path: Path) -> None:
    """One Dockerfile in a repository of Python is a detail. Twenty test
    files are a test suite."""
    directory = tmp_path / "p"
    (directory / "tests").mkdir(parents=True)
    (directory / "tests" / "test_one.py").write_text("def test(): pass\n")

    scan = scan_repository(directory)
    testing = next(e for e in scan.evidence if e.competency == "automated testing")
    assert testing.count == 1
    assert not testing.sufficient


def test_dependency_trees_are_not_the_operators_work(tmp_path: Path) -> None:
    """Counting site-packages would evidence competencies nobody
    demonstrated."""
    directory = tmp_path / "p"
    for excluded in (".venv/lib/site-packages/pkg", "node_modules/thing"):
        (directory / excluded).mkdir(parents=True)
        for i in range(20):
            (directory / excluded / f"test_{i}.py").write_text("x\n")

    assert scan_repository(directory).sufficient_evidence == []


def test_git_internals_are_skipped(tmp_path: Path) -> None:
    directory = tmp_path / "p"
    (directory / ".git" / "hooks").mkdir(parents=True)
    (directory / ".git" / "hooks" / "test_x.py").write_text("x\n")
    assert scan_repository(directory).sufficient_evidence == []


@pytest.mark.parametrize(
    "filename, competency",
    [
        ("Dockerfile", "containerisation"),
        ("main.tf", "infrastructure as code"),
        ("schema.sql", "SQL and schema design"),
        (".github/workflows/ci.yml", "CI/CD"),
    ],
)
def test_artefacts_are_recognised(tmp_path: Path, filename: str,
                                  competency: str) -> None:
    directory = tmp_path / "p"
    target = directory / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n")

    found = {e.competency for e in scan_repository(directory).sufficient_evidence}
    assert competency in found


# --- proposals are proposals ----------------------------------------------

def test_a_proposal_cites_its_evidence(repo: Path) -> None:
    """An edit without a citation is exactly what the truthfulness rule
    forbids."""
    proposal = propose_bullets([scan_repository(repo)], ["pytest"])[0]
    assert "file(s)" in proposal.citation()
    assert proposal.repository in proposal.citation()


def test_the_draft_bullet_carries_no_invented_quantity(repo: Path) -> None:
    """A file count is not an achievement. The operator rewrites this in
    their own terms."""
    proposal = propose_bullets([scan_repository(repo)], ["pytest"])[0]
    assert "%" not in proposal.bullet
    assert not any(char.isdigit() for char in proposal.bullet)


def test_proposals_are_ordered_by_weight_of_evidence(repo: Path) -> None:
    proposals = propose_bullets([scan_repository(repo)],
                                ["pytest", "documentation"])
    counts = [p.evidence.count for p in proposals]
    assert counts == sorted(counts, reverse=True)


def test_one_proposal_per_competency_per_repository(repo: Path) -> None:
    """Several advert terms may map to one competency. That is one proposal,
    not several."""
    proposals = propose_bullets([scan_repository(repo)],
                                ["pytest", "unit testing", "test coverage"])
    assert len(proposals) == 1


# --- robustness -----------------------------------------------------------

def test_an_absent_repository_yields_an_empty_scan(tmp_path: Path) -> None:
    """An unreadable repository must not stop a batch."""
    scan = scan_repository(tmp_path / "nothere")
    assert scan.evidence == [] and scan.commits == 0


def test_a_repository_without_git_still_scans(repo: Path) -> None:
    scan = scan_repository(repo)
    assert not scan.is_git
    assert scan.sufficient_evidence


def test_relative_paths_get_a_usable_name(tmp_path: Path) -> None:
    """`.` has no useful name, and an unnamed repository cannot be cited."""
    import os

    directory = tmp_path / "myproject"
    directory.mkdir()
    previous = os.getcwd()
    try:
        os.chdir(directory)
        assert scan_repository(".").name == "myproject"
    finally:
        os.chdir(previous)


def test_every_signal_names_what_it_answers() -> None:
    """A signal that answers nothing can never produce a proposal."""
    for signal in SIGNALS:
        assert signal.answers, f"{signal.competency} answers no advert term"
        assert signal.patterns
