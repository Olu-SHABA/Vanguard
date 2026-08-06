"""
Rank score — queue ordering only.

    S = mpnet document-level cosine similarity between CV and job description

**S never gates.** Coverage decides whether a vacancy proceeds; S decides only
what the operator looks at first. The distinction matters: a document-level
embedding cannot answer *which requirement failed*, so it cannot carry the
audit duty a gate requires.

Two models, deliberately different:

    all-mpnet-base-v2    document-level ranking. Quality over interpretability
    all-MiniLM-L6-v2     per-term stage-3 fallback in coverage. Short strings,
                         where the quality gap narrows and speed compounds

Both run locally rather than via API. The CV carries personal data — name,
address, telephone, full employment history — and a scoring run makes hundreds
of calls.

Embeddings are cached to disk keyed by (model, sha256 of text), so re-running
against the same CV does not re-embed it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

__all__ = [
    "DOCUMENT_MODEL",
    "TERM_MODEL",
    "EmbeddingCache",
    "SentenceTransformerEmbedder",
    "LexicalEmbedder",
    "rank_score",
    "cosine",
]

DOCUMENT_MODEL = "sentence-transformers/all-mpnet-base-v2"
TERM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class RankError(RuntimeError):
    """Ranking could not be computed."""


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity. Returns 0.0 for a zero vector rather than raising."""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

@dataclass
class EmbeddingCache:
    """Disk-backed vector cache keyed by (model, sha256 of text).

    Corruption is survivable: a bad cache file is discarded and rebuilt rather
    than crashing a scoring run.
    """

    path: Path
    _data: dict[str, list[float]] | None = None

    def _load(self) -> dict[str, list[float]]:
        if self._data is not None:
            return self._data
        self._data = {}
        if self.path.is_file():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._data = {}
        return self._data

    @staticmethod
    def key(model: str, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
        return f"{model}:{digest}"

    def get(self, model: str, text: str) -> list[float] | None:
        return self._load().get(self.key(model, text))

    def put(self, model: str, text: str, vector: Sequence[float]) -> None:
        self._load()[self.key(model, text)] = list(vector)

    def flush(self) -> None:
        if self._data is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass  # a cache write failure must never fail a scoring run


# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------

class SentenceTransformerEmbedder:
    """Local sentence-transformers model. Loaded lazily on first use.

    Import and model load are deferred so the module is importable — and the
    rest of the pipeline testable — without torch installed.
    """

    def __init__(self, model_name: str = TERM_MODEL, cache: EmbeddingCache | None = None) -> None:
        self.model_name = model_name
        self.cache = cache
        self._model = None

    def _ensure(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RankError(
                    "sentence-transformers required: pip install -e '.[scoring]'"
                ) from exc
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        if self.cache is not None:
            hit = self.cache.get(self.model_name, text)
            if hit is not None:
                return hit
        vector = [float(x) for x in self._ensure().encode(text, normalize_embeddings=True)]
        if self.cache is not None:
            self.cache.put(self.model_name, text, vector)
        return vector

    def similarity(self, a: str, b: str) -> float:
        return cosine(self.embed(a), self.embed(b))


class LexicalEmbedder:
    """Deterministic token-overlap fallback. No model, no network, no torch.

    NOT a substitute for the real embedder — it is synonym-blind, which is the
    exact weakness stage 3 exists to cover. Two uses only:

      * testing the coverage pipeline end to end without a 2GB dependency
      * degraded operation when the model is unavailable, where a flagged
        SOFT_HIT is still better than silently scoring every term as a GAP

    Runs should record which embedder produced them.
    """

    name = "lexical"

    _TOKEN = re.compile(r"[a-z0-9]+")
    _STOP = frozenset(
        "a an the and or of in to for with as is are be will you we our your on at by from that this".split()
    )

    def tokens(self, text: str) -> set[str]:
        return {t for t in self._TOKEN.findall(text.lower()) if t not in self._STOP and len(t) > 2}

    def similarity(self, a: str, b: str) -> float:
        """Weighted Jaccard, biased toward covering the shorter string.

        A three-word requirement fully contained in a long CV bullet should
        score high; plain Jaccard would penalise it for the length difference.
        """
        ta, tb = self.tokens(a), self.tokens(b)
        if not ta or not tb:
            return 0.0
        overlap = len(ta & tb)
        return 0.7 * (overlap / min(len(ta), len(tb))) + 0.3 * (overlap / len(ta | tb))


# ---------------------------------------------------------------------------
# Document-level rank
# ---------------------------------------------------------------------------

def rank_score(
    cv_text: str,
    advert_text: str,
    embedder: SentenceTransformerEmbedder | LexicalEmbedder | None = None,
) -> float:
    """Document-level similarity for queue ordering. Never gates.

    Returns 0.0–1.0. A low absolute value is expected and meaningless in
    isolation — a CV and an advert are different genres of document, and the
    score is structurally capped well below 1.0 even for a perfect candidate.
    Only the ordering across vacancies carries information.
    """
    if not cv_text.strip() or not advert_text.strip():
        return 0.0
    if embedder is None:
        embedder = SentenceTransformerEmbedder(DOCUMENT_MODEL)
    return float(embedder.similarity(cv_text, advert_text))
