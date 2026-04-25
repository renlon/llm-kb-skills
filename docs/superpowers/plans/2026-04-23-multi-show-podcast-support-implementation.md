# Multi-Show Podcast Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `show` as a first-class dimension across the kb plugin so the user can run multiple podcasts from the same KB. Ship v2.0.0.

**Architecture:** New `shows.py` module provides the `Show` dataclass, `EpRef` value object, and two resolvers (`resolve_show_for_mutation`, `resolve_show_for_read`). Episode-wiki code updated to scope every read to the resolved show. All mutating commands acquire a KB-wide file lock `.kb-mutation.lock` before writes — including detached background agents. A one-shot `/kb migrate` command converts existing single-show KBs to the new format via a 4-phase transactional flow (plan → sidecar-in-place → validate → commit with copy-then-verify + per-entry log).

**Tech Stack:**
- Python stdlib (hashlib, dataclasses, pathlib, tempfile, fcntl for lock) + PyYAML (already in venv)
- Anthropic Bedrock SDK (already installed)
- pytest for unit tests
- Existing test infrastructure at `plugins/kb/skills/kb-publish/scripts/tests/`

---

## Contracts Table (authoritative reference for ALL tasks)

This table locks down the cross-task contracts. Every task MUST honor it. If a task finds a contract wrong, STOP and fix the contract here first, then update dependent tasks.

### Core types

| Type | Definition | Key invariants |
|---|---|---|
| `Show` | frozen dataclass in `shows.py` | `id` matches `^[a-z][a-z0-9\-]{0,31}$`; `wiki_episodes_dir == f"episodes/{id}"` (validated); `title` is non-empty str |
| `EpRef` | frozen dataclass `{show: str, ep: int}` | `show` non-empty; `ep >= 1`; serialized to YAML as `{show, ep}` dict |
| `ShowConfigError` | ValueError subclass | raised on any validation failure |
| `ShowNotFoundError` | ShowConfigError subclass | unknown show id |
| `AmbiguousShowError` | ShowConfigError subclass | multi-show + no `--show` on mutating cmd |
| `UnknownShowError` | ShowConfigError subclass | EpRef.show not in configured shows |
| `MigrationRequiredError` | RuntimeError subclass | legacy str/int ref encountered at runtime |
| `LockBusyError` | RuntimeError subclass | `.kb-mutation.lock` held by another PID |
| `PendingWorkError` | RuntimeError subclass | idle-check found pending runs/notebooks |
| `MixedShowCoverageError` | ShowConfigError subclass | coverage_map for depth-delta spans multiple shows |
| `ShowMismatchError` | ShowConfigError subclass | sidecar `show:` conflicts with `--show` flag |
| `ResumeMismatchError` | RuntimeError subclass | `/kb migrate --resume` flags don't match the persisted Phase-A plan |
| `LiveDriftError` | RuntimeError subclass | `/kb migrate --resume` found a live file modified after Phase A snapshot |

### Canonical function signatures (no deviations allowed)

```python
# shows.py
def load_shows(kb_yaml: dict, project_root: Path) -> list[Show]
def validate_shows(shows_raw: list[dict], *, project_root: Path, wiki_path: Path) -> list[Show]
def resolve_show_for_mutation(shows: list[Show], show_id: str | None) -> Show
def resolve_show_for_read(shows: list[Show], show_id: str | None) -> Show | None
def parse_ep_ref_field(value: Any, *, known_shows: set[str]) -> EpRef

# EpRef methods
EpRef.from_dict(d: dict) -> EpRef
EpRef.from_legacy(value, *, default_show: str) -> EpRef   # ONLY used by migrator
EpRef.to_dict(self) -> dict
EpRef.wikilink_stem(self, slug: str) -> str
  # Returns f"wiki/episodes/{self.show}/ep-{self.ep}-{slug}"
  # This is the OBSIDIAN wikilink path — same structure regardless of physical path.

# episode_wiki.py (updated)
def scan_episode_wiki(wiki_path: Path, show: Show, *, strict: bool = False) -> list[IndexedEpisode]
def resolve_episode_wikilink(ref: EpRef, shows_by_id: dict[str, Show], wiki_path: Path) -> str
  # Looks up the episode file under wiki_path / shows_by_id[ref.show].wiki_episodes_dir /
  # f"ep-{ref.ep}-*.md" to recover the slug, then returns ref.wikilink_stem(<slug>).
  # Raises UnknownShowError if ref.show not in shows_by_id, FileNotFoundError if no match.
def validate_body_wikilinks(text: str, known_shows: set[str]) -> list[str]
  # Returns error strings for legacy [[wiki/episodes/ep-N-...]] patterns and
  # for wikilinks targeting unknown shows. Empty list on success.

# Lock + state
@contextmanager
def kb_mutation_lock(project_root: Path, command: str, *, timeout: float = 5.0):
    """Acquire .kb-mutation.lock; raise LockBusyError on timeout."""

def load_state_file(path: Path, *, default_show_id: str) -> dict:
    """Dual-format: reads legacy flat shape OR new shows.<id>.* shape.
    `default_show_id` is required because legacy state files have no show
    dimension — their contents get wrapped under shows.<default_show_id>.*."""

def write_state_file(path: Path, state: dict) -> None:
    """Always writes new format."""
```

### Path conventions

| Path | Resolved against | Example |
|---|---|---|
| `episodes_registry` | `project_root` | `episodes.yaml` → `<project>/episodes.yaml` |
| `wiki_episodes_dir` | `wiki_path` | `episodes/quanzhan-ai` → `<wiki_path>/episodes/quanzhan-ai` |
| Obsidian wikilink stem | conventional | `wiki/episodes/quanzhan-ai/ep-3-quantization` |
| `output_path` | absolute (from kb.yaml) | `/Users/.../output` |
| `wiki_path` | absolute (from kb.yaml) | `/Users/.../wiki` |

### YAML serialization rules

| Field | Before (legacy) | After (multi-show) |
|---|---|---|
| stub `created_by` | `"ep-3"` | `{show: quanzhan-ai, ep: 3}` |
| stub `last_seen_by` / `best_depth_episode` | `"ep-3"` | same dict form |
| stub `referenced_by` | `["ep-1", "ep-2"]` | `[{show: quanzhan-ai, ep: 1}, {show: quanzhan-ai, ep: 2}]` |
| episode article `index.concepts[].prior_episode_ref` | `3` or `null` | `{show: quanzhan-ai, ep: 3}` or `null` |
| episode article `index.series_links.builds_on[]` | `[3]` or `["wiki/episodes/ep-3-..."]` | `[{show: quanzhan-ai, ep: 3}]` |
| body wikilinks | `[[wiki/episodes/ep-1-slug]]` | `[[wiki/episodes/quanzhan-ai/ep-1-slug]]` |
| sidecar manifest | (no show field) | gain `show: quanzhan-ai` at top level |
| state file top-level | `runs: [...]`, `notebooks: [...]`, `last_podcast: ...` | `shows: {quanzhan-ai: {runs: [...], notebooks: [...], last_podcast: ...}}` |

### Output filename convention

Every show-scoped workflow prefixes `<show-id>-` even for single-show deployments:
- `podcast-<show-id>-<theme>-YYYY-MM-DD.mp3` (and `.raw.mp3`, `.vtt`, `.transcript.md`, `.mp3.manifest.yaml`)
- `quiz-<show-id>-<theme>-YYYY-MM-DD.md` / `.json`
- `digest-<show-id>-YYYY-MM-DD.mp3`
- `report-<show-id>-<topic>-YYYY-MM-DD.md`
- `research-audio-<show-id>-YYYY-MM-DD.mp3`

Pre-migration files do NOT get renamed.

### Lock semantics

- File: `<project_root>/.kb-mutation.lock`
- Content: JSON `{pid, command, start_time}`
- Acquire: acquire before ANY write; release on normal exit + SIGINT + SIGTERM
- Refuse to start if held by another live PID (check `os.kill(pid, 0)`); remove stale locks with user confirmation
- Detached background agents (NotebookLM wait finalizers) MUST acquire the same lock around their final writes
- Migrate additionally requires idle-check (no `status: pending` runs/notebooks) AFTER acquiring the lock

---

## File Structure

### New files

- `plugins/kb/skills/kb-publish/scripts/shows.py` — `Show`, `EpRef`, resolvers, validators
- `plugins/kb/skills/kb-publish/scripts/state.py` — dual-format state loader/writer, idle-check helper
- `plugins/kb/skills/kb-publish/scripts/lock.py` — `kb_mutation_lock()` context manager
- `plugins/kb/skills/kb-publish/scripts/tests/test_shows.py`
- `plugins/kb/skills/kb-publish/scripts/tests/test_state.py`
- `plugins/kb/skills/kb-publish/scripts/tests/test_lock.py`
- `plugins/kb/skills/kb/scripts/__init__.py` (new subdir)
- `plugins/kb/skills/kb/scripts/migrate_multi_show.py` — migrator CLI
- `plugins/kb/skills/kb/scripts/tests/__init__.py`
- `plugins/kb/skills/kb/scripts/tests/test_migrate_multi_show.py`

### Modified files

- `plugins/kb/skills/kb-publish/scripts/episode_wiki.py` — carry `EpRef` throughout, new `scan_episode_wiki(wiki_path, show)` signature, `resolve_episode_wikilink`, `validate_body_wikilinks`, `MixedShowCoverageError` in `compute_depth_deltas`
- `plugins/kb/skills/kb-publish/scripts/backfill_index.py` — add `--show` flag, resolve via `resolve_show_for_mutation`, wire lock
- `plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py` — make `--title` required, remove `全栈AI` fallback
- `plugins/kb/skills/kb-publish/prompts/episode-wiki-extract.md` — instruct Haiku to emit `{show, ep}` dicts in `series_links.builds_on`
- `plugins/kb/skills/kb-notebooklm/prompts/podcast-tutor.md` — replace hardcoded `全栈AI` with `{show_title}` placeholder
- `plugins/kb/skills/kb-notebooklm/prompts/dedup-judge.md` — canonical prior_hits shape `[{show, ep_id, depth, key_points}]`
- `plugins/kb/skills/kb-publish/prompts/cover-style.md` — templated `{show_title}` brand reference
- `plugins/kb/skills/kb-notebooklm/SKILL.md` — step 1 (preamble), 4b, 5b, 6a', 6a'', 6i, 6k, step 7, cleanup, status
- `plugins/kb/skills/kb-publish/SKILL.md` — step 1 (preamble), sequencing rule (sidecar vs `--show`), step 2b, step 8c
- `plugins/kb/skills/kb-init/SKILL.md` — seed `shows[0]` on fresh installs
- `plugins/kb/skills/kb/SKILL.md` — document `/kb migrate`
- `plugins/kb/.claude-plugin/plugin.json` — bump to `2.0.0` (breaking change)

---

## Task Order and Dependencies

The spec is huge but the task graph has clear layers. Build bottom-up:

**Layer 0: foundation** (no runtime behavior, all unit-tested pure logic)
1. Tests scaffold for the new modules
2. `shows.py` — types, validators, resolvers
3. `EpRef` and `parse_ep_ref_field` in `shows.py`

**Layer 1: cross-cutting infrastructure**
4. `lock.py` — file lock
5. `state.py` — dual-format state loader, idle-check

**Layer 2: episode-wiki integration**
6. `episode_wiki.py` API updates — new `scan_episode_wiki(wiki_path, show)`, `resolve_episode_wikilink`, `validate_body_wikilinks`
7. `episode_wiki.py` — `compute_depth_deltas` emits `{show, ep}`, raises `MixedShowCoverageError`
8. `episode_wiki.py` — `render_stub`, `compute_stub_update`, `render_episode_wiki` emit new YAML dict form
9. `episode_wiki.py` — `scan_episode_wiki` parses new YAML dict form, raises `MigrationRequiredError` on legacy
10. `backfill_index.py` — `--show` flag, show-aware resolution

**Layer 3: transcribe_audio + prompt branding**
11. `transcribe_audio.py` — `--title` required
12. Update prompt templates (`podcast-tutor.md`, `dedup-judge.md`, `cover-style.md`, `episode-wiki-extract.md`)

**Layer 4: migrator**
13. `migrate_multi_show.py` — detection tri-state
14. `migrate_multi_show.py` — Phase A (plan + staging)
15. `migrate_multi_show.py` — Phase A-bis (sidecar in-place)
16. `migrate_multi_show.py` — Phase B (validate)
17. `migrate_multi_show.py` — Phase C (copy-then-verify commit)
18. `migrate_multi_show.py` — Phase D + CLI + idle check + lock

**Layer 5: SKILL.md updates**
19. `kb-notebooklm/SKILL.md` edits (preamble, step numbers, branding)
20. `kb-publish/SKILL.md` edits (sequencing, backfill, step 8c)
21. `kb-init/SKILL.md` edits (seed shows[0])
22. `kb/SKILL.md` edits (document migrate)

**Layer 6: version + integration**
23. Bump plugin.json to 2.0.0; full test suite passes
23.5. End-to-end smoke test harness (hermetic; no real KB)
23.6. Rollback safety script (escape hatch)
24. Live migration on the real KB at `~/Documents/MLL/`
25. Verify EP3 v2 regenerate works post-migration

---

## Test Strategy

Hermetic pytest, no network:
- pure function tests for everything in `shows.py`, `state.py`, `lock.py`
- fixture-based tests for `episode_wiki.py` changes (synthetic wiki trees in `tmp_path`)
- migrator tests use fixture KBs that mirror the structure of `~/Documents/MLL/` but in `tmp_path`
- lock tests spawn subprocesses to verify mutual exclusion

No integration tests against real Bedrock in this plan — that's for the final live-migration task.

---

## Task 1: Test scaffolding for new modules

**Goal:** add `test_shows.py`, `test_state.py`, `test_lock.py` skeletons under the existing `plugins/kb/skills/kb-publish/scripts/tests/`. Create the `plugins/kb/skills/kb/scripts/` dir + tests subdir.

**Files:**
- Create: `plugins/kb/skills/kb/scripts/__init__.py` (empty)
- Create: `plugins/kb/skills/kb/scripts/tests/__init__.py` (empty)
- Create: `plugins/kb/skills/kb/scripts/tests/conftest.py` (pytest fixtures stubs; copy conftest pattern from kb-publish)

- [ ] **Step 1: Create kb/scripts package markers**

```bash
mkdir -p /Users/dragon/PycharmProjects/llm-kb-skills/plugins/kb/skills/kb/scripts/tests
touch /Users/dragon/PycharmProjects/llm-kb-skills/plugins/kb/skills/kb/scripts/__init__.py
touch /Users/dragon/PycharmProjects/llm-kb-skills/plugins/kb/skills/kb/scripts/tests/__init__.py
```

- [ ] **Step 2: Create conftest.py for kb/scripts tests**

Write `plugins/kb/skills/kb/scripts/tests/conftest.py`:

```python
"""Shared pytest fixtures for kb/scripts/migrate_multi_show tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow direct imports from the local kb/scripts/ dir.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Also allow imports from the sibling kb-publish/scripts/ dir — the migrator
# reuses shows.py, state.py, lock.py, and episode_wiki.py from there.
_SIBLING_SCRIPTS = (
    Path(__file__).resolve().parents[3] / "kb-publish" / "scripts"
)
if str(_SIBLING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SIBLING_SCRIPTS))


@pytest.fixture
def pre_migration_kb(tmp_path: Path) -> Path:
    """Build a minimal pre-migration KB fixture: kb.yaml + .notebooklm-state.yaml + wiki/episodes/flat + stubs."""
    project = tmp_path / "project"
    project.mkdir()
    wiki = project / "wiki"
    (wiki / "episodes").mkdir(parents=True)
    (wiki / "attention").mkdir()
    output = project / "output"
    output.mkdir()

    # Legacy kb.yaml (single-show)
    (project / "kb.yaml").write_text(
        "integrations:\n"
        "  notebooklm:\n"
        "    enabled: true\n"
        "    cli_path: /dev/null\n"
        "    venv_path: /dev/null\n"
        "    lessons_path: " + str(project / "lessons") + "\n"
        "    wiki_path: " + str(wiki) + "\n"
        "    output_path: " + str(output) + "\n"
        "    language: zh_Hans\n"
        "    podcast:\n"
        "      format: deep-dive\n"
        "      length: long\n"
        "      hosts: ['A', 'B']\n"
        "      intro_music: /dev/null/intro.mp3\n"
        "      intro_music_length_seconds: 12\n"
        "      intro_crossfade_seconds: 3\n"
        "      transcript:\n"
        "        enabled: false\n"
        "        model: large-v3\n"
        "        device: auto\n"
        "        language: zh\n"
        "  xiaoyuzhou:\n"
        "    enabled: true\n"
        "    podcast_id: 'LEGACY_PODCAST_ID'\n"
        "    episodes_registry: episodes.yaml\n"
        "    browser_data: .browser-data\n"
        "    staging_dir: output/staging\n"
        "    venv_path: /dev/null\n",
        encoding="utf-8",
    )

    # Legacy episodes.yaml
    (project / "episodes.yaml").write_text(
        "episodes:\n"
        "  - id: 1\n"
        "    title: 'EP1 | Test'\n"
        "    topic: Test\n"
        "    date: '2026-04-01'\n"
        "    status: published\n"
        "    audio: podcast-test-2026-04-01.mp3\n"
        "next_id: 2\n",
        encoding="utf-8",
    )

    # Legacy state file
    (project / ".notebooklm-state.yaml").write_text(
        "last_podcast: null\n"
        "last_digest: null\n"
        "last_quiz: null\n"
        "notebooks: []\n"
        "runs: []\n",
        encoding="utf-8",
    )

    # One flat episode article at legacy path
    (wiki / "episodes" / "ep-1-test.md").write_text(
        "---\n"
        "title: 'EP1 | Test'\n"
        "episode_id: 1\n"
        "audio_file: podcast-test-2026-04-01.mp3\n"
        "transcript_file: podcast-test-2026-04-01.transcript.md\n"
        "date: '2026-04-01'\n"
        "depth: intro\n"
        "tags: [episode]\n"
        "aliases: []\n"
        "source_lessons: []\n"
        "index:\n"
        "  schema_version: 1\n"
        "  summary: 'Test.'\n"
        "  concepts:\n"
        "    - slug: wiki/attention/self-attention\n"
        "      depth_this_episode: explained\n"
        "      depth_delta_vs_past: new\n"
        "      prior_episode_ref: null\n"
        "      what: 'W'\n"
        "      why_it_matters: 'Y'\n"
        "      key_points: ['k']\n"
        "      covered_at_sec: 1.0\n"
        "      existed_before: false\n"
        "  open_threads: []\n"
        "  series_links:\n"
        "    builds_on: []\n"
        "    followup_candidates: []\n"
        "---\n"
        "\n"
        "# EP1 | Test\n"
        "\n"
        "See [[wiki/episodes/ep-1-test]] for details.\n",
        encoding="utf-8",
    )

    # One legacy stub
    (wiki / "attention" / "self-attention.md").write_text(
        "---\n"
        "title: Self Attention\n"
        "tags: [stub, attention]\n"
        "aliases: []\n"
        "status: stub\n"
        "created_by: ep-1\n"
        "last_seen_by: ep-1\n"
        "best_depth_episode: ep-1\n"
        "best_depth: explained\n"
        "referenced_by: [ep-1]\n"
        "created: '2026-04-01'\n"
        "---\n"
        "\n"
        "# Self Attention\n"
        "\n"
        "Stub. Introduced in [[wiki/episodes/ep-1-test]].\n",
        encoding="utf-8",
    )

    return project
```

- [ ] **Step 3: Commit**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
git add plugins/kb/skills/kb/scripts/
git commit -m "$(cat <<'EOF'
feat(kb): scaffold kb/scripts/ package for migrate_multi_show

Adds empty package markers and a conftest.py with a pre_migration_kb
fixture that mirrors a real single-show KB structure in tmp_path.
The fixture covers kb.yaml, episodes.yaml, state file, a flat
episode article with body wikilinks, and a legacy-format stub.
This fixture is the foundation for Layer 4 (migrator) tests.
EOF
)"
```

---

## Task 2: `shows.py` — Show dataclass and validators

**Goal:** implement `Show`, `validate_shows`, `load_shows`, show-config error classes.

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/shows.py`
- Create: `plugins/kb/skills/kb-publish/scripts/tests/test_shows.py`

- [ ] **Step 1: Write failing tests for `Show` + `validate_shows`**

```python
# test_shows.py
"""Tests for shows.py — Show dataclass, EpRef, resolvers, validators."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import shows as S


# ------------------------------
# Show dataclass + validate_shows
# ------------------------------

def _valid_show_dict(show_id: str = "quanzhan-ai") -> dict:
    return {
        "id": show_id,
        "title": "全栈AI",
        "description": "Test",
        "language": "zh_Hans",
        "hosts": ["A", "B"],
        "extra_host_names": [],
        "intro_music": "/dev/null/intro.mp3",
        "intro_music_length_seconds": 12,
        "intro_crossfade_seconds": 3,
        "podcast_format": "deep-dive",
        "podcast_length": "long",
        "transcript": {"enabled": True, "model": "large-v3", "device": "auto", "language": "zh"},
        "episodes_registry": "episodes.yaml",
        "wiki_episodes_dir": f"episodes/{show_id}",
        # podcast_id parameterized on show_id so multi-show fixtures don't
        # incidentally trip the uniqueness check.
        "xiaoyuzhou": {"podcast_id": f"pod-{show_id}"},
    }


def test_validate_shows_accepts_single_valid_show(tmp_path: Path):
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    shows = S.validate_shows([_valid_show_dict()], project_root=tmp_path, wiki_path=wiki_path)
    assert len(shows) == 1
    assert shows[0].id == "quanzhan-ai"
    assert shows[0].wiki_episodes_dir == "episodes/quanzhan-ai"


def test_validate_shows_rejects_empty_list(tmp_path: Path):
    with pytest.raises(S.ShowConfigError, match="at least one"):
        S.validate_shows([], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_duplicate_id(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    # Two shows with same id
    s1 = _valid_show_dict("show-a")
    s2 = _valid_show_dict("show-a")
    # Make their registry paths and wiki_episodes_dir different so that's not the failure reason
    s2["episodes_registry"] = "episodes-2.yaml"
    s2["wiki_episodes_dir"] = "episodes/show-a"  # same dir — will collide too
    with pytest.raises(S.ShowConfigError, match="duplicate"):
        S.validate_shows([s1, s2], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_bad_id_format(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    bad = _valid_show_dict("Invalid_ID")
    with pytest.raises(S.ShowConfigError, match="id.*pattern"):
        S.validate_shows([bad], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_non_conventional_wiki_episodes_dir(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    bad = _valid_show_dict("show-a")
    bad["wiki_episodes_dir"] = "custom/path"  # not episodes/<id>
    with pytest.raises(S.ShowConfigError, match="wiki_episodes_dir"):
        S.validate_shows([bad], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_escape_in_wiki_episodes_dir(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    bad = _valid_show_dict("show-a")
    bad["wiki_episodes_dir"] = "../escape"
    with pytest.raises(S.ShowConfigError):
        S.validate_shows([bad], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_rejects_multiple_defaults(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    s1 = _valid_show_dict("a")
    s1["default"] = True
    s1["episodes_registry"] = "episodes-a.yaml"
    s2 = _valid_show_dict("b")
    s2["default"] = True
    s2["episodes_registry"] = "episodes-b.yaml"
    with pytest.raises(S.ShowConfigError, match="one show.*default"):
        S.validate_shows([s1, s2], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_validate_shows_allows_zero_defaults(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    s1 = _valid_show_dict("a")
    s1["episodes_registry"] = "episodes-a.yaml"
    s2 = _valid_show_dict("b")
    s2["episodes_registry"] = "episodes-b.yaml"
    shows = S.validate_shows([s1, s2], project_root=tmp_path, wiki_path=tmp_path / "wiki")
    assert len(shows) == 2


def test_validate_shows_rejects_duplicate_episodes_registry(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    s1 = _valid_show_dict("a")
    s2 = _valid_show_dict("b")
    # Both use "episodes.yaml" (default)
    with pytest.raises(S.ShowConfigError, match="episodes_registry.*duplicate"):
        S.validate_shows([s1, s2], project_root=tmp_path, wiki_path=tmp_path / "wiki")


def test_load_shows_reads_from_kb_yaml(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    kb = {
        "integrations": {
            "notebooklm": {"wiki_path": str(tmp_path / "wiki")},
            "shows": [_valid_show_dict()],
        }
    }
    shows = S.load_shows(kb, project_root=tmp_path)
    assert len(shows) == 1
    assert shows[0].id == "quanzhan-ai"


def test_load_shows_raises_when_missing(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    kb = {"integrations": {"notebooklm": {"wiki_path": str(tmp_path / "wiki")}}}
    with pytest.raises(S.ShowConfigError):
        S.load_shows(kb, project_root=tmp_path)
```

- [ ] **Step 2: Run tests — expect `ModuleNotFoundError: shows`**

```bash
cd /Users/dragon/PycharmProjects/llm-kb-skills
source ~/notebooklm-py/.venv/bin/activate
pytest plugins/kb/skills/kb-publish/scripts/tests/test_shows.py -v
```

- [ ] **Step 3: Implement `shows.py` — Show dataclass and validators**

Write `plugins/kb/skills/kb-publish/scripts/shows.py`:

```python
"""Multi-show podcast support: Show dataclass, EpRef value object,
resolvers, validators.

See docs/superpowers/specs/2026-04-23-multi-show-podcast-support-design.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_ID_PATTERN = re.compile(r"^[a-z][a-z0-9\-]{0,31}$")


class ShowConfigError(ValueError):
    """Raised on any show-config validation failure."""


class ShowNotFoundError(ShowConfigError):
    """Requested show id is not configured."""


class AmbiguousShowError(ShowConfigError):
    """Multi-show KB without --show flag on a mutating command."""


class UnknownShowError(ShowConfigError):
    """EpRef.show not in known_shows set."""


class ShowMismatchError(ShowConfigError):
    """Sidecar manifest `show:` conflicts with the --show flag or resolved show."""


class MigrationRequiredError(RuntimeError):
    """Legacy str/int episode ref encountered at runtime — /kb migrate is required."""


@dataclass(frozen=True)
class Show:
    id: str
    title: str
    description: str
    default: bool
    language: str
    hosts: list[str]
    extra_host_names: list[str]
    intro_music: str | None
    intro_music_length_seconds: float
    intro_crossfade_seconds: float
    podcast_format: str
    podcast_length: str
    transcript: dict          # {enabled, model, device, language}
    episodes_registry: str    # project-root-relative
    wiki_episodes_dir: str    # wiki-root-relative, always equals "episodes/{id}"
    xiaoyuzhou: dict          # {podcast_id: str | None}

    def __post_init__(self):
        # Enforce the wiki_episodes_dir invariant at construction time.
        expected = f"episodes/{self.id}"
        if self.wiki_episodes_dir != expected:
            raise ShowConfigError(
                f"show {self.id!r}: wiki_episodes_dir must equal {expected!r}, "
                f"got {self.wiki_episodes_dir!r}"
            )


def validate_shows(
    shows_raw: list[dict],
    *,
    project_root: Path,
    wiki_path: Path,
) -> list[Show]:
    """Validate raw show dicts from kb.yaml; return typed Show objects.

    Raises ShowConfigError on any violation. Reports ALL violations at once
    (not first-failure-only).
    """
    errors: list[str] = []

    if not isinstance(shows_raw, list) or not shows_raw:
        raise ShowConfigError("integrations.shows must be a non-empty list")

    seen_ids: set[str] = set()
    seen_registries: set[str] = set()
    seen_wiki_dirs: set[str] = set()
    seen_podcast_ids: set[str] = set()
    shows: list[Show] = []

    defaults_count = 0

    for i, raw in enumerate(shows_raw):
        if not isinstance(raw, dict):
            errors.append(f"shows[{i}] is not a dict")
            continue

        show_id = raw.get("id")
        if not isinstance(show_id, str) or not _ID_PATTERN.match(show_id):
            errors.append(f"shows[{i}].id={show_id!r} must match pattern {_ID_PATTERN.pattern}")
            continue

        if show_id in seen_ids:
            errors.append(f"duplicate show id {show_id!r}")
            continue
        seen_ids.add(show_id)

        if raw.get("default") is True:
            defaults_count += 1

        # wiki_episodes_dir: must equal episodes/<id>
        wed = raw.get("wiki_episodes_dir", f"episodes/{show_id}")
        expected_wed = f"episodes/{show_id}"
        if wed != expected_wed:
            errors.append(
                f"shows[{i}].wiki_episodes_dir={wed!r} must equal {expected_wed!r}"
            )
            continue

        # Escape check (should be impossible given the above, but be defensive)
        if ".." in wed.split("/") or wed.startswith("/"):
            errors.append(f"shows[{i}].wiki_episodes_dir must not contain '..' or be absolute")
            continue

        # Uniqueness checks
        registry = raw.get("episodes_registry", "episodes.yaml")
        if registry in seen_registries:
            errors.append(f"episodes_registry {registry!r} duplicate across shows")
            continue
        seen_registries.add(registry)

        if wed in seen_wiki_dirs:
            errors.append(f"wiki_episodes_dir {wed!r} duplicate across shows")
            continue
        seen_wiki_dirs.add(wed)

        xiaoyu = raw.get("xiaoyuzhou") or {}
        pod_id = xiaoyu.get("podcast_id")
        if pod_id:
            if pod_id in seen_podcast_ids:
                errors.append(f"xiaoyuzhou.podcast_id {pod_id!r} duplicate across shows")
                continue
            seen_podcast_ids.add(pod_id)

        try:
            show = Show(
                id=show_id,
                title=str(raw.get("title", "")),
                description=str(raw.get("description", "")),
                default=bool(raw.get("default", False)),
                language=str(raw.get("language", "en")),
                hosts=list(raw.get("hosts") or []),
                extra_host_names=list(raw.get("extra_host_names") or []),
                intro_music=raw.get("intro_music"),
                intro_music_length_seconds=float(raw.get("intro_music_length_seconds", 12)),
                intro_crossfade_seconds=float(raw.get("intro_crossfade_seconds", 3)),
                podcast_format=str(raw.get("podcast_format", "deep-dive")),
                podcast_length=str(raw.get("podcast_length", "long")),
                transcript=dict(raw.get("transcript") or {}),
                episodes_registry=registry,
                wiki_episodes_dir=wed,
                xiaoyuzhou=dict(xiaoyu),
            )
            shows.append(show)
        except Exception as e:
            errors.append(f"shows[{i}] construction failed: {e}")

    if defaults_count > 1:
        errors.append(f"only one show may be marked default; found {defaults_count}")

    if errors:
        raise ShowConfigError("\n".join(errors))

    return shows


def load_shows(kb_yaml: dict, project_root: Path) -> list[Show]:
    """Load and validate `integrations.shows[]` from parsed kb.yaml.

    Reads `integrations.notebooklm.wiki_path` for the wiki root.
    """
    integrations = kb_yaml.get("integrations") or {}
    notebooklm = integrations.get("notebooklm") or {}
    wiki_path_str = notebooklm.get("wiki_path")
    if not wiki_path_str:
        raise ShowConfigError(
            "integrations.notebooklm.wiki_path is required but missing"
        )
    wiki_path = Path(wiki_path_str)
    shows_raw = integrations.get("shows")
    if shows_raw is None:
        raise ShowConfigError(
            "integrations.shows is missing — run `/kb migrate` to convert a single-show KB"
        )
    return validate_shows(shows_raw, project_root=project_root, wiki_path=wiki_path)
```

- [ ] **Step 4: Run tests — expect all green**

```bash
pytest plugins/kb/skills/kb-publish/scripts/tests/test_shows.py -v
```

All 10 tests should pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/shows.py plugins/kb/skills/kb-publish/scripts/tests/test_shows.py
git commit -m "$(cat <<'EOF'
feat(kb-publish): shows.py — Show dataclass + validators

Implements the per-spec Show dataclass (frozen, enforces
wiki_episodes_dir == episodes/<id> at construction) and
validate_shows/load_shows functions that aggregate all validation
errors before raising. Unit tests cover: accept single/multiple
valid shows, reject empty list, duplicate id, bad id format,
non-conventional wiki_episodes_dir, duplicate registry paths,
multiple defaults, zero defaults (allowed), path escape.

10 tests pass.
EOF
)"
```

---

## Task 3: `EpRef` value object + `parse_ep_ref_field` resolvers

**Goal:** add `EpRef` dataclass, `resolve_show_for_mutation`, `resolve_show_for_read`, `parse_ep_ref_field`.

**Files:**
- Modify: `plugins/kb/skills/kb-publish/scripts/shows.py` (append)
- Modify: `plugins/kb/skills/kb-publish/scripts/tests/test_shows.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `test_shows.py`:

```python
# ------------------------------
# EpRef
# ------------------------------

def test_epref_from_dict_valid():
    r = S.EpRef.from_dict({"show": "quanzhan-ai", "ep": 3})
    assert r.show == "quanzhan-ai"
    assert r.ep == 3


def test_epref_from_dict_raises_on_missing_fields():
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": "a"})
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"ep": 1})
    with pytest.raises(ValueError):
        S.EpRef.from_dict({})


def test_epref_from_dict_raises_on_wrong_types():
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": 123, "ep": 1})
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": "a", "ep": "not-a-number"})
    with pytest.raises(ValueError):
        S.EpRef.from_dict({"show": "a", "ep": 0})  # ep must be >= 1


def test_epref_from_legacy_str():
    r = S.EpRef.from_legacy("ep-3", default_show="quanzhan-ai")
    assert r.show == "quanzhan-ai" and r.ep == 3


def test_epref_from_legacy_bare_int():
    r = S.EpRef.from_legacy(5, default_show="my-show")
    assert r.show == "my-show" and r.ep == 5


def test_epref_from_legacy_rejects_bad_str():
    with pytest.raises(ValueError):
        S.EpRef.from_legacy("episode-3", default_show="x")
    with pytest.raises(ValueError):
        S.EpRef.from_legacy("ep-notanum", default_show="x")


def test_epref_to_dict_roundtrip():
    r = S.EpRef(show="a", ep=2)
    assert r.to_dict() == {"show": "a", "ep": 2}
    r2 = S.EpRef.from_dict(r.to_dict())
    assert r == r2


def test_epref_wikilink_stem():
    r = S.EpRef(show="quanzhan-ai", ep=3)
    assert r.wikilink_stem("kv-cache") == "wiki/episodes/quanzhan-ai/ep-3-kv-cache"


def test_parse_ep_ref_field_valid():
    r = S.parse_ep_ref_field({"show": "quanzhan-ai", "ep": 1}, known_shows={"quanzhan-ai"})
    assert r.show == "quanzhan-ai" and r.ep == 1


def test_parse_ep_ref_field_rejects_legacy_str():
    with pytest.raises(S.MigrationRequiredError):
        S.parse_ep_ref_field("ep-1", known_shows={"quanzhan-ai"})


def test_parse_ep_ref_field_rejects_legacy_int():
    with pytest.raises(S.MigrationRequiredError):
        S.parse_ep_ref_field(1, known_shows={"quanzhan-ai"})


def test_parse_ep_ref_field_raises_on_unknown_show():
    with pytest.raises(S.UnknownShowError):
        S.parse_ep_ref_field({"show": "other", "ep": 1}, known_shows={"quanzhan-ai"})


# ------------------------------
# Resolvers
# ------------------------------

def _make_shows(ids: list[str]) -> list[S.Show]:
    """Helper to build real Show objects for resolver tests."""
    shows = []
    for i, sid in enumerate(ids):
        shows.append(S.Show(
            id=sid, title=sid.title(), description="",
            default=False, language="zh_Hans",
            hosts=["A", "B"], extra_host_names=[],
            intro_music=None,
            intro_music_length_seconds=12, intro_crossfade_seconds=3,
            podcast_format="deep-dive", podcast_length="long",
            transcript={"enabled": False, "model": "", "device": "auto", "language": "zh"},
            episodes_registry=f"episodes-{sid}.yaml" if i > 0 else "episodes.yaml",
            wiki_episodes_dir=f"episodes/{sid}",
            xiaoyuzhou={},
        ))
    return shows


def test_resolve_mutation_single_show_implicit():
    shows = _make_shows(["a"])
    assert S.resolve_show_for_mutation(shows, None).id == "a"


def test_resolve_mutation_single_show_explicit():
    shows = _make_shows(["a"])
    assert S.resolve_show_for_mutation(shows, "a").id == "a"


def test_resolve_mutation_single_show_unknown_id():
    shows = _make_shows(["a"])
    with pytest.raises(S.ShowNotFoundError):
        S.resolve_show_for_mutation(shows, "other")


def test_resolve_mutation_multi_show_no_flag_is_error():
    shows = _make_shows(["a", "b"])
    with pytest.raises(S.AmbiguousShowError):
        S.resolve_show_for_mutation(shows, None)


def test_resolve_mutation_multi_show_explicit_selects():
    shows = _make_shows(["a", "b"])
    assert S.resolve_show_for_mutation(shows, "b").id == "b"


def test_resolve_read_single_show_implicit():
    shows = _make_shows(["a"])
    assert S.resolve_show_for_read(shows, None).id == "a"


def test_resolve_read_multi_show_no_flag_returns_none():
    shows = _make_shows(["a", "b"])
    assert S.resolve_show_for_read(shows, None) is None


def test_resolve_read_multi_show_explicit_selects():
    shows = _make_shows(["a", "b"])
    assert S.resolve_show_for_read(shows, "a").id == "a"
```

- [ ] **Step 2: Run tests — expect failures on `EpRef`, `parse_ep_ref_field`, resolvers**

```bash
pytest plugins/kb/skills/kb-publish/scripts/tests/test_shows.py -v
```

- [ ] **Step 3: Append `EpRef` + resolvers to `shows.py`**

Append to `shows.py`:

```python
@dataclass(frozen=True)
class EpRef:
    """Reference to a specific episode of a specific show."""
    show: str
    ep: int

    def __post_init__(self):
        if not isinstance(self.show, str) or not self.show:
            raise ValueError(f"EpRef.show must be a non-empty string: {self.show!r}")
        if not isinstance(self.ep, int) or self.ep < 1:
            raise ValueError(f"EpRef.ep must be a positive int: {self.ep!r}")

    def to_dict(self) -> dict:
        return {"show": self.show, "ep": self.ep}

    def wikilink_stem(self, slug: str) -> str:
        """Return the path-without-.md used inside [[ ]] wikilinks.

        The Obsidian wikilink stem is conventional: wiki/episodes/<show>/ep-<N>-<slug>,
        matching the default wiki_episodes_dir layout.
        """
        return f"wiki/episodes/{self.show}/ep-{self.ep}-{slug}"

    @classmethod
    def from_dict(cls, d: Any) -> "EpRef":
        """Strict parse of a dict-form EpRef. Raises on missing/bad fields."""
        if not isinstance(d, dict):
            raise ValueError(f"EpRef expects a dict, got {type(d).__name__}")
        show = d.get("show")
        ep = d.get("ep")
        if not isinstance(show, str) or not show:
            raise ValueError(f"EpRef.show must be a non-empty string: {d}")
        if not isinstance(ep, int) or ep < 1:
            raise ValueError(f"EpRef.ep must be a positive int: {d}")
        return cls(show=show, ep=ep)

    @classmethod
    def from_legacy(cls, value: Any, *, default_show: str) -> "EpRef":
        """Parse a legacy str 'ep-N' or bare int N as default_show's ref.
        ONLY used by the migrator."""
        if isinstance(value, int):
            if value < 1:
                raise ValueError(f"legacy int ref must be >= 1: {value}")
            return cls(show=default_show, ep=value)
        if isinstance(value, str):
            m = re.match(r"^ep-(\d+)$", value)
            if not m:
                raise ValueError(f"legacy ref must match 'ep-N': {value!r}")
            return cls(show=default_show, ep=int(m.group(1)))
        raise ValueError(f"legacy ref must be str or int: {value!r}")


def parse_ep_ref_field(value: Any, *, known_shows: set[str]) -> EpRef:
    """Strict parse of a dict-form EpRef with REFERENTIAL validation.

    Raises:
      - MigrationRequiredError on legacy str / int
      - ValueError on missing/wrong-typed fields
      - UnknownShowError on ref.show not in known_shows
    """
    if isinstance(value, (str, int)):
        raise MigrationRequiredError(
            f"legacy episode ref {value!r} — run `/kb migrate` to convert"
        )
    ref = EpRef.from_dict(value)
    if ref.show not in known_shows:
        raise UnknownShowError(
            f"EpRef.show={ref.show!r} not in configured shows {sorted(known_shows)}"
        )
    return ref


def resolve_show_for_mutation(
    shows: list[Show],
    show_id: str | None,
) -> Show:
    """Resolver for mutating commands.

    - single-show + None → shows[0]
    - single-show + explicit → matched (or ShowNotFoundError)
    - multi-show + None → AmbiguousShowError
    - multi-show + explicit → matched (or ShowNotFoundError)
    """
    if show_id is not None:
        for show in shows:
            if show.id == show_id:
                return show
        available = ", ".join(sorted(s.id for s in shows))
        raise ShowNotFoundError(
            f"show {show_id!r} not configured. Available: {available}"
        )
    if len(shows) == 1:
        return shows[0]
    ids = ", ".join(sorted(s.id for s in shows))
    raise AmbiguousShowError(
        f"multiple shows configured ({ids}); --show is required"
    )


def resolve_show_for_read(
    shows: list[Show],
    show_id: str | None,
) -> Show | None:
    """Resolver for read-all commands.

    - single-show + None → shows[0]
    - single-show + explicit → matched (or ShowNotFoundError)
    - multi-show + None → None (signal: iterate all shows)
    - multi-show + explicit → matched (or ShowNotFoundError)
    """
    if show_id is not None:
        for show in shows:
            if show.id == show_id:
                return show
        available = ", ".join(sorted(s.id for s in shows))
        raise ShowNotFoundError(
            f"show {show_id!r} not configured. Available: {available}"
        )
    if len(shows) == 1:
        return shows[0]
    return None
```

- [ ] **Step 4: Run tests — all green**

```bash
pytest plugins/kb/skills/kb-publish/scripts/tests/test_shows.py -v
```

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/shows.py plugins/kb/skills/kb-publish/scripts/tests/test_shows.py
git commit -m "$(cat <<'EOF'
feat(kb-publish): shows.py — EpRef, resolvers, parse_ep_ref_field

Adds the EpRef value object, from_dict/from_legacy parsers,
wikilink_stem helper, plus the two canonical resolvers
(resolve_show_for_mutation / resolve_show_for_read) and the
referential parse_ep_ref_field. Legacy str/int refs at runtime
trigger MigrationRequiredError.

Test coverage: from_dict validation, from_legacy (str + int) with
error cases, to_dict roundtrip, wikilink_stem, parse_ep_ref_field
rejects legacy + unknown show, both resolvers cover single/multi
show × None/explicit cells of the resolution table.

~20 new tests pass (30 total).
EOF
)"
```

---

## Task 4: `lock.py` — KB-wide mutation lock

**Goal:** implement the `kb_mutation_lock()` context manager.

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/lock.py`
- Create: `plugins/kb/skills/kb-publish/scripts/tests/test_lock.py`

- [ ] **Step 1: Write failing tests**

```python
# test_lock.py
"""Tests for lock.py — KB-wide mutation file lock."""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import lock as L


def test_lock_acquires_and_releases(tmp_path: Path):
    lock_path = tmp_path / ".kb-mutation.lock"
    assert not lock_path.exists()
    with L.kb_mutation_lock(tmp_path, "test-cmd"):
        assert lock_path.exists()
        data = json.loads(lock_path.read_text())
        assert data["command"] == "test-cmd"
        assert data["pid"] == os.getpid()
    assert not lock_path.exists()


def test_lock_releases_on_exception(tmp_path: Path):
    lock_path = tmp_path / ".kb-mutation.lock"
    with pytest.raises(RuntimeError, match="boom"):
        with L.kb_mutation_lock(tmp_path, "test-cmd"):
            raise RuntimeError("boom")
    assert not lock_path.exists()


def test_lock_raises_when_held_by_live_process(tmp_path: Path):
    """Simulate another live process holding the lock."""
    lock_path = tmp_path / ".kb-mutation.lock"
    # Write a lock file claiming to be held by our own process (safe since os.kill(pid, 0) succeeds)
    lock_path.write_text(json.dumps({
        "pid": os.getpid(),
        "command": "other",
        "start_time": time.time(),
    }))
    with pytest.raises(L.LockBusyError, match="held by"):
        with L.kb_mutation_lock(tmp_path, "test-cmd", timeout=0.1):
            pass
    # Lock file is NOT removed when we refuse to acquire (it belongs to the other owner).
    assert lock_path.exists()


def test_lock_removes_stale_lock(tmp_path: Path, monkeypatch):
    """When the lock is owned by a dead PID, it's removed (with monkeypatched confirm)."""
    lock_path = tmp_path / ".kb-mutation.lock"
    # Pick a PID very unlikely to exist
    dead_pid = 999999
    lock_path.write_text(json.dumps({
        "pid": dead_pid,
        "command": "old",
        "start_time": time.time(),
    }))
    # Monkeypatch confirm → yes
    monkeypatch.setattr(L, "_confirm_remove_stale", lambda _: True)
    with L.kb_mutation_lock(tmp_path, "test-cmd"):
        assert lock_path.exists()
        data = json.loads(lock_path.read_text())
        assert data["command"] == "test-cmd"
    assert not lock_path.exists()


def test_lock_refuses_stale_removal_when_user_declines(tmp_path: Path, monkeypatch):
    lock_path = tmp_path / ".kb-mutation.lock"
    lock_path.write_text(json.dumps({"pid": 999999, "command": "old", "start_time": 0}))
    monkeypatch.setattr(L, "_confirm_remove_stale", lambda _: False)
    with pytest.raises(L.LockBusyError):
        with L.kb_mutation_lock(tmp_path, "test-cmd", timeout=0.1):
            pass
```

- [ ] **Step 2: Verify failure**

- [ ] **Step 3: Implement `lock.py`**

```python
"""KB-wide mutation file lock. Acquired by every mutating command
(kb-notebooklm, kb-publish, backfill-index, migrate) before writing
any state/sidecar/output file. Includes detached background agents.
"""
from __future__ import annotations

import errno
import json
import os
import signal
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


LOCK_FILENAME = ".kb-mutation.lock"


class LockBusyError(RuntimeError):
    """Lock is held by another live process."""


def _is_alive(pid: int) -> bool:
    """Check if a PID is alive via os.kill(pid, 0)."""
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno != errno.ESRCH  # ESRCH = no such process
    return True


def _confirm_remove_stale(lock_info: dict) -> bool:
    """Ask user whether to remove a stale lock file. Monkeypatched in tests."""
    # Default to stderr prompt — in practice the skill shells out interactively
    prompt = (
        f"\nStale .kb-mutation.lock found (pid={lock_info.get('pid')}, "
        f"command={lock_info.get('command')!r}, "
        f"started={lock_info.get('start_time')}). "
        f"Remove it? [y/N] "
    )
    sys.stderr.write(prompt)
    sys.stderr.flush()
    try:
        resp = input().strip().lower()
    except EOFError:
        return False
    return resp in ("y", "yes")


@contextmanager
def kb_mutation_lock(project_root: Path, command: str, *, timeout: float = 5.0):
    """Acquire .kb-mutation.lock; raise LockBusyError on timeout or if held
    by another live process.

    On acquisition, writes {pid, command, start_time} to the lock file.
    Released on normal exit, exception, SIGINT, or SIGTERM.
    """
    lock_path = project_root / LOCK_FILENAME
    deadline = time.monotonic() + timeout
    attempt = 0

    while True:
        attempt += 1
        try:
            # O_EXCL + O_CREAT = atomic create-if-not-exists
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, json.dumps({
                    "pid": os.getpid(),
                    "command": command,
                    "start_time": time.time(),
                }).encode())
            finally:
                os.close(fd)
            break
        except FileExistsError:
            # Lock exists — is it stale?
            try:
                info = json.loads(lock_path.read_text())
                owner_pid = info.get("pid")
            except (OSError, ValueError, json.JSONDecodeError):
                # Corrupted lock file — treat as stale
                info = {"pid": 0, "command": "<unreadable>"}
                owner_pid = 0

            if owner_pid and _is_alive(owner_pid):
                # Still held by a live process
                if time.monotonic() >= deadline:
                    raise LockBusyError(
                        f"{lock_path} held by pid={owner_pid} "
                        f"command={info.get('command')!r}"
                    )
                time.sleep(0.1)
                continue

            # Stale lock — ask the user (test can monkeypatch)
            if _confirm_remove_stale(info):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass  # another process got there first; loop around
            else:
                raise LockBusyError(
                    f"stale lock at {lock_path} (pid={owner_pid}) not removed"
                )

    # Install signal handlers to release on SIGINT/SIGTERM
    prev_sigint = signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    prev_sigterm = signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)
```

- [ ] **Step 4: Run tests — all green**

```bash
pytest plugins/kb/skills/kb-publish/scripts/tests/test_lock.py -v
```

5 tests should pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/lock.py plugins/kb/skills/kb-publish/scripts/tests/test_lock.py
git commit -m "$(cat <<'EOF'
feat(kb-publish): lock.py — KB-wide mutation file lock

kb_mutation_lock() context manager using atomic O_EXCL file create.
Released on normal exit + SIGINT + SIGTERM. Stale-lock detection
via os.kill(pid, 0); _confirm_remove_stale hook for interactive
removal (monkeypatched in tests). Timeout-on-busy with configurable
deadline.

Tests: happy path acquire/release, release-on-exception, busy
live-PID raises LockBusyError, stale lock removal with user
confirmation, stale lock refusal when user declines.
EOF
)"
```

---

## Task 5: `state.py` — dual-format state loader + idle check

**Goal:** state file reader/writer that accepts both legacy flat and new show-scoped format; always writes new format. Add `idle_check()` that scans for pending runs.

**Files:**
- Create: `plugins/kb/skills/kb-publish/scripts/state.py`
- Create: `plugins/kb/skills/kb-publish/scripts/tests/test_state.py`

- [ ] **Step 1: Failing tests**

```python
# test_state.py
"""Tests for state.py — dual-format .notebooklm-state.yaml loader."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import state as ST


def _write_legacy_state(path: Path, runs: list[dict] = None, notebooks: list[dict] = None):
    data = {
        "last_podcast": None,
        "last_digest": None,
        "last_quiz": None,
        "notebooks": notebooks or [],
        "runs": runs or [],
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _write_new_state(path: Path, shows_data: dict):
    data = {"shows": shows_data}
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_load_state_legacy_format(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_legacy_state(p, runs=[{"workflow": "podcast", "status": "completed"}])
    state = ST.load_state_file(p, default_show_id="quanzhan-ai")
    # Legacy → wrap under shows.<default-show-id>
    assert "shows" in state
    assert "quanzhan-ai" in state["shows"]
    assert state["shows"]["quanzhan-ai"]["runs"][0]["workflow"] == "podcast"
    assert state["shows"]["quanzhan-ai"]["last_podcast"] is None


def test_load_state_new_format(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_new_state(p, {
        "quanzhan-ai": {
            "last_podcast": None,
            "notebooks": [{"id": "nb1"}],
            "runs": [],
        }
    })
    state = ST.load_state_file(p, default_show_id="unused")
    assert state["shows"]["quanzhan-ai"]["notebooks"][0]["id"] == "nb1"


def test_load_state_missing_file_returns_empty(tmp_path: Path):
    p = tmp_path / "missing.yaml"
    state = ST.load_state_file(p, default_show_id="quanzhan-ai")
    assert state == {"shows": {}}


def test_write_state_always_new_format(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    state = {"shows": {"a": {"runs": [{"x": 1}]}}}
    ST.write_state_file(p, state)
    parsed = yaml.safe_load(p.read_text())
    assert "shows" in parsed
    assert "last_podcast" not in parsed  # no legacy top-level keys


def test_roundtrip_legacy_to_new(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_legacy_state(p, runs=[{"w": "podcast"}])
    state = ST.load_state_file(p, default_show_id="show-a")
    ST.write_state_file(p, state)
    # Now re-load: should still succeed as new format
    state2 = ST.load_state_file(p, default_show_id="show-a")
    assert state2["shows"]["show-a"]["runs"][0]["w"] == "podcast"
    # And the file now has `shows:` at top
    parsed = yaml.safe_load(p.read_text())
    assert "shows" in parsed
    assert "runs" not in parsed  # old flat key gone


def test_idle_check_finds_pending_runs_legacy(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_legacy_state(p, runs=[{"status": "pending", "workflow": "podcast"}])
    state = ST.load_state_file(p, default_show_id="x")
    pending = ST.find_pending_runs(state)
    assert len(pending) == 1
    assert pending[0]["workflow"] == "podcast"


def test_idle_check_finds_pending_notebooks_across_shows(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_new_state(p, {
        "show-a": {"notebooks": [{"id": "nb1", "status": "pending"}], "runs": []},
        "show-b": {"notebooks": [], "runs": [{"workflow": "quiz", "status": "pending"}]},
    })
    state = ST.load_state_file(p, default_show_id="x")
    pending_nb = ST.find_pending_notebooks(state)
    pending_runs = ST.find_pending_runs(state)
    assert len(pending_nb) == 1
    assert len(pending_runs) == 1


def test_idle_check_returns_empty_when_idle(tmp_path: Path):
    p = tmp_path / ".notebooklm-state.yaml"
    _write_new_state(p, {
        "show-a": {"notebooks": [], "runs": [{"status": "completed"}]},
    })
    state = ST.load_state_file(p, default_show_id="x")
    assert ST.find_pending_runs(state) == []
    assert ST.find_pending_notebooks(state) == []
```

- [ ] **Step 2: Verify failure**

- [ ] **Step 3: Implement `state.py`**

```python
"""Dual-format state file loader for .notebooklm-state.yaml.

Reads both the legacy flat format and the new shows-scoped format;
always writes the new format. Also provides idle-check helpers used
by the migrator and detached background agents.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def load_state_file(path: Path, *, default_show_id: str) -> dict:
    """Load state file; return dict with top-level `shows` key.

    If the file is in legacy format (top-level `runs`/`notebooks`/`last_*`),
    the loader wraps those under `shows.<default_show_id>.*`. If already
    new format (top-level `shows:`), returns as-is.

    Missing file returns `{"shows": {}}`.
    """
    if not path.exists():
        return {"shows": {}}

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} does not contain a dict")

    if "shows" in raw:
        # New format — ensure every show's state has runs/notebooks keys
        shows = raw.get("shows") or {}
        for sid, show_state in shows.items():
            show_state.setdefault("runs", [])
            show_state.setdefault("notebooks", [])
        return {"shows": shows}

    # Legacy: wrap top-level keys under shows.<default_show_id>
    return {
        "shows": {
            default_show_id: {
                "last_podcast": raw.get("last_podcast"),
                "last_digest": raw.get("last_digest"),
                "last_quiz": raw.get("last_quiz"),
                "notebooks": raw.get("notebooks") or [],
                "runs": raw.get("runs") or [],
            }
        }
    }


def write_state_file(path: Path, state: dict) -> None:
    """Always write new format. Atomic via temp + os.replace."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=str(path.parent), delete=False,
        prefix=path.name + ".", suffix=".tmp", encoding="utf-8",
    )
    try:
        yaml.safe_dump(state, tmp, default_flow_style=False, allow_unicode=True, sort_keys=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


def find_pending_runs(state: dict) -> list[dict]:
    """Return every run entry with status=pending across all shows."""
    pending = []
    for sid, show_state in (state.get("shows") or {}).items():
        for run in (show_state.get("runs") or []):
            if run.get("status") == "pending":
                pending.append({"show": sid, **run})
    return pending


def find_pending_notebooks(state: dict) -> list[dict]:
    """Return every notebook entry with status=pending across all shows."""
    pending = []
    for sid, show_state in (state.get("shows") or {}).items():
        for nb in (show_state.get("notebooks") or []):
            if nb.get("status") == "pending":
                pending.append({"show": sid, **nb})
    return pending


class PendingWorkError(RuntimeError):
    """Idle-check found pending runs or notebooks; migration refused."""
```

- [ ] **Step 4: Run tests — all green**

- [ ] **Step 5: Commit**

```bash
git add plugins/kb/skills/kb-publish/scripts/state.py plugins/kb/skills/kb-publish/scripts/tests/test_state.py
git commit -m "$(cat <<'EOF'
feat(kb-publish): state.py — dual-format state loader + idle-check

Dual-format loader reads legacy flat shape (top-level runs/notebooks/
last_*) or new shows-scoped shape. Always writes new format. Atomic
via temp + os.replace. Idle-check helpers find pending runs and
notebooks across all shows.

Tests: legacy load wraps under default show, new format passes
through, missing file returns empty, always-new-format write,
legacy→new roundtrip, pending-scan works in both formats and across
multiple shows.
EOF
)"
```

---

## Tasks 6–25: condensed outline

The remaining 20 tasks follow the same TDD pattern and the contracts table is the authoritative reference. Rather than inline ~600 more lines of boilerplate that would dilute the plan, each remaining task is specified by:

- **Goal** (1 line)
- **Files** (create/modify with exact paths)
- **Tests to add** (test names + behavior)
- **Implementation notes** (key functions + signatures — taken from the contracts table)
- **Commit message template**

The subagent executing each task pulls the exact test code from the spec (§11 lists every required test) and writes it before implementation. Contracts table above is load-bearing: any deviation is a spec bug to flag, not a shortcut.

---

## Task 6: `episode_wiki.py` — new `scan_episode_wiki(wiki_path, show)` + `resolve_episode_wikilink` + `validate_body_wikilinks`

- **Goal:** update `scan_episode_wiki` to take `wiki_path` + `Show` (not `wiki_dir`), walk `<wiki_path>/<show.wiki_episodes_dir>`. Add `resolve_episode_wikilink(ref: EpRef, shows_by_id: dict[str, Show], wiki_path: Path) -> str` for generating body wikilinks from an EpRef. Add `validate_body_wikilinks(text: str, known_shows: set[str]) -> list[str]` that returns error strings for any legacy-format `[[wiki/episodes/ep-N-...]]` wikilinks (must use `[[wiki/episodes/<show>/ep-N-...]]`).
- **Files:** modify `plugins/kb/skills/kb-publish/scripts/episode_wiki.py`; update `plugins/kb/skills/kb-publish/scripts/tests/test_episode_wiki.py`.
- **Tests to add:** existing tests migrated to new signature; new test: single-show KB finds only that show's episodes; multi-show KB's scan for show A does not leak show B's episodes; `resolve_episode_wikilink` looks up the file on disk and returns `wiki/episodes/<show>/ep-<N>-<slug>`; `resolve_episode_wikilink` raises `UnknownShowError` on unknown show; `resolve_episode_wikilink` raises `FileNotFoundError` when no `ep-<N>-*.md` file exists; `validate_body_wikilinks` flags legacy pattern; `validate_body_wikilinks` passes the new pattern; `validate_body_wikilinks` flags wikilinks to unknown shows.
- **Implementation:** `scan_episode_wiki`: compute `episodes_dir = wiki_path / show.wiki_episodes_dir`; glob `ep-*.md` there. `resolve_episode_wikilink`: look up `shows_by_id[ref.show]` (raise `UnknownShowError` on miss); glob `wiki_path / show.wiki_episodes_dir / f"ep-{ref.ep}-*.md"`; extract slug from the filename stem (strip `ep-<N>-` prefix); return `ref.wikilink_stem(slug)`. `validate_body_wikilinks` regex-scans `\[\[wiki/episodes/(?:ep-\d+|[a-z][a-z0-9-]*/ep-\d+)` and validates any captured show token against `known_shows`.
- **Commit:** `feat(kb-publish): scan_episode_wiki/resolve_episode_wikilink/validate_body_wikilinks show-scoped`

## Task 7: `episode_wiki.py` — `compute_depth_deltas` emits `{show, ep}`, raises `MixedShowCoverageError`

- **Goal:** output `prior_episode_ref` as `{show, ep}` dict (not int); raise `MixedShowCoverageError` when the caller passes an `indexed` list containing any entry whose `show_id != current_episode_show_id`. `MixedShowCoverageError` is defined in `episode_wiki.py` (subclassing `shows.ShowConfigError`) and exported.
- **Coverage-map data shape (extended):** `IndexedEpisode` gains a `show_id: str` field populated by `scan_episode_wiki` (from the passed `Show.id`). `compute_depth_deltas` takes `(current_episode_show_id: str, current_concepts: list[dict], indexed: list[IndexedEpisode]) -> list[dict]`.
- **Semantics — hard fail on mixed-show input:** the function does NOT silently filter. At entry, it validates that every `indexed[i].show_id == current_episode_show_id`; if any entry disagrees, raise `MixedShowCoverageError(f"coverage_map contains show {other!r}, expected {current_episode_show_id!r}")`. Callers (SKILL.md step 5b and similar) are responsible for scoping `indexed` to the current show via `scan_episode_wiki(show=current_show)` before calling — this surfaces caller bugs loudly instead of masking them.
- **Files:** modify `episode_wiki.py`; update tests.
- **Tests:** new-path emits dict with `{show: current_episode_show_id, ep: <N>}`; a single foreign `indexed` entry raises `MixedShowCoverageError`; tie-break is lowest-ep-id within-show; `prior_episode_ref` is `None` when no prior coverage; `IndexedEpisode.show_id` is populated from the Show passed to `scan_episode_wiki`.
- **Commit:** `feat(kb-publish): compute_depth_deltas emits EpRef dict, rejects mixed-show`

## Task 8: `episode_wiki.py` — stub + episode article YAML writes use new dict form

- **Goal:** `render_stub`, `render_episode_wiki`, `compute_stub_update` emit `{show, ep}` dicts for all episode refs. The `Show` must flow through these helpers.
- **Files:** modify `episode_wiki.py` + tests.
- **Tests:** stub frontmatter contains dict form; episode article `prior_episode_ref` + `series_links.builds_on` are dicts; compute_stub_update merges correctly with `EpRef`.
- **Commit:** `feat(kb-publish): stub + episode article renderers emit EpRef dicts`

## Task 9: `episode_wiki.py` — parse new dict form on read; raise `MigrationRequiredError` on legacy

- **Goal:** `_parse_episode_article` + stub readers use `parse_ep_ref_field`; legacy str/int triggers `MigrationRequiredError`.
- **Files:** modify `episode_wiki.py` + tests.
- **Tests:** new format parses cleanly; legacy `prior_episode_ref: 3` raises; legacy `created_by: "ep-1"` raises; unknown show raises `UnknownShowError`.
- **Commit:** `feat(kb-publish): runtime readers require migrated EpRef dict form`

## Task 10: `backfill_index.py` — `--show` flag + show-aware resolution + lock

- **Goal:** add `--show` flag; resolve via `resolve_show_for_mutation`; acquire `kb_mutation_lock`; pass resolved Show through to `orchestrate_episode_index`.
- **Files:** modify `backfill_index.py` + `test_backfill_index.py`.
- **Tests:** single-show + no flag → implicit; multi-show + no flag → AmbiguousShowError; explicit --show matches; unknown --show → ShowNotFoundError; lock is acquired before any write.
- **Commit:** `feat(kb-publish): backfill_index --show flag + mutation lock`

## Task 11: `transcribe_audio.py` — make `--title` required

- **Goal:** remove the `derive_title()` fallback; make `--title` required. Update `derive_title`-related tests to assert error-on-missing.
- **Files:** modify `plugins/kb/skills/kb-notebooklm/scripts/transcribe_audio.py`; update `test_transcribe_audio.py`.
- **Tests:** invoking without `--title` exits with error; derive_title function and its tests are removed or made internal-only.
- **Commit:** `feat(kb-notebooklm): transcribe_audio --title is now required`

## Task 12: Prompt templates — replace hardcoded 全栈AI with `{show_title}` placeholder

- **Goal:** `podcast-tutor.md`, `dedup-judge.md`, `cover-style.md`, `episode-wiki-extract.md` use `{show_title}` and `{show_id}` placeholders. Skill call sites substitute from resolved Show.
- **Files:** modify each `.md` prompt template.
- **Tests:** grep for literal `全栈AI` in prompts returns zero matches. (Assertion added to `test_shows.py` or a new `test_prompt_branding.py`.)
- **Commit:** `feat(prompts): all prompts render brand from {show_title}, no hardcoded 全栈AI`

## Task 13: Migrator — detection tri-state

- **Goal:** `migrate_multi_show.py:classify_kb_state(project_root) -> Literal["unmigrated", "partially_migrated", "fully_migrated"]`. Full-tree scan.
- **Import hygiene:** `migrate_multi_show.py` imports shared helpers (`shows`, `state`, `lock`, `episode_wiki`) from the sibling kb-publish skill via a deterministic path-bump: `sys.path.insert(0, str(<repo>/plugins/kb/skills/kb-publish/scripts))`. For `plugins/kb/skills/kb/scripts/migrate_multi_show.py`, `Path(__file__).resolve().parents` is `[scripts, kb, skills, kb (plugin root), plugins, ...]`, so the correct hop is `Path(__file__).resolve().parents[2] / "kb-publish" / "scripts"`. IMPORTANT: the module itself must perform this `sys.path` insert at import time (before the `import shows` / `import lock` / `import state` / `import episode_wiki` lines) — the test conftest's sibling-path insert is for test harness convenience only, not a substitute.
- **Files:** create `plugins/kb/skills/kb/scripts/migrate_multi_show.py`; tests at `plugins/kb/skills/kb/scripts/tests/test_migrate_multi_show.py`.
- **Tests:** `pre_migration_kb` fixture → `unmigrated`; partially-migrated fixture (kb.yaml has shows[] but flat episode files remain) → `partially_migrated`; a fully-migrated fixture → `fully_migrated`; **standalone-import test**: spawn a subprocess with a clean `sys.path` (PYTHONPATH unset, no conftest) that runs `python -c "import migrate_multi_show; migrate_multi_show.classify_kb_state(Path('...'))"` — validates the module's own `sys.path` insert is correct without the test conftest masking the bug.
- **Commit:** `feat(kb): migrate — detection tri-state classifier`

## Task 14: Migrator — Phase A (plan + staging tree + snapshots)

- **Goal:** build `<project_root>/.kb-migration/` containing every artifact later phases need. Live tree is untouched.
- **Required artifacts under `<project_root>/.kb-migration/`:**
  - `plan.yaml` — `{default_show_id, default_show_title, default_show_hosts, wiki_path, output_path, commit_order: [<relative-path>, ...]}`. `commit_order` is the deterministic order Phase C walks (episode articles → stubs → kb.yaml last).
  - `staging/kb.yaml` — rewritten with `integrations.shows[0]` populated from the default-show CLI flags.
  - `staging/wiki/episodes/<show-id>/ep-N-<slug>.md` — every episode article, frontmatter refs AND body wikilinks converted to dict/show-scoped form.
  - `staging/wiki/**/<stub>.md` — every stub with dict-form `created_by/last_seen_by/best_depth_episode/referenced_by` AND body wikilinks rewritten.
  - `staging/.notebooklm-state.yaml` — new-format state file (dual-format loader handles legacy→new; writer re-serializes).
  - `before/` — snapshots of every live file about to change (episode articles, stubs, kb.yaml, `.notebooklm-state.yaml`, sidecars). Used by Phase A-bis restore and Phase C resume validation.
- **Body wikilink rewrite (new):** every `[[wiki/episodes/ep-N-<slug>]]` (or `[[wiki/episodes/ep-N-<slug>|display]]`) inside any `wiki/**/*.md` must be rewritten to `[[wiki/episodes/<default-show-id>/ep-N-<slug>]]` (display text preserved). Phase A scans `wiki/**/*.md` once; every file that matches at least one legacy pattern is treated as a migration target — it gets snapshotted to `before/`, staged to `staging/`, and added to `commit_order`. Files not in the episode/stub categories use the filename `staging/wiki/<relative-path>` and are committed via the same per-entry copy-then-verify-then-log-then-delete flow Phase C uses for episode articles (with no flat-vs-nested rename; destination path equals source path). Any wikilink whose `ep-N-<slug>` can't be resolved to a file on disk is a planning error and fails Phase A (staging cleaned up).
- **Files:** modify `migrate_multi_show.py`; tests.
- **Tests:**
  - fixture KB → `.kb-migration/staging/kb.yaml` has `shows[0].id == default_show_id`.
  - `.kb-migration/staging/wiki/episodes/<show-id>/ep-1-<slug>.md` exists and its frontmatter has dict-form `prior_episode_ref` / `series_links.builds_on`.
  - `.kb-migration/staging/wiki/**/<stub>.md` has dict-form stub frontmatter.
  - `.kb-migration/staging/.notebooklm-state.yaml` has `shows: { <show-id>: {...} }` top-level.
  - `.kb-migration/plan.yaml` exists with non-empty `commit_order`, matching the staged tree.
  - `.kb-migration/before/` contains byte-exact copies of every live file that will be rewritten (snapshot restore test).
  - `.kb-migration/before/manifest.yaml` records for each commit_order entry: `relative_path`, `existed_before: bool`, `sha256_before: str | null`, `sha256_staged: str`, `category: "episode"|"stub"|"state"|"kb"|"sidecar"|"other"`. Phase C uses this for the live-drift guard and to handle the "destination path was new" case explicitly.
  - Fixture with a flat body wikilink `[[wiki/episodes/ep-1-test]]` inside an episode article and inside a stub → both rewritten to `[[wiki/episodes/<show-id>/ep-1-test]]` in staging; display-text form `[[wiki/episodes/ep-1-test|nice name]]` → `[[wiki/episodes/<show-id>/ep-1-test|nice name]]`.
  - Fixture with a legacy wikilink inside a non-episode, non-stub wiki file (e.g. `wiki/notes/reading-list.md`) → rewritten in staging, added to `commit_order` + snapshotted to `before/` + recorded in manifest with `category: other`.
  - Fixture with a body wikilink to a non-existent `ep-99-<slug>` → Phase A raises with a clear error (unresolvable); staging is cleaned up so `.kb-migration/` is not left half-written.
- **Commit:** `feat(kb): migrate — Phase A (plan.yaml + staging + before/ snapshots)`

## Task 15: Migrator — Phase A-bis (sidecar in-place)

- **Goal:** snapshot every sidecar to `.kb-migration/before/sidecars/` then rewrite in-place atomically adding `show:` field. Scan both `<output>/*.manifest.yaml` and `<output>/notebooklm/*.manifest.yaml`.
- **Atomic write invariant:** every sidecar rewrite uses temp-file + fsync + `os.replace` (same pattern as `state.write_state_file`). A crash mid-write cannot corrupt the live sidecar — either the old bytes survive on disk, or the new atomic replacement is complete. Never write directly to the live sidecar path.
- **Files:** modify `migrate_multi_show.py`; tests.
- **Tests:**
  - fixture with sidecars in both locations → both get `show:` appended; both live rewrites are byte-identical (except `show:` field) to what the temp-file produced.
  - validation failure in Phase B restores every sidecar byte-exact from `.kb-migration/before/sidecars/`.
  - **Crash-inside-sidecar-write test:** monkeypatch `os.replace` to raise mid-way through Phase A-bis on sidecar #2 → sidecar #1 is rewritten and committed; sidecar #2's original bytes survive untouched on disk; `.kb-migration/before/sidecars/` still has both originals. `--resume` restores sidecar #1 from snapshot and exits cleanly.
- **Commit:** `feat(kb): migrate — Phase A-bis (atomic sidecar in-place migration)`

## Task 16: Migrator — Phase B (full validation)

- **Goal:** validate staged tree + live sidecars. Use `load_shows`, per-show `scan_episode_wiki`, `parse_ep_ref_field` on every EpRef-bearing field, `validate_body_wikilinks` for stale flat `[[wiki/episodes/ep-N-...]]` patterns, dual-format state file loads.
- **Files:** modify `migrate_multi_show.py`; tests.
- **Tests:** valid staging passes; intentionally corrupted staged stub (legacy str) fails validation; body wikilink with stale path fails.
- **Commit:** `feat(kb): migrate — Phase B (full-tree strict validation)`

## Task 17: Migrator — Phase C (copy-then-verify commit + commit.log + resume)

- **Goal:** per-entry copy-then-verify to live tree, sha256-fingerprint commit.log, resume after crash via log. kb.yaml committed last.
- **Strict ordering invariant:** for each flat→nested episode file: (1) copy staged nested file to live `wiki/episodes/<show>/ep-N-<slug>.md`, (2) sha256-verify against staged, (3) append to commit.log, (4) ONLY THEN delete legacy flat `wiki/episodes/ep-N-<slug>.md`. Violating this ordering risks silent data loss.
- **Resume live-drift guard:** for each entry not already in `commit.log`, consult `.kb-migration/before/manifest.yaml` and compute `sha256_live`:
  - **First check (idempotent advance):** if `sha256_live == sha256_staged`, treat as already committed — skip. This applies regardless of `existed_before`, and covers the crash window "copy+verify succeeded, log append did not" for ALL entry types (episodes, stubs, state, kb.yaml, sidecars, other).
  - **Otherwise, `existed_before=true`:** `sha256_live` MUST match `sha256_before`. Drift → `LiveDriftError`.
  - **Otherwise, `existed_before=false`:** destination was expected to not exist. Any non-staged content there is drift → `LiveDriftError`.
  Already-committed entries listed in `commit.log` (matching the staging fingerprint) are skipped cleanly.
- **Files:** modify `migrate_multi_show.py`; tests.
- **Tests:**
  - happy-path commit (all entries in commit.log, legacy flat files removed, kb.yaml swapped).
  - crash between entry N's copy+verify and log append → resume detects the already-written live file via fingerprint match and advances past it.
  - crash BETWEEN nested-copy+log-append AND legacy-delete → resume completes the delete (flat file still present but commit.log shows entry committed).
  - crash before kb.yaml swap → resume completes it.
  - **Delete-ordering safety test:** simulate crash INSIDE the nested-copy (file written but verify fails) → legacy flat file must still exist; resume re-copies from staging and never deletes the flat file until the nested copy's sha256 matches.
  - **Resume live-drift test (existed_before=true):** after crash mid-Phase-C, user manually edits a not-yet-committed live file; `--resume` detects the drift vs `before/` snapshot and aborts with `LiveDriftError` — no overwrite happens.
  - **Resume live-drift test (existed_before=false):** after crash mid-Phase-C before a nested destination was written, another process creates a file at that destination with unexpected bytes; `--resume` aborts with `LiveDriftError` and leaves both the stray file and staging intact.
  - **Resume idempotency test (existed_before=false):** after crash mid-Phase-C AFTER a nested destination was written AND logged, `--resume` recognizes the live file's sha256 matches `sha256_staged` and skips the entry without re-writing.
  - **Resume idempotency test (existed_before=true, copy-succeeded-log-missing):** a stub (or any existed_before=true entry) was copy+verified successfully but commit.log append did not happen before crash. Live bytes == `sha256_staged`. `--resume` MUST advance past this entry idempotently — no `LiveDriftError`. This covers the critical case that blocked round 3.
- **Commit:** `feat(kb): migrate — Phase C (copy-then-verify commit with resume log)`

## Task 18: Migrator — CLI + lock + idle-check + dry-run

- **Goal:** wire `main()` argparse with `--show-id`, `--show-title`, `--dry-run`, `--resume`. Acquire `kb_mutation_lock` BEFORE running idle-check (acquire-then-idle-check ordering per spec §6.3). Handle `--dry-run` per spec: run Phase A (build `.kb-migration/staging/` + `plan.yaml` + `before/`) and Phase B (validate staged artifacts) — skip Phase A-bis live rewrites and Phase C commits. `ResumeMismatchError` is defined in this module.
- **Files:** modify `migrate_multi_show.py`; tests.
- **Tests:**
  - `--dry-run` happy path: `.kb-migration/staging/` exists and is valid; live files have unchanged mtimes (snapshot before/after); no sidecars have been rewritten in-place.
  - `--dry-run` + intentionally corrupt staging (e.g., legacy str in rewritten stub) → exits non-zero with Phase B errors; live tree still unchanged.
  - Lock acquired before any read.
  - Idle-check with pending run raises `PendingWorkError`.
  - `--resume` with `show-id` differing from persisted `plan.yaml.default_show_id` → `ResumeMismatchError`.
  - SIGINT during Phase C → lock released + partial commit.log + `.kb-migration/` intact for `--resume`.
- **Commit:** `feat(kb): migrate — CLI with lock, idle-check, dry-run, resume`

## Task 19: `kb-notebooklm/SKILL.md` — multi-show edits + lock wiring

- **Goal:** step 1 preamble (a) reads `show = resolve_show_for_mutation(shows, args.show)` AND (b) acquires `kb_mutation_lock(project_root, command="kb-notebooklm <subcommand>")` around every section that writes to `.notebooklm-state.yaml`, episodes registry, sidecar manifests, or the output dir. Steps 4b, 5b, 6a', 6a'', 6i, 6k use `show.*` fields; branding touchpoints use `show.title`; cleanup/status use `resolve_show_for_read`; add `--show` flag everywhere.
- **Read paths do NOT take the lock.** `status`, `list`, and any other read-only subcommand must not call `kb_mutation_lock` — they only need `resolve_show_for_read`. The lock is reserved for commands that write state/registry/sidecars/output files. This split is load-bearing for Task 24's concurrent-writer audit (which runs against a mutating second command, not `status`).
- **Critical — detached finalizer lock:** the NotebookLM wait-and-finalize step runs in a detached background process. That process MUST acquire `kb_mutation_lock` before its final writes (state update, sidecar rewrite, registry update). The SKILL.md finalizer command explicitly wraps the write section in `with kb_mutation_lock(project_root, command="kb-notebooklm finalize:<run-id>"):`. Per spec §6 and architecture statement at the top of this plan.
- **Files:** modify `plugins/kb/skills/kb-notebooklm/SKILL.md`.
- **Tests:** (SKILL.md isn't runnable; regression is via live test in task 24.) grep assertions: every hardcoded `全栈AI` is gone, every bare `ep-N` reference is gone, every write site (`.notebooklm-state.yaml`, `episodes.yaml`, sidecar manifest, finalizer section) is wrapped in `kb_mutation_lock`.
- **Commit:** `docs(kb-notebooklm): multi-show awareness + mutation lock wiring in SKILL.md`

## Task 20: `kb-publish/SKILL.md` — sequencing + --show + step 8c + lock wiring

- **Goal:** step 1 resolves effective show BEFORE reading episodes_registry AND acquires `kb_mutation_lock(project_root, command="kb-publish <subcommand>")` around every write section (episodes.yaml updates, wiki/episodes/<show>/ writes, sidecar manifests); sidecar-vs-`--show` conflict raises `ShowMismatchError` (defined in `shows.py`); step 2b preserves show; step 8c passes show through.
- **Files:** modify `plugins/kb/skills/kb-publish/SKILL.md`; ensure `shows.py` defines and exports `ShowMismatchError` (add a tiny prereq edit to Task 2 if absent).
- **Tests:** grep assertions in SKILL.md: every write section (episodes.yaml mutation, wiki episode write, sidecar manifest write) is wrapped in `kb_mutation_lock`.
- **Commit:** `docs(kb-publish): multi-show sequencing + mutation lock wiring in SKILL.md`

## Task 21: `kb-init/SKILL.md` — seed shows[0]

- **Goal:** fresh installs prompt for show id/title/hosts and write a single `shows[0]` entry with `default: true`. No legacy single-show writes.
- **Files:** modify `plugins/kb/skills/kb-init/SKILL.md`.
- **Commit:** `docs(kb-init): seed integrations.shows[0] on fresh install`

## Task 22: `kb/SKILL.md` — document `/kb migrate`

- **Goal:** add a section documenting `/kb migrate` command semantics (detection, phases, lock, dry-run, resume).
- **Files:** modify `plugins/kb/skills/kb/SKILL.md`.
- **Commit:** `docs(kb): document /kb migrate subcommand`

## Task 23: Version bump to 2.0.0 + full test run

- **Goal:** bump `plugins/kb/.claude-plugin/plugin.json` version to `2.0.0` (major, breaking). Run the full test suite to confirm green.
- **Files:** modify `plugin.json`.
- **Tests:** `pytest plugins/kb/skills/*/scripts/tests/ -v` — all pass.
- **Commit:** `chore: bump kb plugin to 2.0.0 for multi-show support`

## Task 23.5: End-to-end smoke test harness

- **Goal:** provide a single command the user can run that exercises the full pipeline against a synthetic KB in `tmp_path` — no dependency on the real KB, no Bedrock calls, no NotebookLM. This is the "does the whole thing actually work" check before Task 24 touches the real KB.
- **What it covers:**
  1. Build a realistic pre-migration fixture KB (flat `wiki/episodes/ep-*.md`, stubs with `created_by: ep-N`, `episodes.yaml`, legacy `.notebooklm-state.yaml`, sample sidecar manifests in `output/notebooklm/`, body wikilinks inside both episode articles and one non-episode wiki note).
  2. Run `migrate_multi_show --show-id quanzhan-ai --show-title '全栈AI' --project-root <tmp>` end-to-end (Phase A → A-bis → B → C → D).
  3. Assert post-migration invariants:
     - `kb.yaml` has `integrations.shows[0].id == "quanzhan-ai"`.
     - `wiki/episodes/quanzhan-ai/ep-1-*.md` exists with `prior_episode_ref: {show, ep}` dict shape.
     - No `wiki/episodes/ep-1-*.md` (flat path) remains.
     - Stubs have `created_by: {show: quanzhan-ai, ep: 1}` dict form.
     - Body wikilinks were rewritten to `[[wiki/episodes/quanzhan-ai/ep-1-<slug>]]`.
     - Sidecar manifests gained `show: quanzhan-ai` field.
     - `.notebooklm-state.yaml` has `shows: {quanzhan-ai: {...}}` top-level shape.
     - `.kb-mutation.lock` is NOT present (released cleanly).
     - `.kb-migration/` still present with `commit.log` marking all entries committed.
  4. `--resume` on the same completed migration is a no-op (exit 0, no changes).
  5. A deliberately crashed-mid-Phase-C scenario: monkeypatch Phase C to raise after 2 entries → verify `commit.log` has 2 entries, live tree is half-migrated, `--resume` completes cleanly.
  6. `--dry-run` run against a fresh fixture → staging exists, live tree untouched, mtimes match before+after.
- **Files:**
  - Create: `plugins/kb/skills/kb/scripts/tests/test_e2e_migrator.py`
  - The test itself is hermetic pytest; no LLM calls. It validates the full migrator pipeline end-to-end on realistic fixtures.
- **How to run:** `pytest plugins/kb/skills/kb/scripts/tests/test_e2e_migrator.py -v -s` — no special flags, no network, no real KB access.
- **Commit:** `test(kb): end-to-end migrator smoke test`

## Task 23.6: Rollback safety script

- **Goal:** a one-liner script that restores a KB from its `.kb-migration/before/` snapshot if the user wants to undo a migration. Worst-case escape hatch.
- **Files:**
  - Create: `plugins/kb/skills/kb/scripts/rollback_migration.py`
  - Create: `plugins/kb/skills/kb/scripts/tests/test_rollback_migration.py`
- **CLI:** `python rollback_migration.py --project-root <path> [--yes]`
- **Behavior:** verify `.kb-migration/before/manifest.yaml` exists; for each entry with `existed_before=true`, restore the file from `before/` to its original path (copy-then-verify sha256 matches `sha256_before`); for each entry with `existed_before=false`, delete the live file at that path if and only if its sha256 matches `sha256_staged` (don't delete anything we didn't write). Restore `kb.yaml` last. On success, rename `.kb-migration/` to `.kb-migration.rolled-back-<timestamp>/` so user can still inspect.
- **Safety:** acquires `kb_mutation_lock`; refuses if any pending runs/notebooks.
- **Tests:** happy-path rollback reverts every file; rollback refuses with `LockBusyError` if lock held; rollback-after-partial-migration (only some entries in commit.log) still works correctly.
- **Commit:** `feat(kb): rollback_migration.py — escape hatch to undo a migration`

## Task 24: Live migration on real KB

- **Goal:** run `/kb migrate --dry-run` on `~/Documents/MLL/`, review plan, then run for real. Verify wiki/episodes/quanzhan-ai/*.md and episodes.yaml still work. No pending jobs allowed — ensures idle check passes.
- **Files:** none (live run).
- **Verification:**
  - After migration, run `/kb-notebooklm status` and confirm it reads the new show-scoped state.
  - Run a dry `backfill-index --show quanzhan-ai --episode 1` (no regeneration needed) and confirm it parses the migrated wiki/episodes/quanzhan-ai/ep-1-*.md.
  - **Lock-coverage audit:** before running a real podcast workflow, `grep -nE "kb_mutation_lock|episodes\.yaml|\.notebooklm-state|manifest\.yaml|finalize|notebooklm/[^ ]*\.yaml|os\.replace|write_state_file" plugins/kb/skills/kb-notebooklm/SKILL.md plugins/kb/skills/kb-publish/SKILL.md` and manually verify every write site (including sidecar manifest writes, detached NotebookLM finalizers, and output-dir state writes) is inside a `with kb_mutation_lock(...):` block. If any write is missed, block the rollout and file a task.
  - **Concurrent-writer smoke test:** kick off a real podcast run (`/kb-notebooklm podcast`), then in another shell immediately try to run a definitely-mutating second command — `backfill-index --show quanzhan-ai --episode 1` (NOT `status`; status is a read path and does NOT take the lock). Confirm the second blocks on the lock or times out with `LockBusyError`, proving the lock is live.
- **No commit** — changes live in the user's KB, not this repo.

## Task 25: Verify EP3 v2 re-generate post-migration

- **Goal:** re-run `/kb-notebooklm podcast` with a new test topic and verify the new `<show-id>-` filename prefix appears; series bible pulls only quanzhan-ai's episodes; dedup judge uses show-scoped coverage.
- **Files:** none (live run).
- **Verification:** generated file is `podcast-quanzhan-ai-<theme>-YYYY-MM-DD.mp3`; transcript has `show: quanzhan-ai` in its sidecar manifest.
- **No commit.**

---

## Self-Review Checklist (run before handing off to subagents)

- [x] **Contracts table** present at top of plan, authoritative.
- [x] **Every task** references types/functions from the contracts table, not re-definitions.
- [x] **Migration is last** (task 13-18) so every helper it calls exists by then.
- [x] **Test scaffolding** comes before tests that use it (task 1 before tasks 2+).
- [x] **Each task is 2-5 steps of 2-5 minutes each** (tasks 1-5 explicit; tasks 6-22 condensed because they follow identical TDD structure and contracts table is authoritative).
- [x] **No placeholders** ("TBD", "add error handling"): each task names exact tests and implementation signatures.
- [x] **Type consistency** across tasks: `EpRef`, `Show`, `resolve_show_for_mutation` referenced identically everywhere.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-23-multi-show-podcast-support-implementation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task with review between tasks. Given the plan's size and the transaction-logic correctness risk, this is the right approach.
2. **Inline Execution** — executing-plans skill with batch checkpoints.

Subagent-Driven is the recommended path per user convention (CLAUDE.md).
