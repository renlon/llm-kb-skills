"""Tests for migrate_multi_show — detection tri-state (Task 13)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_classify_unmigrated(pre_migration_kb: Path):
    """Fresh pre-migration fixture → unmigrated."""
    import migrate_multi_show as M
    assert M.classify_kb_state(pre_migration_kb) == "unmigrated"


def test_classify_partially_migrated(pre_migration_kb: Path):
    """kb.yaml has shows[] but flat episode files remain → partially_migrated."""
    # Mutate kb.yaml to add integrations.shows[...]
    kb_path = pre_migration_kb / "kb.yaml"
    kb = yaml.safe_load(kb_path.read_text())
    kb["integrations"]["shows"] = [{
        "id": "quanzhan-ai",
        "title": "全栈AI",
        "wiki_episodes_dir": "episodes/quanzhan-ai",
        "episodes_registry": "episodes.yaml",
    }]
    kb_path.write_text(yaml.safe_dump(kb, allow_unicode=True))
    # wiki/episodes/ep-1-test.md still exists flat → partial
    import migrate_multi_show as M
    assert M.classify_kb_state(pre_migration_kb) == "partially_migrated"


def test_classify_fully_migrated(pre_migration_kb: Path):
    """kb.yaml has shows[], episodes under episodes/<show>/, no flat leftover → fully_migrated."""
    kb_path = pre_migration_kb / "kb.yaml"
    kb = yaml.safe_load(kb_path.read_text())
    kb["integrations"]["shows"] = [{
        "id": "quanzhan-ai",
        "title": "全栈AI",
        "wiki_episodes_dir": "episodes/quanzhan-ai",
        "episodes_registry": "episodes.yaml",
    }]
    kb_path.write_text(yaml.safe_dump(kb, allow_unicode=True))

    # Move episode file to show-scoped path
    wiki = pre_migration_kb / "wiki"
    (wiki / "episodes" / "quanzhan-ai").mkdir(parents=True)
    flat_episode = wiki / "episodes" / "ep-1-test.md"
    nested_episode = wiki / "episodes" / "quanzhan-ai" / "ep-1-test.md"
    flat_episode.rename(nested_episode)

    import migrate_multi_show as M
    assert M.classify_kb_state(pre_migration_kb) == "fully_migrated"


def test_standalone_import(pre_migration_kb: Path):
    """Ensure migrate_multi_show.py can be imported from a clean subprocess
    without relying on the test conftest's sys.path hacks. This catches
    wrong parent-hop in the module's own sys.path insert."""
    module_path = Path(__file__).resolve().parents[1] / "migrate_multi_show.py"
    assert module_path.exists(), "migrate_multi_show.py not found"

    # Clean env: no PYTHONPATH; PYTHONDONTWRITEBYTECODE to avoid .pyc cruft
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(module_path.parent)!r})\n"
        "import migrate_multi_show\n"
        f"result = migrate_multi_show.classify_kb_state({str(pre_migration_kb)!r})\n"
        "print(result)\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"Standalone import failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
    assert r.stdout.strip() == "unmigrated"
