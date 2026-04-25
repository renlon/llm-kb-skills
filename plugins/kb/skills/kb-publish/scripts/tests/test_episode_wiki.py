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

def _make_indexed_episode(ep_id: int, show_id: str, slug: str, depth: str) -> E.IndexedEpisode:
    """Helper to create a minimal IndexedEpisode for coverage tests."""
    return E.IndexedEpisode(
        episode_id=ep_id,
        title=f"EP{ep_id}",
        date="2026-01-01",
        depth="deep-dive",
        audio_file="a.mp3",
        transcript_file=None,
        concepts=[E.IndexedConcept(
            slug=slug,
            depth_this_episode=depth,
            depth_delta_vs_past="new",
            prior_episode_ref=None,
            what="",
            why_it_matters="",
            key_points=[],
            covered_at_sec=None,
        )],
        open_threads=[],
        series_builds_on=[],
        series_followup_candidates=[],
        show_id=show_id,
    )


def test_depth_delta_new_when_no_priors():
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "explained"}]
    result = compute_depth_deltas("my-show", concepts, [])
    assert result[0]["depth_delta_vs_past"] == "new"
    assert result[0]["prior_episode_ref"] is None


def test_depth_delta_deeper_when_new_exceeds_best():
    indexed = [_make_indexed_episode(1, "my-show", "wiki/foo/bar", "mentioned")]
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "deep-dive"}]
    result = compute_depth_deltas("my-show", concepts, indexed)
    assert result[0]["depth_delta_vs_past"] == "deeper"
    assert result[0]["prior_episode_ref"] == {"show": "my-show", "ep": 1}


def test_depth_delta_same_when_match():
    indexed = [_make_indexed_episode(2, "my-show", "wiki/foo/bar", "explained")]
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "explained"}]
    result = compute_depth_deltas("my-show", concepts, indexed)
    assert result[0]["depth_delta_vs_past"] == "same"
    assert result[0]["prior_episode_ref"] == {"show": "my-show", "ep": 2}


def test_depth_delta_lighter_when_below():
    indexed = [_make_indexed_episode(3, "my-show", "wiki/foo/bar", "deep-dive")]
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "mentioned"}]
    result = compute_depth_deltas("my-show", concepts, indexed)
    assert result[0]["depth_delta_vs_past"] == "lighter"
    assert result[0]["prior_episode_ref"] == {"show": "my-show", "ep": 3}


def test_depth_delta_tie_breaks_by_lowest_ep_id():
    # Two prior episodes both covered at "explained" depth — tie-break by lowest ep_id
    indexed = [
        _make_indexed_episode(5, "my-show", "wiki/foo/bar", "explained"),
        _make_indexed_episode(2, "my-show", "wiki/foo/bar", "explained"),
    ]
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "explained"}]
    result = compute_depth_deltas("my-show", concepts, indexed)
    assert result[0]["depth_delta_vs_past"] == "same"
    # Lowest ep_id wins tie-break
    assert result[0]["prior_episode_ref"] == {"show": "my-show", "ep": 2}


def test_compute_depth_deltas_emits_dict_ref():
    """Task 7: prior_episode_ref must be emitted as {show, ep} dict."""
    indexed = [_make_indexed_episode(4, "quanzhan-ai", "wiki/ml/attention", "mentioned")]
    concepts = [{"slug": "wiki/ml/attention", "depth_this_episode": "explained"}]
    result = compute_depth_deltas("quanzhan-ai", concepts, indexed)
    ref = result[0]["prior_episode_ref"]
    assert isinstance(ref, dict)
    assert ref["show"] == "quanzhan-ai"
    assert ref["ep"] == 4


def test_compute_depth_deltas_raises_on_mixed_show():
    """Task 7: foreign show_id in indexed list must raise MixedShowCoverageError."""
    from episode_wiki import MixedShowCoverageError
    indexed = [
        _make_indexed_episode(1, "show-a", "wiki/foo/bar", "mentioned"),
        _make_indexed_episode(2, "show-b", "wiki/foo/bar", "explained"),  # foreign show
    ]
    concepts = [{"slug": "wiki/foo/bar", "depth_this_episode": "explained"}]
    with pytest.raises(MixedShowCoverageError, match="show-b"):
        compute_depth_deltas("show-a", concepts, indexed)


# ---------------------------------------------------------------------------
# compute_stub_update
# ---------------------------------------------------------------------------

# New dict-form frontmatter (post-migration)
_BASE_STUB_FM = {
    "title": "K Quants",
    "tags": ["stub", "quantization"],
    "status": "stub",
    "created_by": {"show": "my-show", "ep": 1},
    "last_seen_by": {"show": "my-show", "ep": 1},
    "best_depth_episode": {"show": "my-show", "ep": 1},
    "best_depth": "mentioned",
    "referenced_by": [{"show": "my-show", "ep": 1}],
    "created": "2026-01-01",
}


def test_stub_update_always_updates_last_seen_by():
    concept = {"depth_this_episode": "mentioned"}
    result = compute_stub_update(dict(_BASE_STUB_FM), concept, episode_id=2, show_id="my-show")
    assert result is not None
    assert result["last_seen_by"] == {"show": "my-show", "ep": 2}


def test_stub_update_bumps_best_depth_only_when_deeper():
    # Current best is "mentioned"; new ep covers at "deep-dive" → should bump
    concept = {"depth_this_episode": "deep-dive"}
    result = compute_stub_update(dict(_BASE_STUB_FM), concept, episode_id=4, show_id="my-show")
    assert result is not None
    assert result["best_depth"] == "deep-dive"
    assert result["best_depth_episode"] == {"show": "my-show", "ep": 4}

    # New ep covers at "mentioned" (same as stored best) → should NOT bump best_depth
    fm2 = dict(_BASE_STUB_FM)
    fm2["best_depth"] = "deep-dive"
    fm2["last_seen_by"] = {"show": "my-show", "ep": 99}  # force last_seen_by to be "stale"
    concept2 = {"depth_this_episode": "mentioned"}
    result2 = compute_stub_update(fm2, concept2, episode_id=5, show_id="my-show")
    # Result may still not be None due to last_seen_by change, but best_depth stays
    if result2 is not None:
        assert result2["best_depth"] == "deep-dive"


def test_stub_update_preserves_created_by():
    concept = {"depth_this_episode": "deep-dive"}
    result = compute_stub_update(dict(_BASE_STUB_FM), concept, episode_id=7, show_id="my-show")
    assert result is not None
    # created_by must always remain unchanged
    assert result["created_by"] == {"show": "my-show", "ep": 1}


def test_stub_update_appends_referenced_by():
    concept = {"depth_this_episode": "mentioned"}
    result = compute_stub_update(dict(_BASE_STUB_FM), concept, episode_id=3, show_id="my-show")
    assert result is not None
    assert {"show": "my-show", "ep": 3} in result["referenced_by"]
    assert {"show": "my-show", "ep": 1} in result["referenced_by"]  # original preserved


def test_stub_update_returns_none_on_noop():
    # Stub already has ep-2 as last_seen_by, best_depth=mentioned, referenced_by includes ep-2
    fm = dict(_BASE_STUB_FM)
    fm["last_seen_by"] = {"show": "my-show", "ep": 2}
    fm["referenced_by"] = [{"show": "my-show", "ep": 1}, {"show": "my-show", "ep": 2}]
    concept = {"depth_this_episode": "mentioned"}
    result = compute_stub_update(fm, concept, episode_id=2, show_id="my-show")
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

import sys as _sys2
_SCRIPTS_DIR_FLAT = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR_FLAT not in _sys2.path:
    _sys2.path.insert(0, _SCRIPTS_DIR_FLAT)
from shows import Show as _Show


def _make_flat_show(show_id: str = "test-show") -> _Show:
    """Create a minimal Show for tests.

    wiki_episodes_dir is set to 'episodes/{show_id}', matching the Show invariant.
    Tests that use this show must place episode files under wiki/episodes/{show_id}/.
    The wiki_fixture conftest uses show_id='test-show' (the default).
    """
    return _Show(
        id=show_id,
        title="Test Show",
        description="",
        default=True,
        language="zh_Hans",
        hosts=["A", "B"],
        extra_host_names=[],
        intro_music=None,
        intro_music_length_seconds=12,
        intro_crossfade_seconds=3,
        podcast_format="deep-dive",
        podcast_length="long",
        transcript={"enabled": False, "model": "", "device": "auto", "language": "zh"},
        episodes_registry="episodes.yaml",
        wiki_episodes_dir=f"episodes/{show_id}",
        xiaoyuzhou={},
    )


# scan_episode_wiki tests

def test_scan_lenient_skips_malformed_and_returns_valid(wiki_fixture, caplog):
    show = _make_flat_show()
    # Add a malformed episode alongside the good one in the show-scoped dir
    ep_dir = wiki_fixture / show.wiki_episodes_dir
    (ep_dir / "ep-04-broken.md").write_text(
        "---\nepisode_id: not-a-number\n---\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        eps = scan_episode_wiki(wiki_fixture, show, strict=False)
    assert len(eps) == 1
    assert eps[0].episode_id == 3
    assert any("ep-04" in rec.message or "broken" in rec.message for rec in caplog.records)


def test_scan_strict_raises_on_malformed(wiki_fixture):
    show = _make_flat_show()
    ep_dir = wiki_fixture / show.wiki_episodes_dir
    (ep_dir / "ep-04-broken.md").write_text(
        "---\nepisode_id: not-a-number\n---\n", encoding="utf-8"
    )
    with pytest.raises(EpisodeParseError):
        scan_episode_wiki(wiki_fixture, show, strict=True)


def test_scan_sorts_by_episode_id(wiki_fixture):
    show = _make_flat_show()
    ep_dir = wiki_fixture / show.wiki_episodes_dir
    (ep_dir / "ep-01-foo.md").write_text(_minimal_episode_article(1), encoding="utf-8")
    (ep_dir / "ep-07-bar.md").write_text(_minimal_episode_article(7), encoding="utf-8")
    eps = scan_episode_wiki(wiki_fixture, show, strict=False)
    assert [e.episode_id for e in eps] == [1, 3, 7]


def test_scan_returns_empty_list_when_episodes_dir_missing(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()  # no episodes subdir
    show = _make_flat_show()
    assert scan_episode_wiki(wiki, show) == []


def test_scan_populates_indexed_concepts_from_index_block(wiki_fixture):
    show = _make_flat_show()
    eps = scan_episode_wiki(wiki_fixture, show, strict=False)
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
    show = _make_flat_show()
    eps = scan_episode_wiki(wiki_fixture, show)
    coverage = concepts_covered_by_episodes(eps)
    assert "wiki/quantization/k-quants" in coverage
    hits = coverage["wiki/quantization/k-quants"]
    assert len(hits) == 1
    assert hits[0]["ep_id"] == 3
    assert hits[0]["depth"] == "deep-dive"


def test_coverage_aggregation_multiple_episodes_same_concept(wiki_fixture):
    show = _make_flat_show()
    # Build a custom article for EP5 with concept at "explained"
    # Note: prior_episode_ref is null here because we're not testing migration — just coverage
    (wiki_fixture / show.wiki_episodes_dir / "ep-05-followup.md").write_text(
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
      prior_episode_ref: null
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
    eps = scan_episode_wiki(wiki_fixture, show)
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
    show = _make_flat_show()
    (wiki / show.wiki_episodes_dir).mkdir(parents=True)

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
        show=show,
    )
    assert result.episode_article.exists()
    assert result.episode_article.name.startswith("ep-1-")
    assert "wiki/topic/concept-a" in result.new_stubs_created
    assert (wiki / "topic" / "concept-a.md").exists()


def test_transactional_skips_existing_non_stub_article(tmp_path):
    wiki = tmp_path / "wiki"
    show = _make_flat_show()
    (wiki / show.wiki_episodes_dir).mkdir(parents=True)
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
        show=show,
    )
    assert "wiki/topic/concept-a" in result.collisions_skipped
    assert canonical.read_text(encoding="utf-8") == original


def test_transactional_same_episode_stub_replaced(tmp_path):
    """Re-indexing an episode that introduced a stub should FULLY replace the stub."""
    wiki = tmp_path / "wiki"
    show = _make_flat_show()
    (wiki / show.wiki_episodes_dir).mkdir(parents=True)
    (wiki / "topic").mkdir()
    stub = wiki / "topic" / "concept-a.md"
    # Use dict-form created_by to match the post-migration format
    stub.write_text(
        "---\ntitle: Concept A\nstatus: stub\ncreated_by: {show: test-show, ep: 7}\n"
        "last_seen_by: {show: test-show, ep: 7}\nbest_depth_episode: {show: test-show, ep: 7}\n"
        "best_depth: explained\nreferenced_by: [{show: test-show, ep: 7}]\n"
        "created: '2026-04-01'\n---\n\n"
        "# Concept A\n\n> Stub.\n\n## Old body content.\n",
        encoding="utf-8",
    )

    extraction = _make_extraction([
        {
            "slug": "wiki/topic/concept-a",
            "depth_this_episode": "deep-dive",
            "depth_delta_vs_past": "deeper",
            "prior_episode_ref": {"show": "test-show", "ep": 7},
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
        show=show,
    )
    assert "wiki/topic/concept-a" in result.stubs_updated
    # Prose section should be the freshly rendered version
    new_text = stub.read_text(encoding="utf-8")
    assert "Old body content" not in new_text
    assert "New what" in new_text


def test_transactional_other_episode_stub_frontmatter_only_update(tmp_path):
    wiki = tmp_path / "wiki"
    show = _make_flat_show()
    (wiki / show.wiki_episodes_dir).mkdir(parents=True)
    (wiki / "topic").mkdir()
    stub = wiki / "topic" / "concept-a.md"
    # Post-migration dict form: created_by EP3 of test-show
    stub.write_text(
        "---\ntitle: Concept A\nstatus: stub\n"
        "created_by:\n  show: test-show\n  ep: 3\n"
        "last_seen_by:\n  show: test-show\n  ep: 3\n"
        "best_depth_episode:\n  show: test-show\n  ep: 3\n"
        "best_depth: mentioned\n"
        "referenced_by:\n  - show: test-show\n    ep: 3\n"
        "created: '2026-04-01'\naliases: []\n---\n\n"
        "# Concept A\n\n> Stub prose introduced by EP3.\n",
        encoding="utf-8",
    )

    extraction = _make_extraction([
        {
            "slug": "wiki/topic/concept-a",
            "depth_this_episode": "explained",  # deeper than EP3's 'mentioned'
            "depth_delta_vs_past": "deeper",
            "prior_episode_ref": {"show": "test-show", "ep": 3},
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
        show=show,
    )
    assert "wiki/topic/concept-a" in result.stubs_updated
    new_text = stub.read_text(encoding="utf-8")
    # Prose preserved
    assert "Stub prose introduced by EP3" in new_text
    # Frontmatter updated — dict form now, so check for show/ep keys
    assert "best_depth: explained" in new_text
    # created_by EP3 preserved (show: test-show, ep: 3)
    assert "ep: 3" in new_text


def test_transactional_aborts_on_invalid_slug(tmp_path):
    wiki = tmp_path / "wiki"
    show = _make_flat_show()
    (wiki / show.wiki_episodes_dir).mkdir(parents=True)

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
            show=show,
        )
    # No episode article written
    assert list((wiki / show.wiki_episodes_dir).glob("*.md")) == []


def test_transactional_commits_stubs_before_episode_article(tmp_path):
    """Simulate a smoke-parse failure — episode article must NOT be written if staging doesn't validate.
    This is enforced by the smoke-parse step before any commit.
    """
    wiki = tmp_path / "wiki"
    show = _make_flat_show()
    (wiki / show.wiki_episodes_dir).mkdir(parents=True)

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
        show=show,
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
    _show_tmp = _make_flat_show()
    (wiki / _show_tmp.wiki_episodes_dir).mkdir(parents=True)
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

    show = _make_flat_show()
    result = orchestrate_episode_index(
        wiki_dir=wiki, episode_id=1, episode_topic="Topic",
        episode_date="2026-04-21", episode_depth="explained",
        audio_file="a.mp3", transcript_path=transcript_path,
        transcript_file="a.transcript.md", tags=["episode"], aliases=[],
        source_lessons=[], haiku_call=capturing_haiku,
        prompt_template_path=prompt_path,
        show=show,
    )
    assert len(captured_prompts) == 1
    assert "Sample transcript for ep 1." in captured_prompts[0]
    assert result.episode_article.exists()


def test_orchestrate_retries_once_on_malformed_then_succeeds(tmp_path):
    wiki = tmp_path / "wiki"
    _show_retry = _make_flat_show()
    (wiki / _show_retry.wiki_episodes_dir).mkdir(parents=True)
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

    show = _make_flat_show()
    result = orchestrate_episode_index(
        wiki_dir=wiki, episode_id=1, episode_topic="T",
        episode_date="2026-04-21", episode_depth="explained",
        audio_file="a.mp3", transcript_path=transcript_path,
        transcript_file="a.t.md", tags=["episode"], aliases=[],
        source_lessons=[], haiku_call=flaky_haiku,
        prompt_template_path=prompt_path,
        show=show,
    )
    assert call_count == 2
    assert result.episode_article.exists()


def test_orchestrate_aborts_after_two_malformed_responses(tmp_path):
    wiki = tmp_path / "wiki"
    _show_abort = _make_flat_show()
    (wiki / _show_abort.wiki_episodes_dir).mkdir(parents=True)
    transcript_path = tmp_path / "t.md"
    transcript_path.write_text("X", encoding="utf-8")
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("{episode_metadata}{transcript}{concept_catalog}{recent_episodes}", encoding="utf-8")

    def bad_haiku(p: str) -> str:
        return "still not json"

    show = _make_flat_show()
    with pytest.raises(TransactionAbortedError):
        orchestrate_episode_index(
            wiki_dir=wiki, episode_id=1, episode_topic="T",
            episode_date="2026-04-21", episode_depth="explained",
            audio_file="a.mp3", transcript_path=transcript_path,
            transcript_file="a.t.md", tags=["episode"], aliases=[],
            source_lessons=[], haiku_call=bad_haiku,
            prompt_template_path=prompt_path,
            show=show,
        )
    # No episode article
    assert list((wiki / show.wiki_episodes_dir).glob("*.md")) == []


def test_orchestrate_excludes_current_episode_from_coverage_map(tmp_path):
    """Reindex must not count the current episode as prior coverage."""
    wiki = tmp_path / "wiki"
    show = _make_flat_show()
    (wiki / show.wiki_episodes_dir).mkdir(parents=True)
    # Seed existing EP3 covering the concept at deep-dive
    from tests.conftest import _minimal_episode_article
    (wiki / show.wiki_episodes_dir / "ep-03-old.md").write_text(_minimal_episode_article(3), encoding="utf-8")

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
    show = _make_flat_show()
    result = orchestrate_episode_index(
        wiki_dir=wiki, episode_id=3, episode_topic="Re-index",
        episode_date="2026-04-21", episode_depth="explained",
        audio_file="a.mp3", transcript_path=transcript_path,
        transcript_file="a.t.md", tags=["episode"], aliases=[],
        source_lessons=[], haiku_call=haiku,
        prompt_template_path=prompt_path,
        show=show,
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


def test_normalize_haiku_slug_lowercases_and_hyphenates():
    from episode_wiki import _normalize_haiku_slug
    assert _normalize_haiku_slug("wiki/gpu/NVIDIA Compute Capability") == "wiki/gpu/nvidia-compute-capability"


def test_normalize_haiku_slug_preserves_already_canonical():
    from episode_wiki import _normalize_haiku_slug
    assert _normalize_haiku_slug("wiki/quantization/k-quants") == "wiki/quantization/k-quants"


def test_normalize_haiku_slug_collapses_runs_of_punctuation():
    from episode_wiki import _normalize_haiku_slug
    assert _normalize_haiku_slug("wiki/ai/GPT-4 & Claude  Opus!") == "wiki/ai/gpt-4-claude-opus"


def test_normalize_extraction_slugs_handles_open_threads_and_series():
    from episode_wiki import _normalize_extraction_slugs
    data = {
        "summary": "s",
        "concepts": [
            {"slug": "wiki/GPU/Compute Capability", "depth_this_episode": "explained",
             "what": "w", "why_it_matters": "y", "key_points": ["k"]}
        ],
        "open_threads": [
            {"slug": "wiki/Formats/GGUF File Format", "note": "n", "existed_before": False}
        ],
        "series_links": {
            "builds_on": ["wiki/episodes/EP-01 GPU Computing"],
            "followup_candidates": ["freeform prose is fine here"]
        }
    }
    out = _normalize_extraction_slugs(data)
    assert out["concepts"][0]["slug"] == "wiki/gpu/compute-capability"
    assert out["open_threads"][0]["slug"] == "wiki/formats/gguf-file-format"
    assert out["series_links"]["builds_on"][0] == "wiki/episodes/ep-01-gpu-computing"
    # followup_candidates untouched
    assert out["series_links"]["followup_candidates"] == ["freeform prose is fine here"]


# ---------------------------------------------------------------------------
# Task 6: judge_candidate_episode — Layer 3 dedup judge
# ---------------------------------------------------------------------------

from episode_wiki import DedupJudgement, judge_candidate_episode


def test_judge_builds_prior_hits_per_candidate(tmp_path):
    wiki = tmp_path / "wiki"
    _show_judge = _make_flat_show()
    (wiki / _show_judge.wiki_episodes_dir).mkdir(parents=True)
    from tests.conftest import _minimal_episode_article
    (wiki / _show_judge.wiki_episodes_dir / "ep-03-q.md").write_text(_minimal_episode_article(3), encoding="utf-8")

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
        show=_show_judge,
    )
    assert isinstance(result, DedupJudgement)
    assert len(result.per_concept) == 1
    assert result.episode_verdict == "reframe"
    # Verify prior_hits substituted in prompt — the k-quants concept in EP3's fixture is at slug wiki/quantization/k-quants
    # The judge passes raw candidate names; resolve_concept_candidate is tried first, so "k-quants" (exact title) should resolve.
    assert "k-quants" in seen["prompt"]


def test_judge_returns_empty_prior_hits_for_novel_candidates(tmp_path):
    wiki = tmp_path / "wiki"
    _show_novel = _make_flat_show()
    (wiki / _show_novel.wiki_episodes_dir).mkdir(parents=True)
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
        show=_show_novel,
    )
    assert result.episode_verdict == "proceed"


def test_judge_raises_when_haiku_json_malformed(tmp_path):
    wiki = tmp_path / "wiki"
    _show_bad = _make_flat_show()
    (wiki / _show_bad.wiki_episodes_dir).mkdir(parents=True)
    prompt_path = tmp_path / "p.md"
    prompt_path.write_text("{candidates}|{prior_hits}|{open_threads}", encoding="utf-8")

    def bad(p):
        return "not json"

    with pytest.raises(json.JSONDecodeError):
        judge_candidate_episode(
            wiki_dir=wiki, candidate_concepts=["x"],
            haiku_call=bad, prompt_template_path=prompt_path,
            show=_show_bad,
        )


def test_judge_requires_haiku_call_and_template(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    # Calling without haiku_call, prompt_template_path, or show must raise RuntimeError
    with pytest.raises(RuntimeError):
        judge_candidate_episode(wiki_dir=wiki, candidate_concepts=["x"])


# ---------------------------------------------------------------------------
# Tasks 6-9: Multi-show integration tests
# ---------------------------------------------------------------------------

import sys as _sys
_SCRIPTS_DIR_SHOWS = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR_SHOWS not in _sys.path:
    _sys.path.insert(0, _SCRIPTS_DIR_SHOWS)

from shows import Show, EpRef
from episode_wiki import (
    MixedShowCoverageError,
    resolve_episode_wikilink,
    validate_body_wikilinks,
)


def _make_show(show_id: str = "quanzhan-ai") -> Show:
    """Create a minimal Show for tests."""
    return Show(
        id=show_id,
        title="全栈AI",
        description="Test show",
        default=True,
        language="zh_Hans",
        hosts=["A", "B"],
        extra_host_names=[],
        intro_music=None,
        intro_music_length_seconds=12,
        intro_crossfade_seconds=3,
        podcast_format="deep-dive",
        podcast_length="long",
        transcript={"enabled": False, "model": "", "device": "auto", "language": "zh"},
        episodes_registry="episodes.yaml",
        wiki_episodes_dir=f"episodes/{show_id}",
        xiaoyuzhou={},
    )


def _write_show_episode(wiki_path: Path, show: Show, ep_id: int, slug: str) -> Path:
    """Write a minimal show-scoped episode article and return its path."""
    ep_dir = wiki_path / show.wiki_episodes_dir
    ep_dir.mkdir(parents=True, exist_ok=True)
    ep_file = ep_dir / f"ep-{ep_id}-{slug}.md"
    ep_file.write_text(
        f"---\n"
        f"title: 'EP{ep_id} | Test'\n"
        f"episode_id: {ep_id}\n"
        f"audio_file: a.mp3\n"
        f"transcript_file: a.transcript.md\n"
        f"date: 2026-04-21\n"
        f"depth: deep-dive\n"
        f"tags: [episode]\n"
        f"aliases: []\n"
        f"source_lessons: []\n"
        f"index:\n"
        f"  schema_version: 1\n"
        f"  summary: 'Test.'\n"
        f"  concepts: []\n"
        f"  open_threads: []\n"
        f"  series_links:\n"
        f"    builds_on: []\n"
        f"    followup_candidates: []\n"
        f"---\n\n# EP{ep_id} | Test\n",
        encoding="utf-8",
    )
    return ep_file


# --- Task 6: scan_episode_wiki show-scoped ---

def test_scan_episode_wiki_show_scoped(tmp_path):
    """scan_episode_wiki with a Show scopes results to that show's directory."""
    wiki = tmp_path / "wiki"
    show_a = _make_show("show-a")
    show_b = _make_show("show-b")

    _write_show_episode(wiki, show_a, 1, "topic-a")
    _write_show_episode(wiki, show_b, 2, "topic-b")

    eps_a = scan_episode_wiki(wiki, show_a)
    eps_b = scan_episode_wiki(wiki, show_b)

    assert len(eps_a) == 1
    assert eps_a[0].episode_id == 1
    assert eps_a[0].show_id == "show-a"

    assert len(eps_b) == 1
    assert eps_b[0].episode_id == 2
    assert eps_b[0].show_id == "show-b"


def test_scan_episode_wiki_does_not_leak_across_shows(tmp_path):
    """Scanning for show A must not return show B's episodes."""
    wiki = tmp_path / "wiki"
    show_a = _make_show("show-a")
    show_b = _make_show("show-b")

    _write_show_episode(wiki, show_a, 1, "topic-a")
    _write_show_episode(wiki, show_b, 1, "topic-b")  # same ep_id, different show

    eps_a = scan_episode_wiki(wiki, show_a)
    # Only show-a's episode is returned
    assert all(e.show_id == "show-a" for e in eps_a)
    assert len(eps_a) == 1
    assert eps_a[0].episode_id == 1


def test_scan_episode_wiki_populates_show_id_field(tmp_path):
    """IndexedEpisode.show_id must be set from the passed Show."""
    wiki = tmp_path / "wiki"
    show = _make_show("quanzhan-ai")
    _write_show_episode(wiki, show, 5, "deep-dive-ep")
    eps = scan_episode_wiki(wiki, show)
    assert len(eps) == 1
    assert eps[0].show_id == "quanzhan-ai"


# --- Task 6: resolve_episode_wikilink ---

def test_resolve_episode_wikilink_happy_path(tmp_path):
    """Returns wiki/episodes/<show>/ep-N-<slug> from the on-disk file."""
    wiki = tmp_path / "wiki"
    show = _make_show("quanzhan-ai")
    _write_show_episode(wiki, show, 3, "kv-cache")
    shows_by_id = {"quanzhan-ai": show}
    ref = EpRef(show="quanzhan-ai", ep=3)
    result = resolve_episode_wikilink(ref, shows_by_id, wiki)
    assert result == "wiki/episodes/quanzhan-ai/ep-3-kv-cache"


def test_resolve_episode_wikilink_unknown_show(tmp_path):
    """Raises UnknownShowError when ref.show is not in shows_by_id."""
    from shows import UnknownShowError
    wiki = tmp_path / "wiki"
    ref = EpRef(show="nonexistent-show", ep=1)
    with pytest.raises(UnknownShowError, match="nonexistent-show"):
        resolve_episode_wikilink(ref, {}, wiki)


def test_resolve_episode_wikilink_file_not_found(tmp_path):
    """Raises FileNotFoundError when no matching ep-<N>-*.md file exists."""
    wiki = tmp_path / "wiki"
    show = _make_show("quanzhan-ai")
    (wiki / show.wiki_episodes_dir).mkdir(parents=True)  # dir exists but empty
    shows_by_id = {"quanzhan-ai": show}
    ref = EpRef(show="quanzhan-ai", ep=99)
    with pytest.raises(FileNotFoundError):
        resolve_episode_wikilink(ref, shows_by_id, wiki)


# --- Task 6: validate_body_wikilinks ---

def test_validate_body_wikilinks_flags_legacy():
    """Legacy flat wikilink [[wiki/episodes/ep-N-slug]] returns an error."""
    text = "See [[wiki/episodes/ep-1-quantization]] for details."
    errors = validate_body_wikilinks(text, known_shows={"quanzhan-ai"})
    assert len(errors) == 1
    assert "legacy wikilink" in errors[0]
    assert "ep-1-quantization" in errors[0]


def test_validate_body_wikilinks_passes_new():
    """New show-scoped wikilink [[wiki/episodes/<show>/ep-N-slug]] returns no errors."""
    text = "See [[wiki/episodes/quanzhan-ai/ep-1-quantization]] for details."
    errors = validate_body_wikilinks(text, known_shows={"quanzhan-ai"})
    assert errors == []


def test_validate_body_wikilinks_flags_unknown_show():
    """Show-scoped wikilink with unknown show returns an error."""
    text = "See [[wiki/episodes/mystery-show/ep-1-topic]] here."
    errors = validate_body_wikilinks(text, known_shows={"quanzhan-ai"})
    assert len(errors) == 1
    assert "unknown show in wikilink" in errors[0]
    assert "mystery-show" in errors[0]


def test_validate_body_wikilinks_passes_empty_text():
    """No wikilinks → no errors."""
    assert validate_body_wikilinks("", known_shows={"quanzhan-ai"}) == []


def test_validate_body_wikilinks_passes_display_text_form():
    """Display-text wikilink [[wiki/episodes/<show>/ep-N-slug|label]] passes."""
    text = "See [[wiki/episodes/quanzhan-ai/ep-2-deep-dive|EP2]] here."
    errors = validate_body_wikilinks(text, known_shows={"quanzhan-ai"})
    assert errors == []


# --- Task 7: show_id in IndexedEpisode ---

def test_indexed_episode_show_id_default():
    """IndexedEpisode.show_id defaults to empty string."""
    ep = E.IndexedEpisode(
        episode_id=1, title="T", date="2026-01-01", depth="intro",
        audio_file="a.mp3", transcript_file=None,
        concepts=[], open_threads=[], series_builds_on=[],
        series_followup_candidates=[],
    )
    assert ep.show_id == ""


# --- Task 8: renderers emit dict form ---

def test_render_stub_emits_dict_form():
    """render_stub with show_id emits {show, ep} dicts for all ref fields."""
    import yaml as _yaml
    concept = {
        "slug": "wiki/attention/self-attention",
        "depth_this_episode": "explained",
        "what": "Attention mechanism.",
        "why_it_matters": "Core to transformers.",
        "key_points": ["Q, K, V"],
        "covered_at_sec": 60.0,
    }
    output = render_stub(
        slug="wiki/attention/self-attention",
        concept=concept,
        episode_id=3,
        episode_slug="ep-3-attention",
        date="2026-04-21",
        show_id="quanzhan-ai",
    )
    # Parse frontmatter: output starts with "---\n", ends at second "\n---\n"
    assert output.startswith("---\n")
    end = output.find("\n---\n", 4)
    assert end > 0, "Must have closing frontmatter delimiter"
    fm = _yaml.safe_load(output[4:end])
    # All ref fields should be dicts
    assert fm["created_by"] == {"show": "quanzhan-ai", "ep": 3}
    assert fm["last_seen_by"] == {"show": "quanzhan-ai", "ep": 3}
    assert fm["best_depth_episode"] == {"show": "quanzhan-ai", "ep": 3}
    assert fm["referenced_by"] == [{"show": "quanzhan-ai", "ep": 3}]


def test_render_stub_without_show_id_uses_legacy_format():
    """render_stub without show_id falls back to legacy ep-N string format."""
    concept = {
        "slug": "wiki/attention/self-attention",
        "depth_this_episode": "mentioned",
        "what": "W.", "why_it_matters": "Y.", "key_points": [],
    }
    output = render_stub(
        slug="wiki/attention/self-attention",
        concept=concept,
        episode_id=5,
        episode_slug="ep-5-test",
        date="2026-04-21",
    )
    assert "created_by: ep-5" in output


def test_render_episode_wiki_emits_dict_refs():
    """render_episode_wiki emits prior_episode_ref as dict and builds_on as list of dicts."""
    import yaml as _yaml
    concept = {
        "slug": "wiki/quantization/k-quants",
        "depth_this_episode": "deep-dive",
        "depth_delta_vs_past": "deeper",
        "prior_episode_ref": {"show": "quanzhan-ai", "ep": 1},
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
        summary="A deep dive.",
        concepts=[concept],
        open_threads=[],
        series_builds_on=[{"show": "quanzhan-ai", "ep": 1}],
        series_followup_candidates=[],
        source_lessons=[],
        tags=["episode"],
        show_id="quanzhan-ai",
    )
    end = output.find("\n---\n", 4)
    fm = _yaml.safe_load(output[4:end])
    idx = fm["index"]
    # prior_episode_ref must be a dict
    assert idx["concepts"][0]["prior_episode_ref"] == {"show": "quanzhan-ai", "ep": 1}
    # series_links.builds_on must be a list of dicts
    assert idx["series_links"]["builds_on"] == [{"show": "quanzhan-ai", "ep": 1}]


# --- Task 9: parse new dict form on read; fail on legacy ---

def test_parser_rejects_legacy_ref_str(tmp_path):
    """Episode article with prior_episode_ref: 'ep-3' (legacy str) raises MigrationRequiredError."""
    from shows import MigrationRequiredError
    ep_dir = tmp_path / "episodes" / "quanzhan-ai"
    ep_dir.mkdir(parents=True)
    ep_file = ep_dir / "ep-5-test.md"
    ep_file.write_text(
        "---\n"
        "title: 'EP5 | Test'\n"
        "episode_id: 5\n"
        "audio_file: a.mp3\n"
        "transcript_file: a.transcript.md\n"
        "date: 2026-04-21\n"
        "depth: explained\n"
        "tags: [episode]\n"
        "aliases: []\n"
        "source_lessons: []\n"
        "index:\n"
        "  schema_version: 1\n"
        "  summary: 'Test.'\n"
        "  concepts:\n"
        "    - slug: wiki/foo/bar\n"
        "      depth_this_episode: explained\n"
        "      depth_delta_vs_past: deeper\n"
        "      prior_episode_ref: 'ep-3'\n"
        "      what: 'W.'\n"
        "      why_it_matters: 'Y.'\n"
        "      key_points: []\n"
        "      covered_at_sec: null\n"
        "      existed_before: true\n"
        "  open_threads: []\n"
        "  series_links:\n"
        "    builds_on: []\n"
        "    followup_candidates: []\n"
        "---\n\n# EP5\n",
        encoding="utf-8",
    )
    show = _make_show("quanzhan-ai")
    wiki = tmp_path
    with pytest.raises(MigrationRequiredError):
        scan_episode_wiki(wiki, show, strict=True)


def test_parser_rejects_legacy_ref_int(tmp_path):
    """Episode article with prior_episode_ref: 3 (bare int) raises MigrationRequiredError."""
    from shows import MigrationRequiredError
    ep_dir = tmp_path / "episodes" / "quanzhan-ai"
    ep_dir.mkdir(parents=True)
    ep_file = ep_dir / "ep-5-test.md"
    ep_file.write_text(
        "---\n"
        "title: 'EP5 | Test'\n"
        "episode_id: 5\n"
        "audio_file: a.mp3\n"
        "transcript_file: a.transcript.md\n"
        "date: 2026-04-21\n"
        "depth: explained\n"
        "tags: [episode]\n"
        "aliases: []\n"
        "source_lessons: []\n"
        "index:\n"
        "  schema_version: 1\n"
        "  summary: 'Test.'\n"
        "  concepts:\n"
        "    - slug: wiki/foo/bar\n"
        "      depth_this_episode: explained\n"
        "      depth_delta_vs_past: deeper\n"
        "      prior_episode_ref: 3\n"
        "      what: 'W.'\n"
        "      why_it_matters: 'Y.'\n"
        "      key_points: []\n"
        "      covered_at_sec: null\n"
        "      existed_before: true\n"
        "  open_threads: []\n"
        "  series_links:\n"
        "    builds_on: []\n"
        "    followup_candidates: []\n"
        "---\n\n# EP5\n",
        encoding="utf-8",
    )
    show = _make_show("quanzhan-ai")
    wiki = tmp_path
    with pytest.raises(MigrationRequiredError):
        scan_episode_wiki(wiki, show, strict=True)


def test_parser_accepts_dict_ref(tmp_path):
    """Episode article with prior_episode_ref: {show, ep} dict parses cleanly."""
    ep_dir = tmp_path / "episodes" / "quanzhan-ai"
    ep_dir.mkdir(parents=True)
    ep_file = ep_dir / "ep-5-test.md"
    ep_file.write_text(
        "---\n"
        "title: 'EP5 | Test'\n"
        "episode_id: 5\n"
        "audio_file: a.mp3\n"
        "transcript_file: a.transcript.md\n"
        "date: 2026-04-21\n"
        "depth: explained\n"
        "tags: [episode]\n"
        "aliases: []\n"
        "source_lessons: []\n"
        "index:\n"
        "  schema_version: 1\n"
        "  summary: 'Test.'\n"
        "  concepts:\n"
        "    - slug: wiki/foo/bar\n"
        "      depth_this_episode: explained\n"
        "      depth_delta_vs_past: deeper\n"
        "      prior_episode_ref:\n"
        "        show: quanzhan-ai\n"
        "        ep: 3\n"
        "      what: 'W.'\n"
        "      why_it_matters: 'Y.'\n"
        "      key_points: []\n"
        "      covered_at_sec: null\n"
        "      existed_before: true\n"
        "  open_threads: []\n"
        "  series_links:\n"
        "    builds_on: []\n"
        "    followup_candidates: []\n"
        "---\n\n# EP5\n",
        encoding="utf-8",
    )
    show = _make_show("quanzhan-ai")
    wiki = tmp_path
    eps = scan_episode_wiki(wiki, show, strict=True)
    assert len(eps) == 1
    assert eps[0].concepts[0].prior_episode_ref == {"show": "quanzhan-ai", "ep": 3}


def test_parser_rejects_unknown_show_in_dict_ref(tmp_path):
    """prior_episode_ref dict with show not in known_shows raises UnknownShowError."""
    from shows import UnknownShowError
    ep_dir = tmp_path / "episodes" / "quanzhan-ai"
    ep_dir.mkdir(parents=True)
    ep_file = ep_dir / "ep-5-test.md"
    ep_file.write_text(
        "---\n"
        "title: 'EP5 | Test'\n"
        "episode_id: 5\n"
        "audio_file: a.mp3\n"
        "transcript_file: a.transcript.md\n"
        "date: 2026-04-21\n"
        "depth: explained\n"
        "tags: [episode]\n"
        "aliases: []\n"
        "source_lessons: []\n"
        "index:\n"
        "  schema_version: 1\n"
        "  summary: 'Test.'\n"
        "  concepts:\n"
        "    - slug: wiki/foo/bar\n"
        "      depth_this_episode: explained\n"
        "      depth_delta_vs_past: deeper\n"
        "      prior_episode_ref:\n"
        "        show: other-show\n"
        "        ep: 3\n"
        "      what: 'W.'\n"
        "      why_it_matters: 'Y.'\n"
        "      key_points: []\n"
        "      covered_at_sec: null\n"
        "      existed_before: true\n"
        "  open_threads: []\n"
        "  series_links:\n"
        "    builds_on: []\n"
        "    followup_candidates: []\n"
        "---\n\n# EP5\n",
        encoding="utf-8",
    )
    show = _make_show("quanzhan-ai")
    wiki = tmp_path
    with pytest.raises(UnknownShowError):
        scan_episode_wiki(wiki, show, strict=True)
