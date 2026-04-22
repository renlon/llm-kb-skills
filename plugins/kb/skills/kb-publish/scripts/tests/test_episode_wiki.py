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
