"""End-to-end migrator smoke test — builds a realistic pre-migration
KB in tmp_path, runs the full migrator pipeline, and asserts every
post-migration invariant. No real KB access, no Bedrock, no NotebookLM.

This is the single-command "does the whole thing work" check.
Run: pytest plugins/kb/skills/kb/scripts/tests/test_e2e_migrator.py -v
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

# conftest.py already handles sys.path for local + sibling scripts dir
import migrate_multi_show as M


@pytest.fixture
def realistic_pre_migration_kb(tmp_path: Path) -> Path:
    """Build a KB fixture with 2 episodes, multiple stubs, body wikilinks
    everywhere, a non-episode wiki note, legacy state file, sidecars in
    both locations."""
    project = tmp_path / "project"
    project.mkdir()
    wiki = project / "wiki"
    for sub in ("episodes", "attention", "quantization", "notes"):
        (wiki / sub).mkdir(parents=True)
    output = project / "output"
    (output / "notebooklm").mkdir(parents=True)
    (project / "lessons").mkdir()

    # kb.yaml
    (project / "kb.yaml").write_text(yaml.safe_dump({
        "integrations": {
            "notebooklm": {
                "enabled": True,
                "cli_path": "/dev/null",
                "venv_path": "/dev/null",
                "lessons_path": str(project / "lessons"),
                "wiki_path": str(wiki),
                "output_path": str(output),
                "language": "zh_Hans",
                "podcast": {
                    "format": "deep-dive",
                    "length": "long",
                    "hosts": ["A", "B"],
                    "intro_music": "/dev/null/intro.mp3",
                    "intro_music_length_seconds": 12,
                    "intro_crossfade_seconds": 3,
                    "transcript": {"enabled": False, "model": "large-v3",
                                   "device": "auto", "language": "zh"},
                },
            },
            "xiaoyuzhou": {
                "enabled": True,
                "podcast_id": "LEGACY",
                "episodes_registry": "episodes.yaml",
                "browser_data": ".browser-data",
                "staging_dir": "output/staging",
                "venv_path": "/dev/null",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    # episodes.yaml
    (project / "episodes.yaml").write_text(yaml.safe_dump({
        "episodes": [
            {"id": 1, "title": "EP1 | Intro", "topic": "Intro",
             "date": "2026-04-01", "status": "published",
             "audio": "podcast-intro-2026-04-01.mp3"},
            {"id": 2, "title": "EP2 | Deep Dive", "topic": "Deep Dive",
             "date": "2026-04-10", "status": "published",
             "audio": "podcast-deep-dive-2026-04-10.mp3"},
        ],
        "next_id": 3,
    }), encoding="utf-8")

    # Legacy state file
    (project / ".notebooklm-state.yaml").write_text(yaml.safe_dump({
        "last_podcast": None,
        "last_digest": None,
        "last_quiz": None,
        "notebooks": [],
        "runs": [],
    }), encoding="utf-8")

    # Episode articles
    def _episode_md(ep_id: int, slug: str, title: str, builds_on: list[int]) -> str:
        index = {
            "schema_version": 1,
            "summary": f"Summary for ep {ep_id}.",
            "concepts": [
                {
                    "slug": "wiki/attention/self-attention",
                    "depth_this_episode": "explained",
                    "depth_delta_vs_past": "new",
                    "prior_episode_ref": None,
                    "what": "W", "why_it_matters": "Y",
                    "key_points": ["k"], "covered_at_sec": 1.0,
                    "existed_before": False,
                },
            ],
            "open_threads": [],
            "series_links": {"builds_on": builds_on, "followup_candidates": []},
        }
        fm = {
            "title": title,
            "episode_id": ep_id,
            "audio_file": f"podcast-{slug}-2026-04-01.mp3",
            "transcript_file": f"podcast-{slug}-2026-04-01.transcript.md",
            "date": "2026-04-01",
            "depth": "intro",
            "tags": ["episode"],
            "aliases": [],
            "source_lessons": [],
            "index": index,
        }
        body = (
            f"\n# {title}\n\n"
            f"See [[wiki/episodes/ep-{ep_id}-{slug}]] for details. "
            f"Also related: [[wiki/episodes/ep-1-intro|the first episode]].\n"
        )
        return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n" + body

    (wiki / "episodes" / "ep-1-intro.md").write_text(
        _episode_md(1, "intro", "EP1 | Intro", []), encoding="utf-8")
    (wiki / "episodes" / "ep-2-deep-dive.md").write_text(
        _episode_md(2, "deep-dive", "EP2 | Deep Dive", [1]), encoding="utf-8")

    # Stubs — legacy ep-N str/int form in frontmatter
    (wiki / "attention" / "self-attention.md").write_text(
        "---\n"
        "title: Self Attention\ntags: [stub]\naliases: []\nstatus: stub\n"
        "created_by: ep-1\nlast_seen_by: ep-2\nbest_depth_episode: ep-2\n"
        "best_depth: explained\nreferenced_by: [ep-1, ep-2]\n"
        "created: '2026-04-01'\n---\n\n"
        "# Self Attention\n\nStub. See [[wiki/episodes/ep-1-intro]].\n",
        encoding="utf-8")
    (wiki / "quantization" / "int8.md").write_text(
        "---\n"
        "title: INT8 Quantization\ntags: [stub]\naliases: []\nstatus: stub\n"
        "created_by: ep-2\nlast_seen_by: ep-2\nbest_depth_episode: ep-2\n"
        "best_depth: explained\nreferenced_by: [ep-2]\n"
        "created: '2026-04-10'\n---\n\n"
        "# INT8 Quantization\n\nStub. [[wiki/episodes/ep-2-deep-dive|deep dive]].\n",
        encoding="utf-8")

    # Non-episode wiki note with legacy body wikilink
    (wiki / "notes" / "reading-list.md").write_text(
        "# Reading List\n\n"
        "- [[wiki/episodes/ep-1-intro|EP1]]\n"
        "- [[wiki/episodes/ep-2-deep-dive]]\n",
        encoding="utf-8")

    # Sidecar manifests (both locations, neither has show: yet)
    (output / "podcast-intro-2026-04-01.mp3.manifest.yaml").write_text(
        yaml.safe_dump({
            "episode_id": 1, "audio": "podcast-intro-2026-04-01.mp3",
            "date": "2026-04-01", "title": "EP1 | Intro",
        }), encoding="utf-8")
    (output / "notebooklm" / "podcast-intro-2026-04-01.notebooklm.manifest.yaml").write_text(
        yaml.safe_dump({
            "episode_id": 1, "notebook_id": "nb-123",
            "source_lessons": [], "generated_at": "2026-04-01",
        }), encoding="utf-8")

    return project


def _snapshot_mtimes(root: Path) -> dict[str, float]:
    """Return {relative_path_str: mtime} for every file under root,
    excluding .kb-migration/ which is expected to change."""
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root)
            # Exclude .kb-migration/ artefacts — they are expected to be created/modified
            if rel.parts and rel.parts[0] == ".kb-migration":
                continue
            out[str(rel)] = p.stat().st_mtime
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# ----------------------------------------------------------------------
# Test 1: happy-path end-to-end migration
# ----------------------------------------------------------------------

def test_e2e_full_migration(realistic_pre_migration_kb: Path):
    """Build realistic KB, run full migration, assert every invariant."""
    project = realistic_pre_migration_kb

    argv = [
        "--project-root", str(project),
        "--show-id", "quanzhan-ai",
        "--show-title", "全栈AI",
        "--show-hosts", "瓜瓜龙,海发菜",
    ]
    rc = M.main(argv)
    assert rc == 0, "migration should exit 0"

    wiki = project / "wiki"

    # kb.yaml has shows[0]
    kb = yaml.safe_load((project / "kb.yaml").read_text())
    assert kb["integrations"]["shows"][0]["id"] == "quanzhan-ai"
    assert kb["integrations"]["shows"][0]["title"] == "全栈AI"

    # Episode articles at new show-scoped path
    ep1 = wiki / "episodes" / "quanzhan-ai" / "ep-1-intro.md"
    ep2 = wiki / "episodes" / "quanzhan-ai" / "ep-2-deep-dive.md"
    assert ep1.exists(), f"ep1 missing at {ep1}"
    assert ep2.exists(), f"ep2 missing at {ep2}"

    # Flat paths gone
    assert not (wiki / "episodes" / "ep-1-intro.md").exists()
    assert not (wiki / "episodes" / "ep-2-deep-dive.md").exists()

    # Episode article frontmatter — dict refs
    ep2_text = ep2.read_text()
    _, fm_raw, body = ep2_text.split("---\n", 2)
    fm = yaml.safe_load(fm_raw)
    builds_on = fm["index"]["series_links"]["builds_on"]
    assert len(builds_on) == 1
    assert builds_on[0] == {"show": "quanzhan-ai", "ep": 1}

    # Episode body wikilinks rewritten
    assert "[[wiki/episodes/quanzhan-ai/ep-2-deep-dive]]" in ep2_text
    assert "[[wiki/episodes/quanzhan-ai/ep-1-intro|" in ep2_text
    # No stale flat wikilinks
    assert "[[wiki/episodes/ep-1-intro]]" not in ep2_text
    assert "[[wiki/episodes/ep-2-deep-dive]]" not in ep2_text

    # Stub — dict form
    self_attn = (wiki / "attention" / "self-attention.md").read_text()
    _, stub_fm_raw, stub_body = self_attn.split("---\n", 2)
    sfm = yaml.safe_load(stub_fm_raw)
    assert sfm["created_by"] == {"show": "quanzhan-ai", "ep": 1}
    assert sfm["last_seen_by"] == {"show": "quanzhan-ai", "ep": 2}
    assert sfm["best_depth_episode"] == {"show": "quanzhan-ai", "ep": 2}
    assert sfm["referenced_by"] == [
        {"show": "quanzhan-ai", "ep": 1},
        {"show": "quanzhan-ai", "ep": 2},
    ]
    assert "[[wiki/episodes/quanzhan-ai/ep-1-intro]]" in stub_body

    # Non-episode note rewritten
    notes = (wiki / "notes" / "reading-list.md").read_text()
    assert "[[wiki/episodes/quanzhan-ai/ep-1-intro|EP1]]" in notes
    assert "[[wiki/episodes/quanzhan-ai/ep-2-deep-dive]]" in notes
    assert "[[wiki/episodes/ep-1-intro|" not in notes

    # Sidecars gained show: field
    sidecar1 = yaml.safe_load(
        (project / "output" / "podcast-intro-2026-04-01.mp3.manifest.yaml").read_text())
    sidecar2 = yaml.safe_load(
        (project / "output" / "notebooklm" / "podcast-intro-2026-04-01.notebooklm.manifest.yaml").read_text())
    assert sidecar1.get("show") == "quanzhan-ai"
    assert sidecar2.get("show") == "quanzhan-ai"

    # State file new format
    state = yaml.safe_load((project / ".notebooklm-state.yaml").read_text())
    assert "shows" in state
    assert "quanzhan-ai" in state["shows"]
    # Legacy top-level keys gone
    assert "runs" not in state
    assert "last_podcast" not in state

    # Lock released
    assert not (project / ".kb-mutation.lock").exists()

    # Migration metadata intact
    assert (project / ".kb-migration" / "plan.yaml").exists()
    assert (project / ".kb-migration" / "commit.log").exists()

    # commit.log marks every entry committed
    commit_log = yaml.safe_load(
        (project / ".kb-migration" / "commit.log").read_text())
    plan = yaml.safe_load(
        (project / ".kb-migration" / "plan.yaml").read_text())
    assert len(commit_log) == len(plan["commit_order"])


# ----------------------------------------------------------------------
# Test 2: --resume on completed migration is a no-op
# ----------------------------------------------------------------------

def test_e2e_resume_on_completed_is_noop(realistic_pre_migration_kb: Path):
    project = realistic_pre_migration_kb
    argv = [
        "--project-root", str(project),
        "--show-id", "quanzhan-ai",
        "--show-title", "全栈AI",
        "--show-hosts", "瓜瓜龙,海发菜",
    ]
    # First run
    assert M.main(argv) == 0

    # Snapshot content hashes for all live-tree files (excluding .kb-migration/).
    # Use hashes rather than mtimes because phase_a_bis_sidecars is idempotent
    # (sidecars already have show: so content is unchanged) but may update mtimes
    # via atomic rewrites.
    hashes_before = {p: _sha256(project / p) for p in _snapshot_mtimes(project)}

    # Resume run
    argv2 = argv + ["--resume"]
    assert M.main(argv2) == 0

    hashes_after = {p: _sha256(project / p) for p in _snapshot_mtimes(project)}
    # Live tree content unchanged (same bytes for every file)
    assert hashes_before == hashes_after, \
        "resume on completed migration should not change any live file content"


# ----------------------------------------------------------------------
# Test 3: crash-mid-Phase-C + resume
# ----------------------------------------------------------------------

def test_e2e_crash_phase_c_and_resume(realistic_pre_migration_kb: Path, monkeypatch):
    """Monkeypatch _append_commit_log to raise after 2 successful appends,
    simulating a crash mid-Phase-C. Then verify --resume completes cleanly."""
    project = realistic_pre_migration_kb
    argv = [
        "--project-root", str(project),
        "--show-id", "quanzhan-ai",
        "--show-title", "全栈AI",
        "--show-hosts", "瓜瓜龙,海发菜",
    ]

    # Count successful _append_commit_log calls and raise after 2
    real_append_commit_log = M._append_commit_log
    call_count = {"n": 0}

    def crashing_append(commit_log_path, *, rel_path, sha256_committed):
        call_count["n"] += 1
        if call_count["n"] > 2:
            raise RuntimeError("simulated crash after 2 commit log entries")
        return real_append_commit_log(
            commit_log_path, rel_path=rel_path, sha256_committed=sha256_committed
        )

    monkeypatch.setattr(M, "_append_commit_log", crashing_append)

    # The crash propagates through main() because it's not caught
    with pytest.raises(RuntimeError, match="simulated crash"):
        M.main(argv)

    # Lock was released by the context manager's finally block
    assert not (project / ".kb-mutation.lock").exists(), \
        "lock should be released after exception"

    # commit.log has exactly 2 entries (and plan has more than 2 entries)
    commit_log_path = project / ".kb-migration" / "commit.log"
    plan_path = project / ".kb-migration" / "plan.yaml"
    assert commit_log_path.exists(), "commit.log should exist with 2 entries"
    assert plan_path.exists(), "plan.yaml should exist"

    entries = yaml.safe_load(commit_log_path.read_text()) or []
    plan = yaml.safe_load(plan_path.read_text()) or {}
    assert len(entries) == 2, \
        f"expected exactly 2 commit log entries; got {len(entries)}"
    assert len(plan["commit_order"]) > 2, \
        f"plan should have >2 entries for this test to be meaningful; got {len(plan['commit_order'])}"

    # Undo the monkeypatch (restore real function) and resume
    monkeypatch.setattr(M, "_append_commit_log", real_append_commit_log)

    argv_resume = argv + ["--resume"]
    assert M.main(argv_resume) == 0

    # Final state matches happy path
    wiki = project / "wiki"
    assert (wiki / "episodes" / "quanzhan-ai" / "ep-1-intro.md").exists()
    assert (wiki / "episodes" / "quanzhan-ai" / "ep-2-deep-dive.md").exists()
    assert not (wiki / "episodes" / "ep-1-intro.md").exists()
    assert not (wiki / "episodes" / "ep-2-deep-dive.md").exists()

    # commit.log is now complete
    entries_after = yaml.safe_load(commit_log_path.read_text()) or []
    assert len(entries_after) == len(plan["commit_order"]), \
        f"commit.log should have all {len(plan['commit_order'])} entries after resume; got {len(entries_after)}"


# ----------------------------------------------------------------------
# Test 4: --dry-run leaves live tree untouched
# ----------------------------------------------------------------------

def test_e2e_dry_run(realistic_pre_migration_kb: Path):
    project = realistic_pre_migration_kb

    mtimes_before = _snapshot_mtimes(project)
    # Hash each file too — mtime alone may be unchanged while bytes differ (or vice versa)
    hashes_before = {
        p: _sha256(project / p) for p in mtimes_before.keys()
    }

    argv = [
        "--project-root", str(project),
        "--show-id", "quanzhan-ai",
        "--show-title", "全栈AI",
        "--show-hosts", "瓜瓜龙,海发菜",
        "--dry-run",
    ]
    rc = M.main(argv)
    assert rc == 0

    mtimes_after = _snapshot_mtimes(project)
    hashes_after = {
        p: _sha256(project / p) for p in mtimes_before.keys()
    }
    assert mtimes_before == mtimes_after
    assert hashes_before == hashes_after, "dry-run must not modify any live file"

    # .kb-migration/ exists with staging
    assert (project / ".kb-migration" / "staging").is_dir()
    assert (project / ".kb-migration" / "plan.yaml").exists()
    assert (project / ".kb-migration" / "before" / "manifest.yaml").exists()

    # A-bis skipped in dry-run → sidecars do NOT have show: field yet
    sidecar1 = yaml.safe_load(
        (project / "output" / "podcast-intro-2026-04-01.mp3.manifest.yaml").read_text())
    assert "show" not in sidecar1, "dry-run should NOT modify sidecars"

    # Phase C skipped in dry-run → flat episode files still present
    assert (project / "wiki" / "episodes" / "ep-1-intro.md").exists()
    assert (project / "wiki" / "episodes" / "ep-2-deep-dive.md").exists()
    # Show-scoped directory either doesn't exist or is empty
    show_ep_dir = project / "wiki" / "episodes" / "quanzhan-ai"
    assert not show_ep_dir.exists() or not any(show_ep_dir.iterdir()), \
        "dry-run must not commit episode files to show-scoped directory"
