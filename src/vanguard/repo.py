"""
Repository evidence — Route 3, gap remediation.

A repository is evidence in a way a CV bullet is not: timestamped, sequenced,
and hard to fabricate after the fact. This reads the operator's own
repositories and proposes CV bullets for work that was genuinely done and is
simply unstated.

## The binding constraint

**A repository evidences only what was built.**

It can supply a **Type 1** gap — something genuinely done but absent from the
CV's wording. It cannot supply a **Type 3** gap: AWS is not evidenced by a
repository that never touched AWS, however thoroughly it is mined.

So the loop recovers unstated claims, never absent ones. A vacancy at 0.20
demanding cloud platforms stays at 0.20.

## Own repositories only

The broad version — scoring any applicant's public repository — carries a
coverage bias recorded under D-04. Public repositories favour open-source
contributors and permissive employers; most enterprise work sits behind a
firewall, and a twenty-year network engineer has no public footprint and is
not less qualified for it.

Here attribution is certain: the operator's machine, the operator's
repository.

## What counts as evidence

Not commit counts. A thousand commits may be careful iteration or committing
every save, and frequency is not competence.

What counts is **artefacts**: a test suite evidences testing, a Dockerfile
evidences containerisation, a CI workflow evidences CI. Each is a thing that
had to be built and made to work.

## The operator decides

Every proposal is exactly that. The scanner reports what it found and how
much; whether that is enough to claim is a judgement about one's own history,
and the system does not make it.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "Evidence",
    "RepositoryScan",
    "Signal",
    "SIGNALS",
    "scan_repository",
    "propose_bullets",
]


@dataclass(frozen=True)
class Signal:
    """One competency, and what in a repository would evidence it.

    `minimum` guards against a single incidental file being read as
    experience. One Dockerfile in a repository of two hundred Python files is
    a detail; twenty test files are a test suite.
    """

    competency: str
    patterns: tuple[str, ...]
    minimum: int = 1
    describes: str = ""
    #: Terms in a job advert this competency would answer.
    answers: tuple[str, ...] = ()


#: What the scanner looks for. Deliberately narrow — each entry is an artefact
#: that had to be built and made to work, not a mention in a file.
SIGNALS: tuple[Signal, ...] = (
    Signal(
        "automated testing",
        ("test_*.py", "*_test.py", "tests/**/*.py", "spec/**/*.rb"),
        minimum=5,
        describes="a test suite",
        answers=("pytest", "unit testing", "test coverage", "automated testing",
                 "TDD", "test suite"),
    ),
    Signal(
        "containerisation",
        ("Dockerfile", "docker-compose.yml", "docker-compose.yaml",
         "*.dockerfile"),
        describes="container definitions",
        answers=("Docker", "containers", "containerisation", "containerization"),
    ),
    Signal(
        "CI/CD",
        (".github/workflows/*.yml", ".github/workflows/*.yaml",
         ".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml"),
        describes="continuous integration pipelines",
        answers=("CI/CD", "continuous integration", "continuous deployment",
                 "GitHub Actions", "Jenkins", "build pipeline"),
    ),
    Signal(
        "infrastructure as code",
        ("*.tf", "*.tfvars", "ansible/**/*.yml", "playbook*.yml"),
        describes="infrastructure definitions",
        answers=("Terraform", "infrastructure as code", "Ansible", "IaC"),
    ),
    Signal(
        "orchestration",
        ("k8s/**/*.yaml", "kubernetes/**/*.yaml", "helm/**/*.yaml",
         "Chart.yaml"),
        describes="orchestration manifests",
        answers=("Kubernetes", "k8s", "Helm", "orchestration"),
    ),
    Signal(
        "SQL and schema design",
        ("*.sql", "migrations/**/*.py", "alembic/**/*.py"),
        describes="schema and migration definitions",
        answers=("SQL", "database design", "schema", "migrations", "RDBMS"),
    ),
    Signal(
        "API development",
        ("**/routes*.py", "**/api/*.py", "**/views.py", "openapi.yaml",
         "swagger.yaml"),
        minimum=2,
        describes="API definitions",
        answers=("REST", "API", "FastAPI", "Flask", "endpoints"),
    ),
    Signal(
        "data pipelines",
        ("**/etl*.py", "**/pipeline*.py", "**/ingest*.py", "dags/**/*.py"),
        minimum=2,
        describes="pipeline code",
        answers=("ETL", "ELT", "data pipelines", "Airflow", "batch processing"),
    ),
    Signal(
        "notebooks and analysis",
        ("*.ipynb", "notebooks/**/*.ipynb"),
        minimum=2,
        describes="analysis notebooks",
        answers=("Jupyter", "notebooks", "exploratory analysis", "EDA"),
    ),
    Signal(
        "technical documentation",
        ("*.md", "docs/**/*.md", "*.rst"),
        minimum=5,
        describes="written documentation",
        answers=("documentation", "technical writing", "runbooks", "SOPs"),
    ),
    Signal(
        "type annotation",
        ("py.typed", "mypy.ini", ".mypy.ini"),
        describes="type checking configuration",
        answers=("type hints", "mypy", "static typing", "type annotations"),
    ),
)

#: Directories never scanned. Dependency trees are not the operator's work,
#: and counting them would evidence competencies nobody demonstrated.
_EXCLUDED = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".tox", ".pytest_cache", ".mypy_cache", "site-packages", "dist",
    "build", ".eggs", "vendor", "third_party",
})


@dataclass
class Evidence:
    """One competency found in a repository, and what supports it."""

    competency: str
    signal: Signal
    files: list[str] = field(default_factory=list)
    lines: int = 0

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def sufficient(self) -> bool:
        """Enough to be worth proposing. Not enough to claim — that is the
        operator's judgement."""
        return self.count >= self.signal.minimum

    def describe(self) -> str:
        what = self.signal.describes or self.competency
        return f"{self.count} file(s) of {what}"


@dataclass
class RepositoryScan:
    """What one repository contains, and when it was worked on."""

    path: Path
    name: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    commits: int = 0
    first_commit: str = ""
    last_commit: str = ""
    languages: dict[str, int] = field(default_factory=dict)
    is_git: bool = False

    @property
    def sufficient_evidence(self) -> list[Evidence]:
        return [e for e in self.evidence if e.sufficient]

    @property
    def span(self) -> str:
        """How long the work ran. Sustained work is a stronger signal than a
        weekend, and the dates are in the history rather than asserted."""
        if not (self.first_commit and self.last_commit):
            return ""
        return f"{self.first_commit[:7]} to {self.last_commit[:7]}"

    def summary(self) -> str:
        found = len(self.sufficient_evidence)
        if not self.is_git:
            return f"{self.name}: {found} competenc(ies), no git history"
        return (f"{self.name}: {found} competenc(ies), {self.commits} commits"
                + (f", {self.span}" if self.span else ""))


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _walk(root: Path) -> Iterable[Path]:
    """Every file, skipping dependency trees and version control internals."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _EXCLUDED for part in path.parts):
            continue
        yield path


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=20, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def scan_repository(path: Path | str, *, name: str = "") -> RepositoryScan:
    """Read one repository. Never raises — an unreadable repository yields an
    empty scan rather than stopping a batch."""
    # `.` and `..` have no useful `.name`, so resolve before taking it.
    root = Path(path).resolve()
    scan = RepositoryScan(path=root, name=name or root.name or "repository")

    if not root.is_dir():
        return scan

    files = list(_walk(root))
    relative = [str(p.relative_to(root)).replace("\\", "/") for p in files]

    for signal in SIGNALS:
        matched = sorted({
            rel for rel in relative
            for pattern in signal.patterns
            if _matches_pattern(rel, pattern)
        })
        if matched:
            scan.evidence.append(Evidence(
                competency=signal.competency, signal=signal, files=matched))

    for path_object in files:
        suffix = path_object.suffix.lower()
        if suffix:
            scan.languages[suffix] = scan.languages.get(suffix, 0) + 1

    if (root / ".git").exists():
        scan.is_git = True
        count = _git(root, "rev-list", "--count", "HEAD")
        scan.commits = int(count) if count.isdigit() else 0
        scan.first_commit = _git(root, "log", "--reverse", "--format=%ad",
                                 "--date=short", "-1")
        scan.last_commit = _git(root, "log", "--format=%ad", "--date=short", "-1")

    return scan


def _matches_pattern(relative_path: str, pattern: str) -> bool:
    """Glob match, `**` spanning directories."""
    if "**" in pattern:
        regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(
            r"\*", "[^/]*").replace(r"\?", ".")
        return re.fullmatch(regex, relative_path) is not None
    if "/" in pattern:
        return Path(relative_path).match(pattern)
    return Path(relative_path).name == pattern or Path(
        relative_path).match(pattern)


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

@dataclass
class Proposal:
    """A CV bullet the operator might add, and what supports it.

    A proposal, not a decision. The scanner can see that a test suite exists;
    it cannot know whether the operator wrote it, or whether they could defend
    it under questioning. Both are why confirmation is required.
    """

    requirement: str
    competency: str
    evidence: Evidence
    repository: str
    bullet: str
    span: str = ""

    def citation(self) -> str:
        base = f"{self.repository}: {self.evidence.describe()}"
        return f"{base}, {self.span}" if self.span else base


def propose_bullets(scans: Sequence[RepositoryScan],
                    unmet_terms: Sequence[str]) -> list[Proposal]:
    """Match unmet requirements against repository evidence.

    Returns proposals, ordered by how much evidence supports each. Nothing is
    written: every proposal needs operator confirmation, because only the
    operator knows whether they built the thing and could defend it.
    """
    normalised = {term.lower().strip(): term for term in unmet_terms}
    proposals: list[Proposal] = []

    for scan in scans:
        for evidence in scan.sufficient_evidence:
            for answer in evidence.signal.answers:
                match = _find_term(answer, normalised)
                if match is None:
                    continue
                proposals.append(Proposal(
                    requirement=match,
                    competency=evidence.competency,
                    evidence=evidence,
                    repository=scan.name,
                    bullet=_draft_bullet(evidence, scan),
                    span=scan.span,
                ))
                break      # one proposal per competency per repository

    proposals.sort(key=lambda p: p.evidence.count, reverse=True)
    return proposals


def _find_term(answer: str, unmet: dict[str, str]) -> str | None:
    low = answer.lower()
    if low in unmet:
        return unmet[low]
    for term_low, original in unmet.items():
        if low in term_low or term_low in low:
            return original
    return None


def _draft_bullet(evidence: Evidence, scan: RepositoryScan) -> str:
    """A starting point, not a finished bullet.

    Deliberately plain and free of quantities the repository cannot support.
    A file count is not an achievement, and the operator will rewrite this in
    their own terms before it goes anywhere near a CV.
    """
    what = evidence.signal.describes or evidence.competency
    where = f" in {scan.name}" if scan.name else ""
    when = f" ({scan.span})" if scan.span else ""
    return f"Built and maintained {what}{where}{when}."
