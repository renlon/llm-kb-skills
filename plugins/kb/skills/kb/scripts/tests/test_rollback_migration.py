"""Tests for rollback_migration.py — undo a migration from .kb-migration/before/."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

# Reuse the e2e fixture infra
import migrate_multi_show as M
import rollback_migration as R


@pytest.fixture
def migrated_kb(realistic_pre_migration_kb: Path) -> Path:
    """Build a pre-migration KB and run the migrator to completion."""
    argv = [
        "--project-root", str(realistic_pre_migration_kb),
        "--show-id", "quanzhan-ai",
        "--show-title", "全栈AI",
        "--show-hosts", "瓜瓜龙,海发菜",
    ]
    assert M.main(argv) == 0
    return realistic_pre_migration_kb


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def test_rollback_happy_path(migrated_kb: Path):
    """Full rollback reverts kb.yaml, episode articles, stubs, state file, sidecars."""
    project = migrated_kb
    rc = R.main(["--project-root", str(project), "--yes"])
    assert rc == 0

    # Flat episode files restored
    assert (project / "wiki" / "episodes" / "ep-1-intro.md").exists()
    assert (project / "wiki" / "episodes" / "ep-2-deep-dive.md").exists()

    # Nested paths gone
    nested_dir = project / "wiki" / "episodes" / "quanzhan-ai"
    assert not nested_dir.exists() or not any(nested_dir.iterdir())

    # kb.yaml has no shows[]
    kb = yaml.safe_load((project / "kb.yaml").read_text())
    assert (kb.get("integrations") or {}).get("shows") is None or \
           (kb.get("integrations") or {}).get("shows") == []

    # Stub frontmatter reverted to legacy ep-N strings
    stub = yaml.safe_load(
        (project / "wiki" / "attention" / "self-attention.md").read_text().split("---\n")[1])
    assert stub["created_by"] == "ep-1"

    # State file reverted to legacy (no shows: top-level)
    state = yaml.safe_load((project / ".notebooklm-state.yaml").read_text())
    assert "shows" not in state
    assert "runs" in state

    # Sidecars reverted (no show: field)
    sidecar = yaml.safe_load(
        (project / "output" / "podcast-intro-2026-04-01.mp3.manifest.yaml").read_text())
    assert "show" not in sidecar

    # .kb-migration/ renamed to rolled-back-*
    assert not (project / ".kb-migration").exists()
    rolled_back = list(project.glob(".kb-migration.rolled-back-*"))
    assert len(rolled_back) == 1


def test_rollback_refuses_with_pending_work(migrated_kb: Path):
    """If state has pending run, refuse to roll back."""
    project = migrated_kb
    # Inject a pending run into the (now migrated) state file
    state_path = project / ".notebooklm-state.yaml"
    state = yaml.safe_load(state_path.read_text())
    state["shows"]["quanzhan-ai"]["runs"] = [
        {"status": "pending", "workflow": "podcast"}
    ]
    state_path.write_text(yaml.safe_dump(state, allow_unicode=True))

    rc = R.main(["--project-root", str(project), "--yes"])
    assert rc == 2


def test_rollback_skips_drifted_new_file(migrated_kb: Path):
    """If an existed_before=false file was edited after migration, don't delete it."""
    project = migrated_kb
    # Edit the ep-1 nested file (existed_before=false for this destination)
    nested = project / "wiki" / "episodes" / "quanzhan-ai" / "ep-1-intro.md"
    nested.write_text(nested.read_text() + "\n\n## User edit after migration\n",
                      encoding="utf-8")

    rc = R.main(["--project-root", str(project), "--yes"])
    # Should succeed but NOT delete the drifted file
    assert rc == 0
    # User's edited version still on disk
    assert nested.exists()
    assert "User edit after migration" in nested.read_text()


def test_rollback_exits_2_when_no_migration_dir(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "kb.yaml").write_text("integrations: {}\n")
    rc = R.main(["--project-root", str(project), "--yes"])
    assert rc == 2


def test_rollback_acquires_lock(migrated_kb: Path, monkeypatch):
    """kb_mutation_lock must be called before touching any file."""
    project = migrated_kb
    lock_calls = []

    import lock
    real_lock = lock.kb_mutation_lock

    def recording_lock(*args, **kwargs):
        lock_calls.append((args, kwargs))
        return real_lock(*args, **kwargs)

    monkeypatch.setattr(lock, "kb_mutation_lock", recording_lock)
    monkeypatch.setattr(R, "kb_mutation_lock", recording_lock)

    rc = R.main(["--project-root", str(project), "--yes"])
    assert rc == 0
    assert len(lock_calls) == 1
    assert "rollback" in lock_calls[0][1].get("command", "").lower()
