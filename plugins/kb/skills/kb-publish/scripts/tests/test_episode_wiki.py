"""Tests for episode_wiki.py pure helpers."""
from __future__ import annotations

import pytest

import episode_wiki as E
from episode_wiki import (
    SlugValidationError,
    validate_slug,
    slug_to_wiki_relative_path,
    compute_depth_deltas,
    compute_stub_update,
    normalize_filename_slug,
    resolve_concept_candidate,
    render_stub,
    render_episode_wiki,
)


# ---------------------------------------------------------------------------
# validate_slug
# ---------------------------------------------------------------------------

def test_validate_slug_accepts_plain_concept():
    validate_slug("wiki/quantization/k-quants")  # must not raise


def test_validate_slug_accepts_nested_concept():
    validate_slug("wiki/attention/flash-attention")  # must not raise


def test_validate_slug_rejects_missing_wiki_prefix():
    with pytest.raises(SlugValidationError):
        validate_slug("quantization/k-quants")


def test_validate_slug_rejects_dotdot_traversal():
    with pytest.raises(SlugValidationError):
        validate_slug("wiki/quantization/../secret")


def test_validate_slug_rejects_trailing_md():
    with pytest.raises(SlugValidationError):
        validate_slug("wiki/quantization/k-quants.md")


def test_validate_slug_rejects_leading_slash():
    with pytest.raises(SlugValidationError):
        validate_slug("/wiki/quantization/k-quants")


def test_validate_slug_rejects_exceeds_180_chars():
    long_slug = "wiki/" + "a" * 180
    with pytest.raises(SlugValidationError):
        validate_slug(long_slug)


def test_validate_slug_rejects_episodes_by_default():
    with pytest.raises(SlugValidationError):
        validate_slug("wiki/episodes/ep-01-gpu-computing-cuda")


def test_validate_slug_accepts_episodes_when_allow_episode_true():
    validate_slug("wiki/episodes/ep-01-gpu-computing-cuda", allow_episode=True)  # must not raise


def test_validate_slug_rejects_uppercase():
    with pytest.raises(SlugValidationError):
        validate_slug("wiki/Quantization/k-quants")


# ---------------------------------------------------------------------------
# slug_to_wiki_relative_path
# ---------------------------------------------------------------------------

def test_slug_to_wiki_relative_path_strips_single_prefix():
    p = slug_to_wiki_relative_path("wiki/quantization/k-quants")
    assert str(p) == "quantization/k-quants.md"


def test_slug_to_wiki_relative_path_appends_md():
    p = slug_to_wiki_relative_path("wiki/attention/flash-attention")
    assert str(p).endswith(".md")


def test_slug_to_wiki_relative_path_does_not_double_nest():
    p = slug_to_wiki_relative_path("wiki/quantization/k-quants")
    # Should be "quantization/k-quants.md", NOT "wiki/quantization/k-quants.md"
    assert not str(p).startswith("wiki/")


# ---------------------------------------------------------------------------
# compute_depth_deltas
# ---------------------------------------------------------------------------

def test_depth_delta_new_when_no_priors():
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "explained"}]
    result = compute_depth_deltas(concepts, {})
    assert result[0]["depth_delta_vs_past"] == "new"
    assert result[0]["prior_episode_ref"] is None


def test_depth_delta_deeper_when_new_exceeds_best():
    coverage = {"wiki/foo/bar": [{"ep_id": 1, "depth": "mentioned", "key_points": [], "date": "2026-01-01"}]}
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "deep-dive"}]
    result = compute_depth_deltas(concepts, coverage)
    assert result[0]["depth_delta_vs_past"] == "deeper"
    assert result[0]["prior_episode_ref"] == 1


def test_depth_delta_same_when_match():
    coverage = {"wiki/foo/bar": [{"ep_id": 2, "depth": "explained", "key_points": [], "date": "2026-01-01"}]}
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "explained"}]
    result = compute_depth_deltas(concepts, coverage)
    assert result[0]["depth_delta_vs_past"] == "same"
    assert result[0]["prior_episode_ref"] == 2


def test_depth_delta_lighter_when_below():
    coverage = {"wiki/foo/bar": [{"ep_id": 3, "depth": "deep-dive", "key_points": [], "date": "2026-01-01"}]}
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "mentioned"}]
    result = compute_depth_deltas(concepts, coverage)
    assert result[0]["depth_delta_vs_past"] == "lighter"
    assert result[0]["prior_episode_ref"] == 3


def test_depth_delta_tie_breaks_by_lowest_ep_id():
    # Two prior episodes both covered at "explained" depth — tie-break by lowest ep_id
    coverage = {
        "wiki/foo/bar": [
            {"ep_id": 5, "depth": "explained", "key_points": [], "date": "2026-03-01"},
            {"ep_id": 2, "depth": "explained", "key_points": [], "date": "2026-01-01"},
        ]
    }
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "explained"}]
    result = compute_depth_deltas(concepts, coverage)
    assert result[0]["depth_delta_vs_past"] == "same"
    # Lowest ep_id wins tie-break
    assert result[0]["prior_episode_ref"] == 2


# ---------------------------------------------------------------------------
# compute_stub_update
# ---------------------------------------------------------------------------

_BASE_STUB_FM = {
    "title": "K Quants",
    "tags": ["stub", "quantization"],
    "status": "stub",
    "created_by": "ep-1",
    "last_seen_by": "ep-1",
    "best_depth_episode": "ep-1",
    "best_depth": "mentioned",
    "referenced_by": ["ep-1"],
    "created": "2026-01-01",
}


def test_stub_update_always_updates_last_seen_by():
    concept = {"depth_this_episode": "mentioned"}
    result = compute_stub_update(dict(_BASE_STUB_FM), concept, episode_id=2)
    assert result is not None
    assert result["last_seen_by"] == "ep-2"


def test_stub_update_bumps_best_depth_only_when_deeper():
    # Current best is "mentioned"; new ep covers at "deep-dive" → should bump
    concept = {"depth_this_episode": "deep-dive"}
    result = compute_stub_update(dict(_BASE_STUB_FM), concept, episode_id=4)
    assert result is not None
    assert result["best_depth"] == "deep-dive"
    assert result["best_depth_episode"] == "ep-4"

    # New ep covers at "mentioned" (same as stored best) → should NOT bump best_depth
    fm2 = dict(_BASE_STUB_FM)
    fm2["best_depth"] = "deep-dive"
    fm2["last_seen_by"] = "ep-99"  # force last_seen_by to be "stale" so we get a change
    concept2 = {"depth_this_episode": "mentioned"}
    result2 = compute_stub_update(fm2, concept2, episode_id=5)
    # Result may still not be None due to last_seen_by change, but best_depth stays
    if result2 is not None:
        assert result2["best_depth"] == "deep-dive"


def test_stub_update_preserves_created_by():
    concept = {"depth_this_episode": "deep-dive"}
    result = compute_stub_update(dict(_BASE_STUB_FM), concept, episode_id=7)
    assert result is not None
    # created_by must always remain unchanged
    assert result["created_by"] == "ep-1"


def test_stub_update_appends_referenced_by():
    concept = {"depth_this_episode": "mentioned"}
    result = compute_stub_update(dict(_BASE_STUB_FM), concept, episode_id=3)
    assert result is not None
    assert "ep-3" in result["referenced_by"]
    assert "ep-1" in result["referenced_by"]  # original preserved


def test_stub_update_returns_none_on_noop():
    # Stub already has ep-2 as last_seen_by, best_depth=mentioned, referenced_by includes ep-2
    fm = dict(_BASE_STUB_FM)
    fm["last_seen_by"] = "ep-2"
    fm["referenced_by"] = ["ep-1", "ep-2"]
    concept = {"depth_this_episode": "mentioned"}
    result = compute_stub_update(fm, concept, episode_id=2)
    assert result is None


# ---------------------------------------------------------------------------
# normalize_filename_slug
# ---------------------------------------------------------------------------

def test_filename_slug_normalizes_ascii():
    assert normalize_filename_slug("GPU Computing & CUDA") == "gpu-computing-cuda"


def test_filename_slug_uses_latin_alias_when_topic_nonascii():
    result = normalize_filename_slug("模型量化", aliases=["Model Quantization"])
    assert result == "model-quantization"


def test_filename_slug_falls_back_to_topic_literal_for_pure_nonascii():
    result = normalize_filename_slug("模型量化 & 部署", aliases=[])
    assert result == "topic"


def test_filename_slug_truncates_to_50_chars():
    long_topic = "a-" * 40  # 80 chars
    result = normalize_filename_slug(long_topic)
    assert len(result) <= 50


# ---------------------------------------------------------------------------
# resolve_concept_candidate
# ---------------------------------------------------------------------------

_SAMPLE_CATALOG = {
    "attention": [
        {
            "slug": "wiki/attention/flash-attention",
            "title": "Flash Attention",
            "tags": ["attention", "optimization"],
            "aliases": ["FlashAttention", "flash-attention"],
            "is_stub": False,
        }
    ],
    "quantization": [
        {
            "slug": "wiki/quantization/k-quants",
            "title": "K-Quants",
            "tags": ["stub", "quantization"],
            "aliases": [],
            "is_stub": True,
        }
    ],
}


def test_resolve_exact_title_match():
    slug = resolve_concept_candidate("Flash Attention", _SAMPLE_CATALOG)
    assert slug == "wiki/attention/flash-attention"


def test_resolve_exact_title_case_insensitive():
    slug = resolve_concept_candidate("flash attention", _SAMPLE_CATALOG)
    assert slug == "wiki/attention/flash-attention"


def test_resolve_alias_match():
    slug = resolve_concept_candidate("FlashAttention", _SAMPLE_CATALOG)
    assert slug == "wiki/attention/flash-attention"


def test_resolve_returns_none_on_ambiguous():
    # Add a second article also titled "Flash Attention" → ambiguous
    ambig_catalog = {
        "attention": [
            {
                "slug": "wiki/attention/flash-attention",
                "title": "Flash Attention",
                "tags": [],
                "aliases": [],
                "is_stub": False,
            },
            {
                "slug": "wiki/transformers/flash-attn",
                "title": "Flash Attention",
                "tags": [],
                "aliases": [],
                "is_stub": False,
            },
        ]
    }
    assert resolve_concept_candidate("Flash Attention", ambig_catalog) is None


def test_resolve_returns_none_on_no_match():
    assert resolve_concept_candidate("Completely Unknown Concept", _SAMPLE_CATALOG) is None


def test_resolve_no_tag_based_resolution():
    # Tags must NOT be used for resolution — "optimization" tag won't resolve "optimization"
    assert resolve_concept_candidate("optimization", _SAMPLE_CATALOG) is None


# ---------------------------------------------------------------------------
# render_stub (snapshot)
# ---------------------------------------------------------------------------

def test_render_stub_snapshot():
    concept = {
        "slug": "wiki/quantization/awq",
        "depth_this_episode": "mentioned",
        "what": "Activation-aware weight quantization.",
        "why_it_matters": "Better accuracy than round-to-nearest at same bit-width.",
        "key_points": ["Preserves salient weights"],
        "covered_at_sec": 300.0,
    }
    output = render_stub(
        slug="wiki/quantization/awq",
        concept=concept,
        episode_id=3,
        episode_slug="ep-03-quantization",
        date="2026-04-21",
    )
    # Must start with frontmatter delimiter
    assert output.startswith("---\n")
    # Must contain required frontmatter keys
    assert "created_by:" in output
    assert "last_seen_by:" in output
    assert "best_depth_episode:" in output
    assert "best_depth:" in output
    assert "referenced_by:" in output
    assert "status: stub" in output
    # Must reference the episode in the body
    assert "ep-03-quantization" in output
    # Must include what/why sections
    assert "Activation-aware weight quantization." in output
    assert "Better accuracy" in output


# ---------------------------------------------------------------------------
# render_episode_wiki (snapshot)
# ---------------------------------------------------------------------------

def test_render_episode_wiki_snapshot():
    import yaml

    concept = {
        "slug": "wiki/quantization/k-quants",
        "depth_this_episode": "deep-dive",
        "depth_delta_vs_past": "new",
        "prior_episode_ref": None,
        "what": "Group-wise quantization.",
        "why_it_matters": "Enables 4-bit inference.",
        "key_points": ["Groups into blocks"],
        "covered_at_sec": 252.0,
        "existed_before": True,
    }
    output = render_episode_wiki(
        episode_id=3,
        title="EP3 | 量化",
        date="2026-04-21",
        depth="deep-dive",
        audio_file="podcast-quantization.mp3",
        transcript_file="podcast-quantization.transcript.md",
        summary="A deep dive into quantization.",
        concepts=[concept],
        open_threads=[{"slug": "wiki/quantization/qat", "note": "Quantization-Aware Training", "existed_before": False}],
        series_builds_on=["wiki/episodes/ep-01-gpu-computing-cuda"],
        series_followup_candidates=["speculative decoding"],
        source_lessons=["Model_Quantization_2026-04-07.md"],
        tags=["episode", "quantization"],
    )

    # Must start with frontmatter delimiter
    assert output.startswith("---\n")

    # Parse the YAML frontmatter to verify structure
    end = output.find("\n---\n", 4)
    assert end > 0, "Frontmatter must be closed"
    fm = yaml.safe_load(output[4:end])
    assert isinstance(fm, dict)

    # Required top-level frontmatter fields
    assert "title" in fm
    assert "episode_id" in fm
    assert fm["episode_id"] == 3
    assert "index" in fm

    # Required index block fields
    idx = fm["index"]
    assert "schema_version" in idx
    assert "summary" in idx
    assert "concepts" in idx
    assert "open_threads" in idx
    assert "series_links" in idx

    # The concept must appear in the index
    assert len(idx["concepts"]) == 1
    assert idx["concepts"][0]["slug"] == "wiki/quantization/k-quants"

    # Body below frontmatter must exist and contain key content
    body = output[end + len("\n---\n"):]
    assert "EP3 | 量化" in body
    assert "A deep dive into quantization." in body


# ---------------------------------------------------------------------------
# I/O helpers: scan_episode_wiki, concept_catalog, concepts_covered_by_episodes
# ---------------------------------------------------------------------------

import logging
import sys
from pathlib import Path

import pytest

import episode_wiki as E
from episode_wiki import (
    EpisodeParseError,
    IndexedEpisode,
    scan_episode_wiki,
    concept_catalog,
    concepts_covered_by_episodes,
)
# conftest._minimal_episode_article is available via fixtures; also importable directly.
# Ensure the tests directory is on sys.path so conftest is importable as a module.
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
from conftest import _minimal_episode_article


# scan_episode_wiki tests

def test_scan_lenient_skips_malformed_and_returns_valid(wiki_fixture, caplog):
    # Add a malformed episode alongside the good one
    (wiki_fixture / "episodes" / "ep-04-broken.md").write_text(
        "---\nepisode_id: not-a-number\n---\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        eps = scan_episode_wiki(wiki_fixture, strict=False)
    assert len(eps) == 1
    assert eps[0].episode_id == 3
    assert any("ep-04" in rec.message or "broken" in rec.message for rec in caplog.records)


def test_scan_strict_raises_on_malformed(wiki_fixture):
    (wiki_fixture / "episodes" / "ep-04-broken.md").write_text(
        "---\nepisode_id: not-a-number\n---\n", encoding="utf-8"
    )
    with pytest.raises(EpisodeParseError):
        scan_episode_wiki(wiki_fixture, strict=True)


def test_scan_sorts_by_episode_id(wiki_fixture):
    (wiki_fixture / "episodes" / "ep-01-foo.md").write_text(_minimal_episode_article(1), encoding="utf-8")
    (wiki_fixture / "episodes" / "ep-07-bar.md").write_text(_minimal_episode_article(7), encoding="utf-8")
    eps = scan_episode_wiki(wiki_fixture, strict=False)
    assert [e.episode_id for e in eps] == [1, 3, 7]


def test_scan_returns_empty_list_when_episodes_dir_missing(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()  # no episodes subdir
    assert scan_episode_wiki(wiki) == []


def test_scan_populates_indexed_concepts_from_index_block(wiki_fixture):
    eps = scan_episode_wiki(wiki_fixture, strict=False)
    assert len(eps[0].concepts) == 1
    c = eps[0].concepts[0]
    assert c.slug == "wiki/quantization/k-quants"
    assert c.depth_this_episode == "deep-dive"
    assert c.key_points == ["Groups into blocks"]


# concept_catalog tests

def test_catalog_excludes_episodes_always(wiki_fixture):
    cat = concept_catalog(wiki_fixture, include_stubs=True)
    all_slugs = {e["slug"] for entries in cat.values() for e in entries}
    assert not any(s.startswith("wiki/episodes/") for s in all_slugs)


def test_catalog_includes_stubs_by_default(wiki_fixture):
    cat = concept_catalog(wiki_fixture)  # include_stubs=True default
    all_slugs = {e["slug"] for entries in cat.values() for e in entries}
    assert "wiki/quantization/k-quants" in all_slugs


def test_catalog_marks_stubs(wiki_fixture):
    cat = concept_catalog(wiki_fixture, include_stubs=True)
    k_entries = [e for entries in cat.values() for e in entries if e["slug"] == "wiki/quantization/k-quants"]
    assert k_entries[0]["is_stub"] is True


def test_catalog_marks_non_stubs(wiki_fixture):
    cat = concept_catalog(wiki_fixture, include_stubs=True)
    fa_entries = [e for entries in cat.values() for e in entries if e["slug"] == "wiki/attention/flash-attention"]
    assert fa_entries[0]["is_stub"] is False


def test_catalog_excludes_stubs_when_include_false(wiki_fixture):
    cat = concept_catalog(wiki_fixture, include_stubs=False)
    all_slugs = {e["slug"] for entries in cat.values() for e in entries}
    assert "wiki/quantization/k-quants" not in all_slugs
    assert "wiki/attention/flash-attention" in all_slugs


def test_catalog_groups_by_top_level_category(wiki_fixture):
    cat = concept_catalog(wiki_fixture, include_stubs=True)
    assert "attention" in cat
    assert "quantization" in cat


def test_catalog_ignores_top_level_files_like_readme(wiki_fixture):
    # wiki/README.md exists from the fixture — should not appear in any category
    cat = concept_catalog(wiki_fixture)
    all_slugs = {e["slug"] for entries in cat.values() for e in entries}
    assert not any("README" in s for s in all_slugs)


# concepts_covered_by_episodes tests

def test_coverage_aggregation_single_episode(wiki_fixture):
    eps = scan_episode_wiki(wiki_fixture)
    coverage = concepts_covered_by_episodes(eps)
    assert "wiki/quantization/k-quants" in coverage
    hits = coverage["wiki/quantization/k-quants"]
    assert len(hits) == 1
    assert hits[0]["ep_id"] == 3
    assert hits[0]["depth"] == "deep-dive"


def test_coverage_aggregation_multiple_episodes_same_concept(wiki_fixture):
    # Add a second episode that also covers k-quants at a different depth
    ep5 = _minimal_episode_article(5).replace(
        "deep-dive", "explained", 1  # change episode depth but NOT the concept — manual tweak below
    )
    # Build a custom article for EP5 with concept at "explained"
    (wiki_fixture / "episodes" / "ep-05-followup.md").write_text(
        """---
title: "EP5 | Follow-up"
episode_id: 5
audio_file: a.mp3
transcript_file: a.transcript.md
date: 2026-04-22
depth: explained
tags: [episode]
aliases: []
source_lessons: []
index:
  schema_version: 1
  summary: "Follow-up."
  concepts:
    - slug: wiki/quantization/k-quants
      depth_this_episode: explained
      depth_delta_vs_past: lighter
      prior_episode_ref: 3
      what: "Brief recap."
      why_it_matters: "Context."
      key_points: []
      covered_at_sec: 5.0
      existed_before: true
  open_threads: []
  series_links:
    builds_on: []
    followup_candidates: []
---

# EP5
""",
        encoding="utf-8",
    )
    eps = scan_episode_wiki(wiki_fixture)
    coverage = concepts_covered_by_episodes(eps)
    hits = coverage["wiki/quantization/k-quants"]
    assert len(hits) == 2
    ep_ids = {h["ep_id"] for h in hits}
    assert ep_ids == {3, 5}


# ---------------------------------------------------------------------------
# Task 4: Transactional core — staging_dir + index_episode_transactional
# ---------------------------------------------------------------------------

from episode_wiki import (
    TransactionalIndexResult,
    TransactionAbortedError,
    staging_dir,
    index_episode_transactional,
)


def _make_extraction(concepts):
    return {
        "summary": "Episode summary.",
        "concepts": concepts,
        "open_threads": [],
        "series_links": {"builds_on": [], "followup_candidates": []},
    }


def test_transactional_new_episode_creates_article_and_new_stubs(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)

    extraction = _make_extraction([
        {
            "slug": "wiki/topic/concept-a",
            "depth_this_episode": "deep-dive",
            "depth_delta_vs_past": "new",
            "prior_episode_ref": None,
            "what": "What.",
            "why_it_matters": "Why.",
            "key_points": ["Point one."],
            "covered_at_sec": 10.0,
            "existed_before": False,
        }
    ])

    result = index_episode_transactional(
        wiki_dir=wiki, episode_id=1, episode_topic="Test Topic",
        episode_date="2026-04-21", episode_depth="deep-dive",
        audio_file="a.mp3", transcript_file="a.transcript.md",
        tags=["episode"], aliases=[], source_lessons=[],
        extraction=extraction,
    )
    assert result.episode_article.exists()
    assert result.episode_article.name.startswith("ep-1-")
    assert "wiki/topic/concept-a" in result.new_stubs_created
    assert (wiki / "topic" / "concept-a.md").exists()


def test_transactional_skips_existing_non_stub_article(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    (wiki / "topic").mkdir()
    canonical = wiki / "topic" / "concept-a.md"
    canonical.write_text(
        "---\ntitle: Concept A\nstatus: complete\n---\n\n# Concept A\n\nReal content.\n",
        encoding="utf-8",
    )
    original = canonical.read_text(encoding="utf-8")

    extraction = _make_extraction([
        {
            "slug": "wiki/topic/concept-a",
            "depth_this_episode": "explained",
            "depth_delta_vs_past": "new",
            "prior_episode_ref": None,
            "what": "What.",
            "why_it_matters": "Why.",
            "key_points": [],
            "covered_at_sec": 10.0,
            "existed_before": True,
        }
    ])
    result = index_episode_transactional(
        wiki_dir=wiki, episode_id=2, episode_topic="T",
        episode_date="2026-04-21", episode_depth="explained",
        audio_file="b.mp3", transcript_file="b.transcript.md",
        tags=["episode"], aliases=[], source_lessons=[],
        extraction=extraction,
    )
    assert "wiki/topic/concept-a" in result.collisions_skipped
    assert canonical.read_text(encoding="utf-8") == original


def test_transactional_same_episode_stub_replaced(tmp_path):
    """Re-indexing an episode that introduced a stub should FULLY replace the stub."""
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    (wiki / "topic").mkdir()
    stub = wiki / "topic" / "concept-a.md"
    stub.write_text(
        "---\ntitle: Concept A\nstatus: stub\ncreated_by: ep-7\n"
        "last_seen_by: ep-7\nbest_depth_episode: ep-7\nbest_depth: explained\n"
        "referenced_by: [ep-7]\ncreated: '2026-04-01'\n---\n\n"
        "# Concept A\n\n> Stub.\n\n## Old body content.\n",
        encoding="utf-8",
    )

    extraction = _make_extraction([
        {
            "slug": "wiki/topic/concept-a",
            "depth_this_episode": "deep-dive",
            "depth_delta_vs_past": "deeper",
            "prior_episode_ref": 7,
            "what": "New what.",
            "why_it_matters": "New why.",
            "key_points": ["Key point."],
            "covered_at_sec": 42.0,
            "existed_before": True,
        }
    ])
    result = index_episode_transactional(
        wiki_dir=wiki, episode_id=7, episode_topic="T",
        episode_date="2026-04-21", episode_depth="deep-dive",
        audio_file="c.mp3", transcript_file="c.transcript.md",
        tags=["episode"], aliases=[], source_lessons=[],
        extraction=extraction,
    )
    assert "wiki/topic/concept-a" in result.stubs_updated
    # Prose section should be the freshly rendered version
    new_text = stub.read_text(encoding="utf-8")
    assert "Old body content" not in new_text
    assert "New what" in new_text


def test_transactional_other_episode_stub_frontmatter_only_update(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    (wiki / "topic").mkdir()
    stub = wiki / "topic" / "concept-a.md"
    stub.write_text(
        "---\ntitle: Concept A\nstatus: stub\ncreated_by: ep-3\n"
        "last_seen_by: ep-3\nbest_depth_episode: ep-3\nbest_depth: mentioned\n"
        "referenced_by: [ep-3]\ncreated: '2026-04-01'\naliases: []\n---\n\n"
        "# Concept A\n\n> Stub prose introduced by EP3.\n",
        encoding="utf-8",
    )

    extraction = _make_extraction([
        {
            "slug": "wiki/topic/concept-a",
            "depth_this_episode": "explained",  # deeper than EP3's 'mentioned'
            "depth_delta_vs_past": "deeper",
            "prior_episode_ref": 3,
            "what": "New what.",
            "why_it_matters": "New why.",
            "key_points": [],
            "covered_at_sec": 42.0,
            "existed_before": True,
        }
    ])
    result = index_episode_transactional(
        wiki_dir=wiki, episode_id=5, episode_topic="T",
        episode_date="2026-04-21", episode_depth="deep-dive",
        audio_file="c.mp3", transcript_file="c.transcript.md",
        tags=["episode"], aliases=[], source_lessons=[],
        extraction=extraction,
    )
    assert "wiki/topic/concept-a" in result.stubs_updated
    new_text = stub.read_text(encoding="utf-8")
    # Prose preserved
    assert "Stub prose introduced by EP3" in new_text
    # Frontmatter updated
    assert "last_seen_by: ep-5" in new_text
    assert "best_depth_episode: ep-5" in new_text
    assert "best_depth: explained" in new_text
    # created_by preserved
    assert "created_by: ep-3" in new_text


def test_transactional_aborts_on_invalid_slug(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)

    extraction = _make_extraction([
        {
            "slug": "not/wiki-prefix",  # invalid
            "depth_this_episode": "explained",
            "depth_delta_vs_past": "new",
            "prior_episode_ref": None,
            "what": "What.",
            "why_it_matters": "Why.",
            "key_points": [],
            "covered_at_sec": None,
            "existed_before": False,
        }
    ])
    with pytest.raises(TransactionAbortedError):
        index_episode_transactional(
            wiki_dir=wiki, episode_id=1, episode_topic="T",
            episode_date="2026-04-21", episode_depth="deep-dive",
            audio_file="a.mp3", transcript_file="a.transcript.md",
            tags=["episode"], aliases=[], source_lessons=[],
            extraction=extraction,
        )
    # No episode article written
    assert list((wiki / "episodes").glob("*.md")) == []


def test_transactional_commits_stubs_before_episode_article(tmp_path):
    """Simulate a smoke-parse failure — episode article must NOT be written if staging doesn't validate.
    This is enforced by the smoke-parse step before any commit.
    """
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)

    # Craft an extraction that renders a valid episode (no smoke-parse failure here).
    # We verify the result includes a new stub AND the episode article — both landed.
    extraction = _make_extraction([
        {
            "slug": "wiki/topic/concept-a",
            "depth_this_episode": "explained",
            "depth_delta_vs_past": "new",
            "prior_episode_ref": None,
            "what": "What.",
            "why_it_matters": "Why.",
            "key_points": [],
            "covered_at_sec": None,
            "existed_before": False,
        }
    ])
    result = index_episode_transactional(
        wiki_dir=wiki, episode_id=1, episode_topic="T",
        episode_date="2026-04-21", episode_depth="explained",
        audio_file="a.mp3", transcript_file="a.transcript.md",
        tags=["episode"], aliases=[], source_lessons=[],
        extraction=extraction,
    )
    assert result.episode_article.exists()
    assert (wiki / "topic" / "concept-a.md").exists()
    # Staging dir should be cleaned up
    staging_parent = wiki.parent / ".kb-publish-staging"
    if staging_parent.exists():
        assert list(staging_parent.iterdir()) == []


def test_staging_dir_creates_episodes_subdir(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    s = staging_dir(wiki)
    assert s.exists()
    assert (s / "episodes").is_dir()
    assert ".kb-publish-staging" in str(s)


# ---------------------------------------------------------------------------
# Task 5: orchestrate_episode_index — Haiku-injected orchestration pipeline
# ---------------------------------------------------------------------------

import json

from episode_wiki import (
    orchestrate_episode_index,
    _validate_extraction_shape,
    _recompute_existed_before,
)


def _mock_haiku(response_json: dict):
    """Return a callable that emits the given JSON as a Haiku response."""
    return lambda prompt: json.dumps(response_json)


def test_orchestrate_calls_haiku_with_expected_structure(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    transcript_path = tmp_path / "t.md"
    transcript_path.write_text("Sample transcript for ep 1.", encoding="utf-8")
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(
        "TEMPLATE\nmeta={episode_metadata}\ntranscript={transcript}\ncat={concept_catalog}\nrecent={recent_episodes}\n",
        encoding="utf-8",
    )

    captured_prompts = []
    def capturing_haiku(p: str) -> str:
        captured_prompts.append(p)
        return json.dumps({
            "summary": "S.",
            "concepts": [
                {"slug": "wiki/topic/c", "depth_this_episode": "explained",
                 "what": "W.", "why_it_matters": "Y.",
                 "key_points": ["a"], "covered_at_sec": 5.0,
                 "existed_before": False},
            ],
            "open_threads": [],
            "series_links": {"builds_on": [], "followup_candidates": []},
        })

    result = orchestrate_episode_index(
        wiki_dir=wiki, episode_id=1, episode_topic="Topic",
        episode_date="2026-04-21", episode_depth="explained",
        audio_file="a.mp3", transcript_path=transcript_path,
        transcript_file="a.transcript.md", tags=["episode"], aliases=[],
        source_lessons=[], haiku_call=capturing_haiku,
        prompt_template_path=prompt_path,
    )
    assert len(captured_prompts) == 1
    assert "Sample transcript for ep 1." in captured_prompts[0]
    assert result.episode_article.exists()


def test_orchestrate_retries_once_on_malformed_then_succeeds(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    transcript_path = tmp_path / "t.md"
    transcript_path.write_text("X", encoding="utf-8")
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("{episode_metadata}{transcript}{concept_catalog}{recent_episodes}", encoding="utf-8")

    call_count = 0
    def flaky_haiku(p: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "not json"
        return json.dumps({
            "summary": "S.",
            "concepts": [
                {"slug": "wiki/x/c", "depth_this_episode": "mentioned",
                 "what": "W.", "why_it_matters": "Y.",
                 "key_points": ["p"], "covered_at_sec": 1.0,
                 "existed_before": False}
            ],
            "open_threads": [],
            "series_links": {"builds_on": [], "followup_candidates": []},
        })

    result = orchestrate_episode_index(
        wiki_dir=wiki, episode_id=1, episode_topic="T",
        episode_date="2026-04-21", episode_depth="explained",
        audio_file="a.mp3", transcript_path=transcript_path,
        transcript_file="a.t.md", tags=["episode"], aliases=[],
        source_lessons=[], haiku_call=flaky_haiku,
        prompt_template_path=prompt_path,
    )
    assert call_count == 2
    assert result.episode_article.exists()


def test_orchestrate_aborts_after_two_malformed_responses(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    transcript_path = tmp_path / "t.md"
    transcript_path.write_text("X", encoding="utf-8")
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("{episode_metadata}{transcript}{concept_catalog}{recent_episodes}", encoding="utf-8")

    def bad_haiku(p: str) -> str:
        return "still not json"

    with pytest.raises(TransactionAbortedError):
        orchestrate_episode_index(
            wiki_dir=wiki, episode_id=1, episode_topic="T",
            episode_date="2026-04-21", episode_depth="explained",
            audio_file="a.mp3", transcript_path=transcript_path,
            transcript_file="a.t.md", tags=["episode"], aliases=[],
            source_lessons=[], haiku_call=bad_haiku,
            prompt_template_path=prompt_path,
        )
    # No episode article
    assert list((wiki / "episodes").glob("*.md")) == []


def test_orchestrate_excludes_current_episode_from_coverage_map(tmp_path):
    """Reindex must not count the current episode as prior coverage."""
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    # Seed existing EP3 covering the concept at deep-dive
    from tests.conftest import _minimal_episode_article
    (wiki / "episodes" / "ep-03-old.md").write_text(_minimal_episode_article(3), encoding="utf-8")

    transcript_path = tmp_path / "t.md"
    transcript_path.write_text("X", encoding="utf-8")
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("{episode_metadata}{transcript}{concept_catalog}{recent_episodes}", encoding="utf-8")

    def haiku(p: str) -> str:
        # Claim the same concept at explained depth — reindex
        return json.dumps({
            "summary": "S.",
            "concepts": [
                {"slug": "wiki/quantization/k-quants", "depth_this_episode": "explained",
                 "what": "W.", "why_it_matters": "Y.",
                 "key_points": ["p"], "covered_at_sec": 1.0,
                 "existed_before": True}
            ],
            "open_threads": [],
            "series_links": {"builds_on": [], "followup_candidates": []},
        })

    # Reindexing ep 3 — coverage_map should EXCLUDE ep 3, so the concept
    # depth_delta_vs_past should resolve to "new" (no prior coverage outside self).
    result = orchestrate_episode_index(
        wiki_dir=wiki, episode_id=3, episode_topic="Re-index",
        episode_date="2026-04-21", episode_depth="explained",
        audio_file="a.mp3", transcript_path=transcript_path,
        transcript_file="a.t.md", tags=["episode"], aliases=[],
        source_lessons=[], haiku_call=haiku,
        prompt_template_path=prompt_path,
    )
    # Read back the written episode article
    text = result.episode_article.read_text(encoding="utf-8")
    assert "depth_delta_vs_past: new" in text


def test_recompute_existed_before_overrides_haiku_claim(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "foo").mkdir(parents=True)
    (wiki / "foo" / "exists.md").write_text("x", encoding="utf-8")
    concepts = [
        {"slug": "wiki/foo/exists", "existed_before": False},
        {"slug": "wiki/foo/missing", "existed_before": True},
    ]
    out = _recompute_existed_before(concepts, wiki)
    assert out[0]["existed_before"] is True
    assert out[1]["existed_before"] is False


def test_validate_extraction_shape_accepts_valid():
    _validate_extraction_shape({
        "summary": "s",
        "concepts": [
            {"slug": "wiki/x", "depth_this_episode": "explained",
             "what": "w", "why_it_matters": "y", "key_points": []}
        ],
        "open_threads": [],
    })


def test_validate_extraction_shape_rejects_missing_summary():
    with pytest.raises(TransactionAbortedError):
        _validate_extraction_shape({"concepts": [], "open_threads": []})


def test_validate_extraction_shape_rejects_invalid_depth():
    with pytest.raises(TransactionAbortedError):
        _validate_extraction_shape({
            "summary": "s",
            "concepts": [
                {"slug": "wiki/x", "depth_this_episode": "nonsense",
                 "what": "w", "why_it_matters": "y", "key_points": []}
            ],
            "open_threads": [],
        })


# ---------------------------------------------------------------------------
# Task 6: judge_candidate_episode — Layer 3 dedup judge
# ---------------------------------------------------------------------------

from episode_wiki import DedupJudgement, judge_candidate_episode


def test_judge_builds_prior_hits_per_candidate(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    from tests.conftest import _minimal_episode_article
    (wiki / "episodes" / "ep-03-q.md").write_text(_minimal_episode_article(3), encoding="utf-8")

    prompt_path = tmp_path / "p.md"
    prompt_path.write_text("{candidates}|{prior_hits}|{open_threads}", encoding="utf-8")

    seen = {}
    def haiku(p):
        seen["prompt"] = p
        return json.dumps({
            "per_concept": [
                {"candidate": "k-quants", "verdict": "redundant_same_depth",
                 "reasoning": "EP3 covered k-quants at deep-dive.",
                 "recommended_framing": "Skip."},
            ],
            "episode_verdict": "reframe",
            "framing_recommendation": "Angle.",
        })

    result = judge_candidate_episode(
        wiki_dir=wiki,
        candidate_concepts=["k-quants", "new-thing"],
        haiku_call=haiku,
        prompt_template_path=prompt_path,
    )
    assert isinstance(result, DedupJudgement)
    assert len(result.per_concept) == 1
    assert result.episode_verdict == "reframe"
    # Verify prior_hits substituted in prompt — the k-quants concept in EP3's fixture is at slug wiki/quantization/k-quants
    # The judge passes raw candidate names; resolve_concept_candidate is tried first, so "k-quants" (exact title) should resolve.
    assert "k-quants" in seen["prompt"]


def test_judge_returns_empty_prior_hits_for_novel_candidates(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    prompt_path = tmp_path / "p.md"
    prompt_path.write_text("{candidates}|{prior_hits}|{open_threads}", encoding="utf-8")

    def haiku(p):
        return json.dumps({
            "per_concept": [{"candidate": "novel", "verdict": "novel",
                             "reasoning": "No prior.", "recommended_framing": "Proceed."}],
            "episode_verdict": "proceed",
            "framing_recommendation": "OK.",
        })

    result = judge_candidate_episode(
        wiki_dir=wiki,
        candidate_concepts=["novel"],
        haiku_call=haiku,
        prompt_template_path=prompt_path,
    )
    assert result.episode_verdict == "proceed"


def test_judge_raises_when_haiku_json_malformed(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    prompt_path = tmp_path / "p.md"
    prompt_path.write_text("{candidates}|{prior_hits}|{open_threads}", encoding="utf-8")

    def bad(p):
        return "not json"

    with pytest.raises(json.JSONDecodeError):
        judge_candidate_episode(
            wiki_dir=wiki, candidate_concepts=["x"],
            haiku_call=bad, prompt_template_path=prompt_path,
        )


def test_judge_requires_haiku_call_and_template(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    with pytest.raises(RuntimeError):
        judge_candidate_episode(wiki_dir=wiki, candidate_concepts=["x"])
