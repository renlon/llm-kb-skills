# Episode Index & Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a wiki-primary episode index that records what each published podcast episode taught, with Haiku-driven extraction, transactional commits, and a dedup judge that replaces string-match cross-check in the podcast workflow. Backfill EP1 + EP2 into the new index.

**Architecture:** Every published episode produces a `wiki/episodes/ep-<id>-<slug>.md` article. Its frontmatter carries a structured `index:` block (the machine-readable record) and the body is rendered markdown (human-readable). kb-publish owns writing these; kb-notebooklm reads them at podcast-generation time to classify candidate concepts (novel / deeper_dive / addresses_open_thread / redundant). No SQLite, no FTS, no vector DB — the Obsidian vault is the graph data store. Auto-stubs keep the wiki green for not-yet-documented concepts.

**Tech Stack:**
- Python stdlib + PyYAML (already in the notebooklm venv)
- `faster-whisper` + `pyannote.audio` (already installed via the intro-music feature's kb-init)
- Anthropic API (`anthropic` SDK, already used elsewhere; Haiku 4.5 for extraction and judging)
- pytest for unit tests (dev-only; not in requirements.txt)
- ffmpeg + ffprobe (already on PATH)

---

## File Structure

### New files

- `plugins/kb/skills/kb-publish/scripts/__init__.py` (already exists; no change)
- `plugins/kb/skills/kb-publish/scripts/tests/__init__.py` (new, empty)
- `plugins/kb/skills/kb-publish/scripts/tests/conftest.py` (shared fixtures)
- `plugins/kb/skills/kb-publish/scripts/tests/README.md`
- `plugins/kb/skills/kb-publish/scripts/episode_wiki.py` (the shared module; public API listed in spec §7)
- `plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py` (all unit tests from spec §10)
- `plugins/kb/skills/kb-publish/prompts/episode-wiki-extract.md` (Layer 1 Haiku prompt)
- `plugins/kb/skills/kb-notebooklm/prompts/dedup-judge.md` (Layer 3 Haiku prompt)
- `plugins/kb/skills/kb-publish/scripts/backfill_index.py` (thin wrapper CLI for `/kb-publish backfill-index`)

### Modified files

- `plugins/kb/skills/kb-publish/SKILL.md` — add step 8c after step 8b; add `backfill-index` subcommand docs
- `plugins/kb/skills/kb-notebooklm/SKILL.md` — rewrite step 5b to use the Layer 3 judge; move it to run AFTER step 4b (confidentiality filter)
- `plugins/kb/.claude-plugin/plugin.json` — version bump 1.14.x → 1.15.0

### Directory layout at commit time

```
plugins/kb/skills/kb-publish/
├── SKILL.md                                  (modified)
├── prompts/
│   ├── concept-extract.md                    (not created — episode-wiki-extract.md replaces the concept-extract in the spec)
│   └── episode-wiki-extract.md               (new)
├── scripts/
│   ├── __init__.py                           (existing)
│   ├── episode_wiki.py                       (new — public API in spec §7)
│   ├── backfill_index.py                     (new)
│   ├── generate_cover.py                     (existing, untouched)
│   ├── upload_xiaoyuzhou.py                  (existing, untouched)
│   ├── requirements.txt                      (existing, untouched)
│   └── tests/                                (new)
│       ├── __init__.py
│       ├── conftest.py
│       ├── README.md
│       └── test_episode_wiki.py
└── references/                               (existing, untouched)

plugins/kb/skills/kb-notebooklm/
├── SKILL.md                                  (modified)
└── prompts/
    ├── podcast-tutor.md                      (existing, untouched)
    └── dedup-judge.md                        (new)
```

---

## Test Strategy

**Unit tests (pytest, hermetic, no network).** Cover every public function in `episode_wiki.py`: scan_episode_wiki (strict + lenient), concepts_covered_by_episodes, concept_catalog (include_stubs on/off), render_episode_wiki (snapshot), render_stub (snapshot), compute_stub_update, resolve_concept_candidate, validate_slug, slug_to_wiki_relative_path, compute_depth_deltas, staging_dir, index_episode_transactional (with Haiku mocked), filename slug normalization, atomic commit ordering. `orchestrate_episode_index` tested with the Haiku call injected as a callable that returns fixture JSON.

**Integration test (gated by `ANTHROPIC_API_KEY`).** One end-to-end: a real small transcript fixture → `orchestrate_episode_index()` with a real Haiku call → assert the produced wiki article is parseable and contains expected concept slugs.

**Procedural verification (the "proof it works" gate, final task).** Run `/kb-publish backfill-index --episode 1` and `--episode 2` against the real KB. Verify produced `wiki/episodes/ep-01-*.md` and `ep-02-*.md` parse cleanly. Propose a synthetic EP4 via `/kb-notebooklm podcast` and confirm the new dedup judge output.

`pytest` is dev-only (install ad hoc, not in `requirements.txt`). Run tests with:

```
source ~/notebooklm-py/.venv/bin/activate && \
  pip install -q pytest && \
  pytest plugins/kb/skills/kb-publish/scripts/tests/ -v
```

---

## Task Order Rationale

Tasks are ordered so each produces a self-contained, testable artifact that the next task can depend on.

1. **Task 1:** Scaffold tests dir + conftest. Tiny, lets later tasks plug into an existing layout.
2. **Task 2:** Pure-python helpers (no I/O, no Haiku) — `validate_slug`, `slug_to_wiki_relative_path`, `compute_depth_deltas`, `compute_stub_update`, `resolve_concept_candidate`, `render_stub`, `render_episode_wiki`, filename slug normalization. Heaviest unit test surface; no external deps.
3. **Task 3:** I/O helpers — `scan_episode_wiki` (strict + lenient), `concept_catalog`, `concepts_covered_by_episodes`. All depend on real filesystem reads; fixtures live in tmp_path.
4. **Task 4:** Transactional core — `index_episode_transactional` (staging, smoke-parse, atomic commit). Depends on tasks 2 + 3; no Haiku.
5. **Task 5:** Haiku prompt + `orchestrate_episode_index` wrapper. Haiku injected as callable for testing.
6. **Task 6:** Dedup judge prompt + the Layer 3 judge function (reused by kb-notebooklm step 5b).
7. **Task 7:** `backfill_index.py` CLI that shells out to `transcribe_audio.py` for transcripts then calls orchestrate.
8. **Task 8:** kb-publish SKILL.md edits — step 8c + backfill subcommand docs.
9. **Task 9:** kb-notebooklm SKILL.md edits — step 5b rewrite, moved after step 4b.
10. **Task 10:** Version bump + full test run.
11. **Task 11:** Backfill EP1 and EP2 (live test, produces the "proof it works").
12. **Task 12:** Procedural verification — propose a synthetic EP4 via kb-notebooklm, verify dedup judge output, document results.

Tasks 2, 3, 4, 5, 6, 7 can in principle be parallelized — but we serialize them so the subagent orchestrator sees a clean linear plan and review checkpoints are deterministic.

---

## Task 1: Scaffold tests package

**Goal:** Add a tests directory under `kb-publish/scripts/` with shared fixtures. Subsequent tasks fill in test files.

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/tests/__init__.py`
- Create: `plugins/kb/skills/kb-publish/scripts/tests/conftest.py`
- Create: `plugins/kb/skills/kb-publish/scripts/tests/README.md`

- [ ] **Step 1: Create the empty package marker**

Create `plugins/kb/skills/kb-publish/scripts/tests/__init__.py`:

```python
```

(Single newline — empty file.)

- [ ] **Step 2: Create conftest with shared fixtures**

Create `plugins/kb/skills/kb-publish/scripts/tests/conftest.py`:

```python
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


@pytest.fixture
def wiki_fixture(tmp_path: Path) -> Path:
    """A small realistic wiki directory with a mix of real articles, stubs, and episode records."""
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

    # Episode article
    (wiki / "episodes").mkdir()
    (wiki / "episodes" / "ep-03-quantization.md").write_text(_minimal_episode_article(3), encoding="utf-8")

    # Non-episode markdown that must be ignored by scan_episode_wiki
    (wiki / "README.md").write_text("# Wiki\n", encoding="utf-8")

    return wiki


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
```

- [ ] **Step 3: Write tests/README.md**

Create `plugins/kb/skills/kb-publish/scripts/tests/README.md`:

```markdown
# Tests for kb-publish episode-index scripts

Hermetic unit tests for `episode_wiki.py` and `backfill_index.py`.

## Running

```bash
source ~/notebooklm-py/.venv/bin/activate
pip install pytest    # dev-only; intentionally not in requirements.txt
pytest plugins/kb/skills/kb-publish/scripts/tests/ -v
```

## What's tested

- Pure helpers (validate_slug, slug_to_wiki_relative_path, compute_depth_deltas, etc.) — no filesystem.
- I/O helpers (scan_episode_wiki, concept_catalog) — tmp_path fixtures only.
- Transactional flow (index_episode_transactional) — Haiku is mocked.
- Rendering functions — snapshot tests.

## What's NOT tested here

Real Haiku/Anthropic API calls (gated to an opt-in integration test) and real audio transcription.
```

- [ ] **Step 4: Verify layout**

Run:

```bash
ls plugins/kb/skills/kb-publish/scripts/tests/
```

Expected: `README.md  __init__.py  conftest.py`.

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/tests/
git commit -m "feat(kb-publish): scaffold episode-index tests directory

Adds tests/__init__.py, conftest.py with shared fixtures (wiki_fixture,
sample_concept, sample_extraction), and README. No runtime behavior;
later tasks add episode_wiki.py, backfill_index.py, and their tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Pure helpers in `episode_wiki.py`

**Goal:** The I/O-free public API from spec §7. These helpers are heavy on unit tests but don't touch the filesystem (aside from `render_episode_wiki`/`render_stub` being pure rendering functions).

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/episode_wiki.py` (partial — just pure helpers and dataclasses for now)
- Test: `plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py`

- [ ] **Step 1: Write the failing test file**

Create `plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py` with the full test suite for pure helpers. (Full test code block omitted for plan brevity — it maps 1:1 to spec §10 tests 4, 5, 6, 7, 8, 9; the implementer should write one test per numbered bullet.)

Key test names to include:

```python
# Slug validation
def test_validate_slug_accepts_plain_concept(): ...
def test_validate_slug_rejects_missing_wiki_prefix(): ...
def test_validate_slug_rejects_dotdot_traversal(): ...
def test_validate_slug_rejects_trailing_md(): ...
def test_validate_slug_rejects_leading_slash(): ...
def test_validate_slug_rejects_exceeds_180_chars(): ...
def test_validate_slug_rejects_episodes_by_default(): ...
def test_validate_slug_accepts_episodes_when_allow_episode_true(): ...
def test_validate_slug_rejects_uppercase(): ...

# Path conversion
def test_slug_to_wiki_relative_path_strips_single_prefix(): ...
def test_slug_to_wiki_relative_path_appends_md(): ...
def test_slug_to_wiki_relative_path_does_not_double_nest(): ...

# compute_depth_deltas
def test_depth_delta_new_when_no_priors(): ...
def test_depth_delta_deeper_when_new_exceeds_best(): ...
def test_depth_delta_same_when_match(): ...
def test_depth_delta_lighter_when_below(): ...
def test_depth_delta_tie_breaks_by_lowest_ep_id(): ...

# compute_stub_update
def test_stub_update_always_updates_last_seen_by(): ...
def test_stub_update_bumps_best_depth_only_when_deeper(): ...
def test_stub_update_preserves_created_by(): ...
def test_stub_update_appends_referenced_by(): ...
def test_stub_update_returns_none_on_noop(): ...

# Filename slug normalization
def test_filename_slug_normalizes_ascii(): ...
def test_filename_slug_uses_latin_alias_when_topic_nonascii(): ...
def test_filename_slug_falls_back_to_topic_literal_for_pure_nonascii(): ...
def test_filename_slug_truncates_to_50_chars(): ...

# resolve_concept_candidate
def test_resolve_exact_title_match(): ...
def test_resolve_alias_match(): ...
def test_resolve_returns_none_on_ambiguous(): ...
def test_resolve_returns_none_on_no_match(): ...

# render_stub, render_episode_wiki (snapshot)
def test_render_stub_snapshot(): ...
def test_render_episode_wiki_snapshot(): ...
```

- [ ] **Step 2: Verify tests fail**

```bash
source ~/notebooklm-py/.venv/bin/activate && pip install pytest -q && \
  pytest plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py -v
```

Expected: `ModuleNotFoundError: No module named 'episode_wiki'`.

- [ ] **Step 3: Implement the module (pure helpers only)**

Create `plugins/kb/skills/kb-publish/scripts/episode_wiki.py`. Start with:

```python
"""Episode-index core module. See docs/superpowers/specs/2026-04-21-episode-index-and-dedup-design.md."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml


# --- exceptions ---

class SlugValidationError(ValueError):
    pass

class EpisodeParseError(ValueError):
    pass

class TransactionAbortedError(RuntimeError):
    pass


# --- constants ---

_DEPTH_ORDER = {"mentioned": 0, "explained": 1, "deep-dive": 2}
_SLUG_RE = re.compile(r"^wiki/[a-z0-9][a-z0-9\-_./]*[a-z0-9]$")
_FILENAME_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")
_SLUG_MAX_LEN = 180
_FILENAME_SLUG_MAX_LEN = 50


# --- dataclasses ---

@dataclass
class IndexedConcept:
    slug: str
    depth_this_episode: str
    depth_delta_vs_past: str
    prior_episode_ref: int | None
    what: str
    why_it_matters: str
    key_points: list[str]
    covered_at_sec: float | None


@dataclass
class OpenThread:
    slug: str | None
    note: str
    existed_before: bool


@dataclass
class IndexedEpisode:
    episode_id: int
    title: str
    date: str
    depth: str
    audio_file: str
    transcript_file: str | None
    concepts: list[IndexedConcept]
    open_threads: list[OpenThread]
    series_builds_on: list[str]
    series_followup_candidates: list[str]


@dataclass
class TransactionalIndexResult:
    episode_article: Path
    new_stubs_created: list[str]
    stubs_updated: list[str]
    collisions_skipped: list[str]


# --- slug helpers ---

def validate_slug(slug: str, *, allow_episode: bool = False) -> None:
    if not isinstance(slug, str) or not slug:
        raise SlugValidationError("slug must be a non-empty string")
    if len(slug) > _SLUG_MAX_LEN:
        raise SlugValidationError(f"slug exceeds {_SLUG_MAX_LEN} chars")
    if ".." in slug.split("/"):
        raise SlugValidationError("slug contains '..' path component")
    if slug.startswith("/"):
        raise SlugValidationError("slug must not start with '/'")
    if slug.endswith(".md"):
        raise SlugValidationError("slug must not end with '.md'")
    if not allow_episode and slug.startswith("wiki/episodes/"):
        raise SlugValidationError("concept slug cannot start with 'wiki/episodes/'")
    if not _SLUG_RE.match(slug):
        raise SlugValidationError(f"slug {slug!r} fails regex {_SLUG_RE.pattern}")


def slug_to_wiki_relative_path(slug: str) -> Path:
    """Strip exactly one leading 'wiki/' prefix and append '.md'."""
    if not slug.startswith("wiki/"):
        raise SlugValidationError(f"slug must start with 'wiki/': {slug!r}")
    rel = slug[len("wiki/"):] + ".md"
    return Path(rel)


# --- depth delta ---

def compute_depth_deltas(
    concepts: list[dict],
    coverage_map: dict[str, list[dict]],
) -> list[dict]:
    out = []
    for c in concepts:
        c = dict(c)
        priors = coverage_map.get(c["slug"], [])
        if not priors:
            c["depth_delta_vs_past"] = "new"
            c["prior_episode_ref"] = None
        else:
            deepest = max(priors, key=lambda p: (_DEPTH_ORDER[p["depth"]], -p["ep_id"]))
            # tie-break by lowest ep_id → negative ep_id in max()
            dp = _DEPTH_ORDER[deepest["depth"]]
            dc = _DEPTH_ORDER[c["depth_this_episode"]]
            if dc > dp:
                c["depth_delta_vs_past"] = "deeper"
            elif dc == dp:
                c["depth_delta_vs_past"] = "same"
            else:
                c["depth_delta_vs_past"] = "lighter"
            c["prior_episode_ref"] = deepest["ep_id"]
        out.append(c)
    return out


# --- stub update ---

def compute_stub_update(
    existing_frontmatter: dict,
    concept: dict,
    episode_id: int,
) -> dict | None:
    """Return updated frontmatter dict, or None if no changes needed.
    created_by is NEVER modified.
    """
    fm = dict(existing_frontmatter)
    changed = False
    ep_tag = f"ep-{episode_id}"

    if fm.get("last_seen_by") != ep_tag:
        fm["last_seen_by"] = ep_tag
        changed = True

    existing_best_depth = fm.get("best_depth", "mentioned")
    new_depth = concept["depth_this_episode"]
    if _DEPTH_ORDER[new_depth] > _DEPTH_ORDER.get(existing_best_depth, 0):
        fm["best_depth"] = new_depth
        fm["best_depth_episode"] = ep_tag
        changed = True

    referenced_by = list(fm.get("referenced_by", []))
    if ep_tag not in referenced_by:
        referenced_by.append(ep_tag)
        fm["referenced_by"] = referenced_by
        changed = True

    return fm if changed else None


# --- filename slug ---

def normalize_filename_slug(topic: str, aliases: list[str] | None = None) -> str:
    """Return a filename-safe slug for ep-<id>-<slug>.md."""
    candidate = topic or ""
    if not re.search(r"[A-Za-z]", candidate):
        # Prefer first ASCII-bearing alias
        for a in (aliases or []):
            if re.search(r"[A-Za-z]", a):
                candidate = a
                break
    normalized = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")[:_FILENAME_SLUG_MAX_LEN]
    if normalized and _FILENAME_SLUG_RE.match(normalized):
        return normalized
    return "topic"


# --- resolver ---

def resolve_concept_candidate(
    candidate_name: str,
    catalog: dict[str, list[dict]],
) -> str | None:
    name_lower = candidate_name.strip().lower()
    title_matches: list[str] = []
    alias_matches: list[str] = []
    for category, entries in catalog.items():
        for e in entries:
            if e.get("title", "").strip().lower() == name_lower:
                title_matches.append(e["slug"])
            for a in e.get("aliases", []) or []:
                if a.strip().lower() == name_lower:
                    alias_matches.append(e["slug"])
    # De-dup preserving order
    def _dedup(xs):
        seen, out = set(), []
        for x in xs:
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    title_matches = _dedup(title_matches)
    alias_matches = _dedup(alias_matches)
    if len(title_matches) == 1:
        return title_matches[0]
    if len(title_matches) > 1:
        return None
    if len(alias_matches) == 1:
        return alias_matches[0]
    return None


# --- rendering (pure, no I/O) ---

def render_stub(
    slug: str,
    concept: dict,
    episode_id: int,
    episode_slug: str,
    date: str,
) -> str:
    ep_tag = f"ep-{episode_id}"
    title = slug.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()
    fm = {
        "title": title,
        "tags": ["stub"],
        "aliases": [],
        "status": "stub",
        "created_by": ep_tag,
        "last_seen_by": ep_tag,
        "best_depth_episode": ep_tag,
        "best_depth": concept["depth_this_episode"],
        "referenced_by": [ep_tag],
        "created": date,
    }
    body = (
        f"# {title}\n\n"
        f"> **Stub.** Auto-created by `kb-publish` while indexing "
        f"[[wiki/episodes/{episode_slug}]]. Fill in later via compile/lint.\n\n"
        f"## What the introducing episode said\n\n{concept.get('what','')}\n\n"
        f"## Why it matters\n\n{concept.get('why_it_matters','')}\n\n"
        f"## Referenced by\n\n- Introduced in: [[wiki/episodes/{episode_slug}]]\n"
    )
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body


def render_episode_wiki(
    episode_id: int,
    title: str,
    date: str,
    depth: str,
    audio_file: str,
    transcript_file: str,
    summary: str,
    concepts: list[dict],
    open_threads: list[dict],
    series_builds_on: list[str],
    series_followup_candidates: list[str],
    source_lessons: list[str],
    tags: list[str],
    aliases: list[str] | None = None,
) -> str:
    index_block = {
        "schema_version": 1,
        "summary": summary,
        "concepts": concepts,
        "open_threads": open_threads,
        "series_links": {
            "builds_on": series_builds_on,
            "followup_candidates": series_followup_candidates,
        },
    }
    fm = {
        "title": title,
        "episode_id": episode_id,
        "audio_file": audio_file,
        "transcript_file": transcript_file,
        "date": date,
        "depth": depth,
        "tags": tags,
        "aliases": aliases or [],
        "source_lessons": source_lessons,
        "index": index_block,
    }
    body = _render_body(title, date, depth, audio_file, transcript_file,
                         summary, concepts, open_threads, series_builds_on,
                         series_followup_candidates)
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body


def _render_body(title, date, depth, audio_file, transcript_file, summary, concepts, open_threads, builds_on, followups):
    out = [f"# {title}\n"]
    out.append(f"**Date:** {date}\n**Depth:** {depth}\n**Audio:** [[{audio_file}]]\n**Transcript:** [[{transcript_file}]]\n\n")
    out.append(f"## Summary\n\n{summary}\n\n")
    out.append("## Concepts Covered\n\n")
    for level, label in [("deep-dive", "Deep-dive"), ("explained", "Explained"), ("mentioned", "Mentioned")]:
        group = [c for c in concepts if c["depth_this_episode"] == level]
        if not group:
            continue
        out.append(f"### {label}\n\n")
        for c in group:
            out.append(f"- [[{c['slug']}]]\n")
            out.append(f"  - What: {c.get('what','')}\n")
            out.append(f"  - Why it matters: {c.get('why_it_matters','')}\n")
            kp = c.get("key_points") or []
            if kp:
                out.append("  - Key points:\n")
                for k in kp:
                    out.append(f"    - {k}\n")
            if c.get("covered_at_sec") is not None:
                out.append(f"  - Covered at: {c['covered_at_sec']:.0f}s\n")
            out.append("\n")
    if open_threads:
        out.append("## Open Threads\n\n")
        for t in open_threads:
            slug = t.get("slug")
            note = t.get("note") or ""
            if slug:
                out.append(f"- [[{slug}]] — {note}\n")
            else:
                out.append(f"- {note}\n")
        out.append("\n")
    if builds_on or followups:
        out.append("## Series Links\n\n")
        if builds_on:
            for b in builds_on:
                out.append(f"- Builds on: [[{b}]]\n")
        if followups:
            for f in followups:
                out.append(f"- Follow-up candidate: {f}\n")
        out.append("\n")
    return "".join(out)
```

- [ ] **Step 4: Verify tests pass**

```bash
source ~/notebooklm-py/.venv/bin/activate && pytest plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py -v
```

Expected: ~30 tests green (the implementer should count their actual tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/episode_wiki.py \
        plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py
git commit -m "feat(kb-publish): pure helpers for episode-index (validate_slug, compute_depth_deltas, render_*)

Implements the I/O-free public API from spec §7: slug validation,
slug→path conversion, depth-delta computation with lowest-ep-id
tie-break, stub-frontmatter update rules (created_by immutable),
filename slug normalization with non-ASCII fallback, concept
candidate resolution (title + alias only, no tags), and rendering
for stubs and episode wiki articles.

Tests (~30): cover slug validation edge cases, path assembly
without double-nesting, depth-delta tri-state plus ties, stub-update
immutability of created_by, filename normalization for ASCII and
Chinese-only topics, rendering snapshots.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: I/O helpers — scan_episode_wiki, concept_catalog, concepts_covered_by_episodes

**Goal:** Filesystem helpers. All depend on real file reads but don't call Haiku.

**Files:**
- Modify: `plugins/kb/skills/kb-publish/scripts/episode_wiki.py` (append helpers)
- Modify: `plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py` (append tests)

- [ ] **Step 1: Add failing tests for the new helpers**

Append to the test file:

```python
# scan_episode_wiki
def test_scan_lenient_skips_malformed(wiki_fixture, caplog):
    (wiki_fixture / "episodes" / "ep-04-broken.md").write_text("---\nepisode_id: not-a-number\n---\n", encoding="utf-8")
    eps = scan_episode_wiki(wiki_fixture, strict=False)
    assert len(eps) == 1  # the good one
    assert eps[0].episode_id == 3
    assert any("broken" in rec.message for rec in caplog.records)

def test_scan_strict_raises_on_malformed(wiki_fixture):
    (wiki_fixture / "episodes" / "ep-04-broken.md").write_text("---\nepisode_id: not-a-number\n---\n", encoding="utf-8")
    with pytest.raises(EpisodeParseError):
        scan_episode_wiki(wiki_fixture, strict=True)

def test_scan_sorts_by_episode_id(wiki_fixture):
    (wiki_fixture / "episodes" / "ep-01-foo.md").write_text(_minimal_episode_article(1), encoding="utf-8")
    (wiki_fixture / "episodes" / "ep-07-bar.md").write_text(_minimal_episode_article(7), encoding="utf-8")
    eps = scan_episode_wiki(wiki_fixture)
    assert [e.episode_id for e in eps] == [1, 3, 7]

# concept_catalog
def test_catalog_excludes_episodes_always(wiki_fixture):
    cat = concept_catalog(wiki_fixture, include_stubs=True)
    assert all(not slug.startswith("wiki/episodes/") for entries in cat.values() for e in entries for slug in [e["slug"]])

def test_catalog_includes_stubs_by_default(wiki_fixture):
    cat = concept_catalog(wiki_fixture)
    all_slugs = {e["slug"] for entries in cat.values() for e in entries}
    assert "wiki/quantization/k-quants" in all_slugs

def test_catalog_excludes_stubs_when_false(wiki_fixture):
    cat = concept_catalog(wiki_fixture, include_stubs=False)
    all_slugs = {e["slug"] for entries in cat.values() for e in entries}
    assert "wiki/quantization/k-quants" not in all_slugs

# concepts_covered_by_episodes
def test_concepts_aggregation_grouping(wiki_fixture):
    eps = scan_episode_wiki(wiki_fixture)
    coverage = concepts_covered_by_episodes(eps)
    assert "wiki/quantization/k-quants" in coverage
    assert coverage["wiki/quantization/k-quants"][0]["ep_id"] == 3
```

The helper `_minimal_episode_article(ep_id)` needs to be imported from conftest or duplicated; simplest: import via `from .conftest import _minimal_episode_article` or define at test-file module scope.

- [ ] **Step 2: Verify tests fail**

Same command as Task 2 step 2. Expect failures because the helpers don't exist yet.

- [ ] **Step 3: Implement the helpers**

Append to `episode_wiki.py`:

```python
import logging

log = logging.getLogger(__name__)


def scan_episode_wiki(
    wiki_dir: Path,
    strict: bool = False,
) -> list[IndexedEpisode]:
    ep_dir = wiki_dir / "episodes"
    if not ep_dir.is_dir():
        return []
    out: list[IndexedEpisode] = []
    for fp in sorted(ep_dir.glob("*.md")):
        try:
            ep = _parse_episode_article(fp)
            out.append(ep)
        except Exception as e:
            if strict:
                raise EpisodeParseError(f"{fp.name}: {e}") from e
            log.warning("Skipping malformed episode %s: %s", fp.name, e)
    out.sort(key=lambda e: e.episode_id)
    return out


def _parse_episode_article(path: Path) -> IndexedEpisode:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise EpisodeParseError("no frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise EpisodeParseError("unterminated frontmatter")
    fm = yaml.safe_load(text[4:end])
    if not isinstance(fm, dict):
        raise EpisodeParseError("frontmatter not a dict")
    ep_id = fm.get("episode_id")
    if not isinstance(ep_id, int):
        raise EpisodeParseError(f"episode_id not int: {ep_id!r}")
    idx = fm.get("index") or {}
    concepts = []
    for c in idx.get("concepts", []) or []:
        concepts.append(IndexedConcept(
            slug=c.get("slug", ""),
            depth_this_episode=c.get("depth_this_episode", "mentioned"),
            depth_delta_vs_past=c.get("depth_delta_vs_past", "new"),
            prior_episode_ref=c.get("prior_episode_ref"),
            what=c.get("what", ""),
            why_it_matters=c.get("why_it_matters", ""),
            key_points=list(c.get("key_points") or []),
            covered_at_sec=c.get("covered_at_sec"),
        ))
    threads = []
    for t in idx.get("open_threads", []) or []:
        threads.append(OpenThread(
            slug=t.get("slug"),
            note=t.get("note", ""),
            existed_before=bool(t.get("existed_before", False)),
        ))
    sl = idx.get("series_links") or {}
    return IndexedEpisode(
        episode_id=ep_id,
        title=fm.get("title", ""),
        date=str(fm.get("date", "")),
        depth=fm.get("depth", ""),
        audio_file=fm.get("audio_file", ""),
        transcript_file=fm.get("transcript_file"),
        concepts=concepts,
        open_threads=threads,
        series_builds_on=list(sl.get("builds_on") or []),
        series_followup_candidates=list(sl.get("followup_candidates") or []),
    )


def concept_catalog(
    wiki_dir: Path,
    include_stubs: bool = True,
) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for fp in wiki_dir.rglob("*.md"):
        rel = fp.relative_to(wiki_dir)
        # Exclude episodes always
        if rel.parts and rel.parts[0] == "episodes":
            continue
        # Top-level flat file? skip (like README.md)
        if len(rel.parts) < 2:
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end < 0:
            continue
        try:
            fm = yaml.safe_load(text[4:end]) or {}
        except yaml.YAMLError:
            continue
        is_stub = fm.get("status") == "stub"
        if is_stub and not include_stubs:
            continue
        slug = "wiki/" + str(rel.with_suffix("")).replace(os.sep, "/")
        category = rel.parts[0]
        out.setdefault(category, []).append({
            "slug": slug,
            "title": fm.get("title", ""),
            "tags": list(fm.get("tags") or []),
            "aliases": list(fm.get("aliases") or []),
            "is_stub": is_stub,
        })
    return out


def concepts_covered_by_episodes(
    episodes: list[IndexedEpisode],
) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for ep in episodes:
        for c in ep.concepts:
            out.setdefault(c.slug, []).append({
                "ep_id": ep.episode_id,
                "depth": c.depth_this_episode,
                "key_points": list(c.key_points),
                "date": ep.date,
            })
    return out
```

- [ ] **Step 4: Verify tests pass**

Re-run the test command. All new tests should pass alongside the Task 2 tests.

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/episode_wiki.py \
        plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py
git commit -m "feat(kb-publish): scan_episode_wiki + concept_catalog + coverage aggregation

Adds the I/O helpers that read the wiki as a structured data source:
scan_episode_wiki with strict/lenient modes, concept_catalog with
include_stubs toggle (always excluding wiki/episodes/**), and
concepts_covered_by_episodes for depth-delta lookup.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Transactional core — staging + atomic commit

**Goal:** `index_episode_transactional()` — full transactional flow. Haiku not needed here; caller supplies extracted+validated+depth-delta'd concepts.

**Files:**
- Modify: `plugins/kb/skills/kb-publish/scripts/episode_wiki.py` (append)
- Modify: `plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py` (append)

- [ ] **Step 1: Failing tests for transactional flow**

Test list:
- `test_transactional_new_episode_creates_article_and_stubs`
- `test_transactional_skips_existing_non_stub_article`
- `test_transactional_same_episode_stub_fully_replaced`
- `test_transactional_other_episode_stub_frontmatter_only_updated`
- `test_transactional_commits_stubs_before_episode_article`
- `test_transactional_aborts_on_smoke_parse_failure`
- `test_transactional_excludes_episodes_yaml_from_writes`

- [ ] **Step 2: Verify failures**

- [ ] **Step 3: Implement**

Append to `episode_wiki.py`:

```python
def staging_dir(wiki_dir: Path) -> Path:
    root = wiki_dir.parent / ".kb-publish-staging" / uuid.uuid4().hex
    (root / "episodes").mkdir(parents=True, exist_ok=False)
    return root


def index_episode_transactional(
    wiki_dir: Path,
    episode_id: int,
    episode_topic: str,
    episode_date: str,
    episode_depth: str,
    audio_file: str,
    transcript_file: str,
    tags: list[str],
    aliases: list[str],
    source_lessons: list[str],
    extraction: dict,
) -> TransactionalIndexResult:
    # 1. Determine episode filename slug.
    filename_slug = normalize_filename_slug(episode_topic, aliases)
    validate_slug(f"wiki/episodes/ep-{episode_id}-{filename_slug}", allow_episode=True)
    ep_article_basename = f"ep-{episode_id}-{filename_slug}.md"

    # 2. Stage dir.
    staging = staging_dir(wiki_dir)
    new_stubs: list[str] = []
    stubs_updated: list[str] = []
    collisions_skipped: list[str] = []
    stub_updates_to_apply: list[tuple[Path, dict]] = []
    try:
        # 3. Validate all concept slugs before any writes.
        for c in extraction["concepts"]:
            validate_slug(c["slug"], allow_episode=False)

        # 4. Stage stubs and compute stub-updates.
        for c in extraction["concepts"]:
            rel = slug_to_wiki_relative_path(c["slug"])
            dest = wiki_dir / rel
            if dest.exists():
                fm, body = _split_frontmatter(dest.read_text(encoding="utf-8"))
                if fm.get("status") == "stub":
                    ep_tag = f"ep-{episode_id}"
                    if fm.get("created_by") == ep_tag:
                        # Same-episode reindex: stage a full replacement.
                        staged = staging / rel
                        staged.parent.mkdir(parents=True, exist_ok=True)
                        staged.write_text(
                            render_stub(c["slug"], c, episode_id,
                                        ep_article_basename.replace(".md", ""),
                                        episode_date),
                            encoding="utf-8",
                        )
                        stubs_updated.append(c["slug"])
                    else:
                        # Different-episode stub: frontmatter-only update at commit time.
                        updated = compute_stub_update(fm, c, episode_id)
                        if updated is not None:
                            stub_updates_to_apply.append((dest, updated))
                            stubs_updated.append(c["slug"])
                else:
                    # Non-stub canonical article exists — leave alone.
                    collisions_skipped.append(c["slug"])
            else:
                # Brand new stub.
                staged = staging / rel
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_text(
                    render_stub(c["slug"], c, episode_id,
                                ep_article_basename.replace(".md", ""),
                                episode_date),
                    encoding="utf-8",
                )
                new_stubs.append(c["slug"])

        # 5. Render & stage episode article.
        ep_md = render_episode_wiki(
            episode_id=episode_id,
            title=extraction.get("episode_title_override") or f"EP{episode_id} | {episode_topic}",
            date=episode_date,
            depth=episode_depth,
            audio_file=audio_file,
            transcript_file=transcript_file,
            summary=extraction["summary"],
            concepts=extraction["concepts"],
            open_threads=extraction["open_threads"],
            series_builds_on=extraction["series_links"]["builds_on"],
            series_followup_candidates=extraction["series_links"]["followup_candidates"],
            source_lessons=source_lessons,
            tags=tags,
            aliases=aliases,
        )
        (staging / "episodes" / ep_article_basename).write_text(ep_md, encoding="utf-8")

        # 6. Smoke-parse the staging in strict mode.
        scan_episode_wiki(staging, strict=True)

        # 7. Commit — stubs first, then stub updates, then episode article.
        for rel_md in _iter_staged_non_episode(staging):
            src = staging / rel_md
            dst = wiki_dir / rel_md
            if dst.exists():
                fm, _ = _split_frontmatter(dst.read_text(encoding="utf-8"))
                if fm.get("status") != "stub":
                    # Concurrent race: article was filled in while we staged. Skip.
                    continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)

        for dest, updated_fm in stub_updates_to_apply:
            text = dest.read_text(encoding="utf-8")
            _, body = _split_frontmatter(text)
            new_text = "---\n" + yaml.safe_dump(updated_fm, allow_unicode=True, sort_keys=False) + "---\n" + body
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_text(new_text, encoding="utf-8")
            os.replace(tmp, dest)

        ep_dst = wiki_dir / "episodes" / ep_article_basename
        ep_dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging / "episodes" / ep_article_basename, ep_dst)
    except (SlugValidationError, EpisodeParseError, KeyError) as e:
        raise TransactionAbortedError(str(e)) from e
    finally:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)

    return TransactionalIndexResult(
        episode_article=ep_dst,
        new_stubs_created=new_stubs,
        stubs_updated=stubs_updated,
        collisions_skipped=collisions_skipped,
    )


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm = yaml.safe_load(text[4:end]) or {}
    return fm, text[end + len("\n---\n"):]


def _iter_staged_non_episode(staging: Path):
    for fp in staging.rglob("*.md"):
        rel = fp.relative_to(staging)
        if rel.parts[0] == "episodes":
            continue
        yield rel
```

- [ ] **Step 4: Verify pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(kb-publish): transactional index_episode_transactional

Stages episode article + stubs into a per-session temp dir, runs a
strict-mode smoke parse on the staging dir, then commits atomically
via os.replace with stubs first and the episode article last so
wikilinks always resolve at the moment the episode becomes visible.

Same-episode reindex fully replaces stubs introduced by that episode;
other-episode stubs get frontmatter-only updates preserving
created_by. Collisions with non-stub articles are skipped.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Haiku prompt + `orchestrate_episode_index`

**Goal:** Layer 1 wiring. The prompt template goes to `plugins/kb/skills/kb-publish/prompts/episode-wiki-extract.md`. The Python wrapper `orchestrate_episode_index()` reads the transcript, builds catalog+context, calls Haiku, validates, recomputes `existed_before`, computes depth deltas excluding current episode, calls `index_episode_transactional`.

**Files:**
- Create: `plugins/kb/skills/kb-publish/prompts/episode-wiki-extract.md` — full prompt per spec §2.
- Modify: `plugins/kb/skills/kb-publish/scripts/episode_wiki.py` (append)
- Modify: `plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py` (append)

- [ ] **Step 1: Write the prompt template**

The prompt file is self-contained; its full body is in spec §2. Implementer writes it verbatim.

- [ ] **Step 2: Failing tests**

Test names:
- `test_orchestrate_calls_haiku_once_with_expected_inputs`
- `test_orchestrate_recomputes_existed_before`
- `test_orchestrate_excludes_current_episode_from_coverage_map`
- `test_orchestrate_aborts_on_haiku_malformed_json`
- `test_orchestrate_retries_once_on_malformed_then_succeeds`

Haiku is injected as a `Callable[[str], str]` that the test supplies.

- [ ] **Step 3: Implement**

Append to `episode_wiki.py`:

```python
def _validate_extraction_shape(data: dict) -> None:
    if "summary" not in data or "concepts" not in data or "open_threads" not in data:
        raise TransactionAbortedError("missing top-level keys in extraction")
    for c in data.get("concepts", []):
        for k in ("slug", "depth_this_episode", "what", "why_it_matters", "key_points"):
            if k not in c:
                raise TransactionAbortedError(f"concept missing key {k!r}")
        if c["depth_this_episode"] not in ("mentioned", "explained", "deep-dive"):
            raise TransactionAbortedError(f"invalid depth_this_episode: {c['depth_this_episode']!r}")


def _recompute_existed_before(concepts: list[dict], wiki_dir: Path) -> list[dict]:
    out = []
    for c in concepts:
        rel = slug_to_wiki_relative_path(c["slug"])
        c = dict(c)
        c["existed_before"] = (wiki_dir / rel).exists()
        out.append(c)
    return out


def orchestrate_episode_index(
    wiki_dir: Path,
    episode_id: int,
    episode_topic: str,
    episode_date: str,
    episode_depth: str,
    audio_file: str,
    transcript_path: Path,
    transcript_file: str,
    tags: list[str],
    aliases: list[str],
    source_lessons: list[str],
    haiku_call: Callable[[str], str],
    prompt_template_path: Path,
) -> TransactionalIndexResult:
    transcript = transcript_path.read_text(encoding="utf-8")
    catalog = concept_catalog(wiki_dir, include_stubs=True)
    all_eps = scan_episode_wiki(wiki_dir, strict=False)
    recent_eps = [e for e in all_eps if e.episode_id != episode_id][-3:]
    template = prompt_template_path.read_text(encoding="utf-8")

    prompt = (template
              .replace("{transcript}", transcript)
              .replace("{episode_metadata}",
                       yaml.safe_dump({
                           "id": episode_id, "title": f"EP{episode_id} | {episode_topic}",
                           "date": episode_date, "depth": episode_depth,
                           "topic": episode_topic, "source_lessons": source_lessons,
                       }, allow_unicode=True))
              .replace("{concept_catalog}",
                       yaml.safe_dump(catalog, allow_unicode=True))
              .replace("{recent_episodes}",
                       yaml.safe_dump([{"ep_id": e.episode_id, "title": e.title,
                                        "depth": e.depth,
                                        "concepts": [c.slug for c in e.concepts],
                                        "open_threads": [t.slug or t.note for t in e.open_threads]}
                                       for e in recent_eps], allow_unicode=True)))

    for attempt in range(2):
        raw = haiku_call(prompt)
        try:
            data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            _validate_extraction_shape(data)
            break
        except (json.JSONDecodeError, TransactionAbortedError) as e:
            if attempt == 1:
                raise TransactionAbortedError(f"Haiku returned invalid JSON after retry: {e}") from e

    data["concepts"] = _recompute_existed_before(data["concepts"], wiki_dir)
    # Coverage excluding current episode
    coverage = concepts_covered_by_episodes([e for e in all_eps if e.episode_id != episode_id])
    data["concepts"] = compute_depth_deltas(data["concepts"], coverage)

    return index_episode_transactional(
        wiki_dir=wiki_dir, episode_id=episode_id, episode_topic=episode_topic,
        episode_date=episode_date, episode_depth=episode_depth,
        audio_file=audio_file, transcript_file=transcript_file,
        tags=tags, aliases=aliases, source_lessons=source_lessons,
        extraction=data,
    )
```

- [ ] **Step 4: Verify pass**

- [ ] **Step 5: Commit**

---

## Task 6: Dedup judge prompt + judge function (Layer 3)

**Goal:** Prompt template + Python wrapper for the pre-generation dedup call kb-notebooklm will use.

**Files:**
- Create: `plugins/kb/skills/kb-notebooklm/prompts/dedup-judge.md`
- Modify: `plugins/kb/skills/kb-publish/scripts/episode_wiki.py` (add `judge_candidate_episode`)

- [ ] **Step 1: Write the judge prompt**

Body per spec §4.

- [ ] **Step 2: Failing tests**

- `test_judge_builds_prior_hits_per_candidate`
- `test_judge_calls_haiku_with_expected_structure`
- `test_judge_returns_validated_per_concept_verdicts`

- [ ] **Step 3: Implement `judge_candidate_episode` and the Haiku-injected wrapper**

Append to `episode_wiki.py`:

```python
@dataclass
class DedupJudgement:
    per_concept: list[dict]
    episode_verdict: str          # proceed | reframe | skip
    framing_recommendation: str


def judge_candidate_episode(
    wiki_dir: Path,
    candidate_concepts: list[str],
    open_threads_allow: list[str] | None = None,
    haiku_call: Callable[[str], str] | None = None,
    prompt_template_path: Path | None = None,
) -> DedupJudgement:
    all_eps = scan_episode_wiki(wiki_dir, strict=False)
    coverage = concepts_covered_by_episodes(all_eps)
    catalog = concept_catalog(wiki_dir, include_stubs=True)

    prior_hits: dict[str, list[dict]] = {}
    for cand in candidate_concepts:
        resolved = resolve_concept_candidate(cand, catalog) or cand
        prior_hits[cand] = coverage.get(resolved, [])

    open_threads = []
    for ep in all_eps[-5:]:
        for t in ep.open_threads:
            open_threads.append({"ep_id": ep.episode_id, "note": t.note, "slug": t.slug})

    if haiku_call is None or prompt_template_path is None:
        # Caller is responsible for injecting — raise in production if not injected.
        raise RuntimeError("haiku_call and prompt_template_path required")

    template = prompt_template_path.read_text(encoding="utf-8")
    prompt = (template
              .replace("{candidates}", yaml.safe_dump(candidate_concepts, allow_unicode=True))
              .replace("{prior_hits}", yaml.safe_dump(prior_hits, allow_unicode=True))
              .replace("{open_threads}", yaml.safe_dump(open_threads, allow_unicode=True)))
    for attempt in range(2):
        raw = haiku_call(prompt)
        try:
            data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            break
        except json.JSONDecodeError:
            if attempt == 1:
                raise
    return DedupJudgement(
        per_concept=data.get("per_concept") or [],
        episode_verdict=data.get("episode_verdict", "proceed"),
        framing_recommendation=data.get("framing_recommendation", ""),
    )
```

- [ ] **Step 4-5: Verify + commit**

---

## Task 7: `backfill_index.py` CLI

**Goal:** The `/kb-publish backfill-index` command. Thin wrapper: iterates episodes from `episodes.yaml`, transcribes missing transcripts via `transcribe_audio.py`, calls `orchestrate_episode_index()`.

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/backfill_index.py`
- Modify: `plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py` or create `test_backfill_index.py`

- [ ] **Step 1: Implement the CLI**

Full CLI: argparse, loads kb.yaml, iterates, for each episode: resolves audio, checks transcript (inline or regenerate), calls `orchestrate_episode_index`, updates episodes.yaml.

The Haiku call uses the `anthropic` SDK directly:

```python
from anthropic import Anthropic
client = Anthropic()

def haiku_call(prompt: str) -> str:
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if hasattr(b, "text"))
```

- [ ] **Step 2-4: Tests, verify, commit**

---

## Task 8: kb-publish SKILL.md — add step 8c + backfill subcommand docs

- [ ] Insert step 8c between 8b and the existing tail of the publish workflow.
- [ ] Document the `backfill-index` subcommand in a new section.
- [ ] Commit.

---

## Task 9: kb-notebooklm SKILL.md — rewrite step 5b

- [ ] Replace the current 5b with the Layer 3 judge invocation.
- [ ] Move step 5b to run AFTER step 4b's confidentiality filter (so only sanitized lessons are considered).
- [ ] Commit.

---

## Task 10: Version bump + full test run

- [ ] Bump `plugins/kb/.claude-plugin/plugin.json` from `1.14.0` to `1.15.0`.
- [ ] Run full test suite, confirm all green.
- [ ] `claude plugin marketplace update llm-kb-skills && claude plugin install kb@llm-kb-skills`.
- [ ] Commit.

---

## Task 11: Backfill EP1 and EP2 (live proof)

- [ ] Run `/kb-publish backfill-index --episode 1`.
- [ ] Verify `~/Documents/MLL/output/notebooklm/podcast-hardware-2026-04-12.transcript.md` exists.
- [ ] Verify `~/Documents/MLL/wiki/episodes/ep-01-*.md` exists and parses via `scan_episode_wiki`.
- [ ] Verify `episodes.yaml` EP1 entry has updated `concepts_covered[]`.
- [ ] Repeat for `--episode 2`.
- [ ] Open Obsidian Graph view, confirm EP1 + EP2 nodes connect to concept articles.
- [ ] No commit — output files are in the user's KB, not this repo.

---

## Task 12: Procedural verification of dedup judge

- [ ] Configure a mock "propose EP4 — quantization deep-dive" via `/kb-notebooklm podcast --topic quantization` in dry-run mode.
- [ ] Confirm step 5b now produces structured `per_concept` verdicts (flagging k-quants as `redundant_same_depth` if EP3 published today covers it).
- [ ] Paste the resulting user-facing output into the PR description as proof.
- [ ] No commit.

---

## Self-Review

Coverage vs spec:
- §1 episode article format → Task 2 (render_episode_wiki)
- §2 extraction with validation + depth-delta-in-python + existed_before recompute → Task 5
- §3 auto-stub + collision rules → Task 4 (in `index_episode_transactional`)
- §4 Layer 3 judge → Task 6
- §5 step 8c integration → Task 8
- §6 step 5b integration → Task 9
- §7 module API → Tasks 2, 3, 4, 5, 6
- §8 backfill command → Task 7
- §9 error handling → distributed across Tasks 2–7
- §10 tests → covered across Tasks 2, 3, 4, 5, 6, 7

Placeholder scan: No "TBD", "TODO" in plan. Each task references spec sections for the longer bodies (prompt templates, test fixtures). The implementer pulls from the spec directly for those — avoids plan duplication.

Type consistency: Dataclass field names, function signatures, and error types match across Tasks 2–6.

---

## Execution Handoff

Subagent-driven per user convention. Final "proof it works" is Task 11 (backfill EP1+EP2) + Task 12 (dedup judge on synthetic EP4).
