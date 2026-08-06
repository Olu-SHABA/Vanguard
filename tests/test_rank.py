"""Rank score, embedding cache, lexical fallback."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanguard.rank import EmbeddingCache, LexicalEmbedder, cosine, rank_score


def test_cosine_identical_is_one() -> None:
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector_returns_zero_not_error() -> None:
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine([1.0], [1.0, 2.0])


# --- cache ----------------------------------------------------------------

def test_cache_round_trips(tmp_path: Path) -> None:
    c = EmbeddingCache(tmp_path / "e.json")
    c.put("m", "hello", [0.1, 0.2])
    c.flush()
    assert EmbeddingCache(tmp_path / "e.json").get("m", "hello") == [0.1, 0.2]


def test_cache_miss_returns_none(tmp_path: Path) -> None:
    assert EmbeddingCache(tmp_path / "e.json").get("m", "absent") is None


def test_cache_key_varies_by_model(tmp_path: Path) -> None:
    c = EmbeddingCache(tmp_path / "e.json")
    assert c.key("a", "text") != c.key("b", "text")


def test_corrupt_cache_is_survivable(tmp_path: Path) -> None:
    p = tmp_path / "e.json"
    p.write_text("{ not json")
    assert EmbeddingCache(p).get("m", "x") is None


def test_cache_write_failure_does_not_raise(tmp_path: Path) -> None:
    """A cache write failure must never fail a scoring run."""
    c = EmbeddingCache(tmp_path / "nodir" / "e.json")
    c.put("m", "x", [1.0])
    c.flush()


# --- lexical fallback -----------------------------------------------------

def test_lexical_identical_scores_high() -> None:
    e = LexicalEmbedder()
    assert e.similarity("automated data pipelines", "automated data pipelines") > 0.9


def test_lexical_unrelated_scores_low() -> None:
    e = LexicalEmbedder()
    assert e.similarity("network telemetry", "underwater basket weaving") < 0.2


def test_lexical_is_synonym_blind() -> None:
    """Documents the known limitation — this is why stage 3 wants a real model."""
    e = LexicalEmbedder()
    assert e.similarity("version control", "source code management") < 0.5


def test_lexical_stopwords_ignored() -> None:
    e = LexicalEmbedder()
    assert e.similarity("the and of", "a an to") == 0.0


def test_lexical_short_requirement_in_long_bullet() -> None:
    e = LexicalEmbedder()
    long = ("Automated data pipelines and ETL workflows in Python, reducing "
            "data processing time by 50% and enabling near real-time analytics.")
    assert e.similarity("ETL workflows Python", long) > 0.6


# --- rank -----------------------------------------------------------------

def test_rank_score_in_range() -> None:
    s = rank_score("a cv about python and sql", "a role needing python", LexicalEmbedder())
    assert 0.0 <= s <= 1.0


def test_rank_score_empty_input_is_zero() -> None:
    assert rank_score("", "text", LexicalEmbedder()) == 0.0
    assert rank_score("text", "   ", LexicalEmbedder()) == 0.0
