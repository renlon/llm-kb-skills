"""Shared pytest fixtures for kb-publish episode-index tests."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _minimal_episode_article(ep_id: int) -> str:
    return f"""---
title: "EP{ep_id} | Test"
episode_id: {ep_id}
audio_file: podcast-test.mp3
transcript_file: podcast-test.transcript.md
date: 2026-04-21
depth: deep-dive
tags: [episode, test]
aliases: []
source_lessons: []
index:
  schema_version: 1
  summary: "Test episode."
  concepts:
    - slug: wiki/quantization/k-quants
      depth_this_episode: deep-dive
      depth_delta_vs_past: new
      prior_episode_ref: null
      what: "Group-wise quant."
      why_it_matters: "Enables 4-bit inference."
      key_points: ["Groups into blocks"]
      covered_at_sec: 100.0
      existed_before: true
  open_threads: []
  series_links:
    builds_on: []
    followup_candidates: []
---

# EP{ep_id} | Test

Body.
"""


_FIXTURE_SHOW_ID = "test-show"


@pytest.fixture
def wiki_fixture(tmp_path: Path) -> Path:
    """A small realistic wiki directory with a mix of real articles, stubs, and episode records.

    Episodes are stored under episodes/test-show/ (show-scoped layout) to match
    the Show invariant (wiki_episodes_dir == 'episodes/{show.id}').
    Use wiki_fixture_show() to get the matching Show object in tests that call
    scan_episode_wiki or other Show-aware functions.
    """
    wiki = tmp_path / "wiki"
    wiki.mkdir()

    # Real concept article
    (wiki / "attention").mkdir()
    (wiki / "attention" / "flash-attention.md").write_text(
        "---\ntitle: Flash Attention\ntags: [attention, optimization]\naliases: [FlashAttention, flash-attention]\n"
        "status: complete\n---\n\n# Flash Attention\n\nTiled attention kernel...\n",
        encoding="utf-8",
    )

    # Stub article
    (wiki / "quantization").mkdir()
    (wiki / "quantization" / "k-quants.md").write_text(
        "---\ntitle: K-Quants\ntags: [stub, quantization]\naliases: []\n"
        "status: stub\ncreated_by: ep-3\nlast_seen_by: ep-3\nbest_depth_episode: ep-3\n"
        "best_depth: deep-dive\nreferenced_by: [ep-3]\ncreated: '2026-04-21'\n---\n\n"
        "# K-Quants\n\n> Stub.\n",
        encoding="utf-8",
    )

    # Episode article — stored under show-scoped subdir
    (wiki / "episodes" / _FIXTURE_SHOW_ID).mkdir(parents=True)
    (wiki / "episodes" / _FIXTURE_SHOW_ID / "ep-03-quantization.md").write_text(
        _minimal_episode_article(3), encoding="utf-8"
    )

    # Non-episode markdown that must be ignored by scan_episode_wiki
    (wiki / "README.md").write_text("# Wiki\n", encoding="utf-8")

    return wiki


@pytest.fixture
def sample_concept() -> dict[str, Any]:
    """A minimal valid extracted concept dict (as if from Haiku after validation)."""
    return {
        "slug": "wiki/new-topic/novel-concept",
        "depth_this_episode": "explained",
        "depth_delta_vs_past": "new",
        "prior_episode_ref": None,
        "what": "A concept.",
        "why_it_matters": "It matters.",
        "key_points": ["Claim one."],
        "covered_at_sec": 42.0,
        "existed_before": False,
    }


@pytest.fixture
def sample_extraction() -> dict[str, Any]:
    """A minimal valid extraction JSON dict (post-validation, post-depth-delta-compute)."""
    return {
        "summary": "Test summary.",
        "concepts": [
            {
                "slug": "wiki/new-topic/novel-concept",
                "depth_this_episode": "explained",
                "depth_delta_vs_past": "new",
                "prior_episode_ref": None,
                "what": "A concept.",
                "why_it_matters": "It matters.",
                "key_points": ["Claim one."],
                "covered_at_sec": 42.0,
                "existed_before": False,
            }
        ],
        "open_threads": [],
        "series_links": {"builds_on": [], "followup_candidates": []},
    }
