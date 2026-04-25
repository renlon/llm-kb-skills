"""Tests for migrate_multi_show — Tasks 13-17."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

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
    without relying on the test conftest's sys.path hacks."""
    module_path = Path(__file__).resolve().parents[1] / "migrate_multi_show.py"
    assert module_path.exists(), "migrate_multi_show.py not found"

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


# ===========================================================================
# Phase A tests
# ===========================================================================

SHOW_ID = "quanzhan-ai"
SHOW_TITLE = "全栈AI"
SHOW_HOSTS = ["A", "B"]


def _run_phase_a(project_root: Path) -> dict:
    import migrate_multi_show as M
    return M.phase_a_plan_and_stage(
        project_root,
        default_show_id=SHOW_ID,
        default_show_title=SHOW_TITLE,
        default_show_hosts=SHOW_HOSTS,
    )


def test_phase_a_builds_kb_yaml_with_shows(pre_migration_kb: Path):
    """staged kb.yaml has integrations.shows[0].id == default_show_id."""
    _run_phase_a(pre_migration_kb)

    staged_kb = pre_migration_kb / ".kb-migration" / "staging" / "kb.yaml"
    assert staged_kb.exists(), "staging/kb.yaml was not created"
    kb = yaml.safe_load(staged_kb.read_text(encoding="utf-8"))
    shows = kb["integrations"]["shows"]
    assert len(shows) == 1
    assert shows[0]["id"] == SHOW_ID


def test_phase_a_stages_episode_articles_with_show_id_path_and_dict_refs(pre_migration_kb: Path):
    """staged wiki/episodes/<show>/ep-1-test.md exists with dict-form prior_episode_ref."""
    _run_phase_a(pre_migration_kb)

    staged_ep = (
        pre_migration_kb
        / ".kb-migration"
        / "staging"
        / "wiki"
        / "episodes"
        / SHOW_ID
        / "ep-1-test.md"
    )
    assert staged_ep.exists(), f"staged episode not found at {staged_ep}"

    text = staged_ep.read_text(encoding="utf-8")
    assert "---\n" in text
    end = text.find("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])
    idx = fm.get("index") or {}
    concepts = idx.get("concepts") or []
    # prior_episode_ref should be null (was null in fixture) or a dict
    if concepts:
        per = concepts[0].get("prior_episode_ref")
        # null is fine (fixture has null); dict form would also be fine
        assert per is None or isinstance(per, dict)


def test_phase_a_stages_stubs_with_dict_form(pre_migration_kb: Path):
    """stub's created_by, last_seen_by, best_depth_episode are dicts and referenced_by is list-of-dicts."""
    _run_phase_a(pre_migration_kb)

    staged_stub = (
        pre_migration_kb
        / ".kb-migration"
        / "staging"
        / "wiki"
        / "attention"
        / "self-attention.md"
    )
    assert staged_stub.exists(), f"staged stub not found at {staged_stub}"

    text = staged_stub.read_text(encoding="utf-8")
    end = text.find("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])

    for field_name in ("created_by", "last_seen_by", "best_depth_episode"):
        val = fm.get(field_name)
        assert isinstance(val, dict), f"{field_name} expected dict, got {val!r}"
        assert val.get("show") == SHOW_ID
        assert isinstance(val.get("ep"), int)

    ref_by = fm.get("referenced_by")
    assert isinstance(ref_by, list)
    assert len(ref_by) >= 1
    for r in ref_by:
        assert isinstance(r, dict), f"referenced_by entry expected dict, got {r!r}"
        assert r.get("show") == SHOW_ID


def test_phase_a_stages_state_file_new_format(pre_migration_kb: Path):
    """staged .notebooklm-state.yaml has top-level shows: key."""
    _run_phase_a(pre_migration_kb)

    staged_state = pre_migration_kb / ".kb-migration" / "staging" / ".notebooklm-state.yaml"
    assert staged_state.exists()
    raw = yaml.safe_load(staged_state.read_text(encoding="utf-8"))
    assert "shows" in raw, f"Expected 'shows' key in state, got: {list(raw.keys())}"


def test_phase_a_writes_plan_yaml_with_non_empty_commit_order(pre_migration_kb: Path):
    """plan.yaml exists and commit_order is non-empty."""
    plan = _run_phase_a(pre_migration_kb)
    plan_file = pre_migration_kb / ".kb-migration" / "plan.yaml"
    assert plan_file.exists()

    loaded_plan = yaml.safe_load(plan_file.read_text(encoding="utf-8"))
    assert loaded_plan["default_show_id"] == SHOW_ID
    assert isinstance(loaded_plan["commit_order"], list)
    assert len(loaded_plan["commit_order"]) > 0
    # Verify plan returned matches plan on disk
    assert plan["commit_order"] == loaded_plan["commit_order"]


def test_phase_a_snapshots_every_live_file_byte_exact_in_before(pre_migration_kb: Path):
    """before/ directory has byte-exact copies of episode and stub files."""
    _run_phase_a(pre_migration_kb)

    # Check the episode snapshot (flat legacy path)
    before_ep = (
        pre_migration_kb
        / ".kb-migration"
        / "before"
        / "wiki"
        / "episodes"
        / "ep-1-test.md"
    )
    assert before_ep.exists(), f"before snapshot not found at {before_ep}"

    live_ep = pre_migration_kb / "wiki" / "episodes" / "ep-1-test.md"
    assert before_ep.read_bytes() == live_ep.read_bytes(), "before snapshot differs from live"

    # Check stub snapshot
    before_stub = (
        pre_migration_kb
        / ".kb-migration"
        / "before"
        / "wiki"
        / "attention"
        / "self-attention.md"
    )
    assert before_stub.exists()
    live_stub = pre_migration_kb / "wiki" / "attention" / "self-attention.md"
    assert before_stub.read_bytes() == live_stub.read_bytes()


def test_phase_a_writes_manifest_with_fingerprints_and_categories(pre_migration_kb: Path):
    """manifest has correct shape, sha256s, categories."""
    _run_phase_a(pre_migration_kb)

    manifest_path = pre_migration_kb / ".kb-migration" / "before" / "manifest.yaml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, list)
    assert len(manifest) > 0

    categories = {e["category"] for e in manifest}
    assert "episode" in categories
    assert "stub" in categories
    assert "kb" in categories
    assert "state" in categories

    for entry in manifest:
        assert "relative_path" in entry
        assert "existed_before" in entry
        assert "sha256_staged" in entry
        assert "category" in entry
        # sha256_staged should be non-empty hex
        assert len(entry["sha256_staged"]) == 64


def test_phase_a_rewrites_body_wikilinks_episode_article(pre_migration_kb: Path):
    """episode article body [[wiki/episodes/ep-1-test]] → [[wiki/episodes/quanzhan-ai/ep-1-test]]."""
    _run_phase_a(pre_migration_kb)

    staged_ep = (
        pre_migration_kb
        / ".kb-migration"
        / "staging"
        / "wiki"
        / "episodes"
        / SHOW_ID
        / "ep-1-test.md"
    )
    text = staged_ep.read_text(encoding="utf-8")
    # Should have the show-scoped form
    assert f"[[wiki/episodes/{SHOW_ID}/ep-1-test]]" in text
    # Should NOT have the legacy flat form
    assert "[[wiki/episodes/ep-1-test]]" not in text


def test_phase_a_rewrites_body_wikilinks_stub(pre_migration_kb: Path):
    """stub body [[wiki/episodes/ep-1-test]] → [[wiki/episodes/quanzhan-ai/ep-1-test]]."""
    _run_phase_a(pre_migration_kb)

    staged_stub = (
        pre_migration_kb
        / ".kb-migration"
        / "staging"
        / "wiki"
        / "attention"
        / "self-attention.md"
    )
    text = staged_stub.read_text(encoding="utf-8")
    assert f"[[wiki/episodes/{SHOW_ID}/ep-1-test]]" in text
    assert "[[wiki/episodes/ep-1-test]]" not in text


def test_phase_a_rewrites_body_wikilinks_other_wiki_file(pre_migration_kb: Path):
    """Other wiki files with legacy wikilinks get rewritten and added to commit_order."""
    # Create a non-episode non-stub wiki file with a legacy wikilink
    notes_dir = pre_migration_kb / "wiki" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    reading_md = notes_dir / "reading.md"
    reading_md.write_text(
        "# Reading List\n\nSee [[wiki/episodes/ep-1-test]] for episode 1.\n",
        encoding="utf-8",
    )

    plan = _run_phase_a(pre_migration_kb)

    # Check the staged version was rewritten
    staged_reading = (
        pre_migration_kb
        / ".kb-migration"
        / "staging"
        / "wiki"
        / "notes"
        / "reading.md"
    )
    assert staged_reading.exists(), "staged notes/reading.md not found"
    text = staged_reading.read_text(encoding="utf-8")
    assert f"[[wiki/episodes/{SHOW_ID}/ep-1-test]]" in text
    assert "[[wiki/episodes/ep-1-test]]" not in text

    # Check it's in commit_order with category "other"
    co = plan["commit_order"]
    other_entries = [e for e in co if e.get("category") == "other"]
    assert any("notes/reading.md" in e["relative_path"] for e in other_entries), \
        f"notes/reading.md not in commit_order as 'other': {co}"

    # Check it's snapshotted
    before_reading = (
        pre_migration_kb
        / ".kb-migration"
        / "before"
        / "wiki"
        / "notes"
        / "reading.md"
    )
    assert before_reading.exists()
    assert before_reading.read_bytes() == reading_md.read_bytes()

    # Check manifest entry
    manifest_path = pre_migration_kb / ".kb-migration" / "before" / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    other_manifest = [e for e in manifest if e.get("category") == "other"]
    assert any("notes/reading.md" in e["relative_path"] for e in other_manifest)


def test_phase_a_rewrites_display_text_wikilinks(pre_migration_kb: Path):
    """[[wiki/episodes/ep-1-test|display text]] → [[wiki/episodes/<show>/ep-1-test|display text]]."""
    # Patch the episode article to include a display-text wikilink
    ep_file = pre_migration_kb / "wiki" / "episodes" / "ep-1-test.md"
    text = ep_file.read_text(encoding="utf-8")
    text = text.replace(
        "See [[wiki/episodes/ep-1-test]] for details.",
        "See [[wiki/episodes/ep-1-test|nice name]] for details.",
    )
    ep_file.write_text(text, encoding="utf-8")

    _run_phase_a(pre_migration_kb)

    staged_ep = (
        pre_migration_kb
        / ".kb-migration"
        / "staging"
        / "wiki"
        / "episodes"
        / SHOW_ID
        / "ep-1-test.md"
    )
    staged_text = staged_ep.read_text(encoding="utf-8")
    assert f"[[wiki/episodes/{SHOW_ID}/ep-1-test|nice name]]" in staged_text
    assert "[[wiki/episodes/ep-1-test|nice name]]" not in staged_text


def test_phase_a_fails_on_unresolvable_wikilink(pre_migration_kb: Path):
    """Body with [[wiki/episodes/ep-99-unknown]] → Phase A raises; .kb-migration/ cleaned up."""
    ep_file = pre_migration_kb / "wiki" / "episodes" / "ep-1-test.md"
    text = ep_file.read_text(encoding="utf-8")
    text += "\n\nSee also [[wiki/episodes/ep-99-unknown]] for reference.\n"
    ep_file.write_text(text, encoding="utf-8")

    import migrate_multi_show as M
    with pytest.raises(ValueError, match="unresolvable.*ep-99"):
        _run_phase_a(pre_migration_kb)

    # .kb-migration/ must NOT exist (temp dir cleaned up)
    assert not (pre_migration_kb / ".kb-migration").exists(), \
        ".kb-migration/ was left behind after Phase A failure"


# ===========================================================================
# Phase A-bis tests
# ===========================================================================

def _make_sidecar(path: Path, content: dict | None = None) -> None:
    """Write a sidecar manifest YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content or {"source_files": ["lesson1.md"], "generated_at": "2026-04-01"}
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_phase_a_bis_adds_show_field_to_sidecars_in_both_locations(pre_migration_kb: Path):
    """fixture has sidecars in both output/ and output/notebooklm/; both get show: field."""
    output = pre_migration_kb / "output"
    sidecar_a = output / "podcast-2026-04-01.manifest.yaml"
    sidecar_b = output / "notebooklm" / "podcast-2026-04-01-nb.manifest.yaml"
    _make_sidecar(sidecar_a)
    _make_sidecar(sidecar_b)

    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)

    for sidecar_path in (sidecar_a, sidecar_b):
        content = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
        assert content.get("show") == SHOW_ID, \
            f"{sidecar_path.name}: expected show={SHOW_ID!r}, got {content.get('show')!r}"


def test_phase_a_bis_writes_atomically(pre_migration_kb: Path):
    """monkeypatch os.replace to raise on sidecar #2 → sidecar #1 rewritten; sidecar #2 survives."""
    output = pre_migration_kb / "output"
    sidecar_a = output / "sidecar-a.manifest.yaml"
    sidecar_b = output / "sidecar-b.manifest.yaml"
    original_b_content = {"source_files": ["b.md"], "generated_at": "2026-04-02"}
    _make_sidecar(sidecar_a)
    _make_sidecar(sidecar_b, original_b_content)

    original_b_bytes = sidecar_b.read_bytes()

    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M

    call_count = [0]
    original_replace = os.replace

    def _patched_replace(src, dst):
        call_count[0] += 1
        # Raise on the second sidecar replace (first is sidecar_a)
        if call_count[0] == 2:
            raise OSError("simulated crash on sidecar #2")
        return original_replace(src, dst)

    with pytest.raises(OSError, match="simulated crash"):
        with patch("os.replace", _patched_replace):
            M.phase_a_bis_sidecars(pre_migration_kb, plan)

    # Sidecar B's original bytes must survive (atomic write prevents corruption)
    assert sidecar_b.read_bytes() == original_b_bytes, \
        "sidecar_b was corrupted despite atomic write failure"


def test_phase_a_bis_snapshots_before_rewrite(pre_migration_kb: Path):
    """before/sidecars/ has byte-exact copies of original sidecar content."""
    output = pre_migration_kb / "output"
    sidecar_a = output / "podcast-snap.manifest.yaml"
    _make_sidecar(sidecar_a, {"source_files": ["snap.md"]})
    original_bytes = sidecar_a.read_bytes()

    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)

    # Find the snapshot
    before_sidecars = pre_migration_kb / ".kb-migration" / "before" / "sidecars"
    assert before_sidecars.exists()

    # The snapshot should be under before/sidecars/<relative-to-project-root>
    rel = sidecar_a.relative_to(pre_migration_kb)
    snapshot = before_sidecars / rel
    assert snapshot.exists(), f"Snapshot not found at {snapshot}"
    assert snapshot.read_bytes() == original_bytes, "Snapshot bytes differ from original"


def test_phase_a_bis_restores_from_snapshot_on_failure(pre_migration_kb: Path):
    """Phase B failure → Phase A-bis restore restores sidecars exactly."""
    output = pre_migration_kb / "output"
    sidecar_a = output / "podcast-restore.manifest.yaml"
    _make_sidecar(sidecar_a, {"source_files": ["restore.md"], "my_field": "original"})
    original_bytes = sidecar_a.read_bytes()

    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    # Run Phase A-bis (rewrite the sidecar in-place)
    M.phase_a_bis_sidecars(pre_migration_kb, plan)

    # Verify sidecar was rewritten
    rewritten_content = yaml.safe_load(sidecar_a.read_text(encoding="utf-8"))
    assert rewritten_content.get("show") == SHOW_ID

    # Now simulate Phase B failure → restore
    M._restore_sidecars_phase_b(pre_migration_kb, plan)

    # After restore, sidecar should match original
    assert sidecar_a.read_bytes() == original_bytes, \
        "Sidecar was not restored to original bytes after Phase B failure"


# ===========================================================================
# Phase B tests
# ===========================================================================

def test_phase_b_valid_staging_passes(pre_migration_kb: Path):
    """Built staging passes Phase B validation."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    # Phase A-bis (no sidecars in fixture, so this is a no-op)
    M.phase_a_bis_sidecars(pre_migration_kb, plan)

    # Phase B should not raise
    M.phase_b_validate(pre_migration_kb, plan)


def test_phase_b_fails_on_legacy_stub_ref(pre_migration_kb: Path):
    """Manually corrupt staged stub with legacy created_by: 'ep-1' → Phase B raises."""
    plan = _run_phase_a(pre_migration_kb)

    # Corrupt the staged stub
    staged_stub = (
        pre_migration_kb
        / ".kb-migration"
        / "staging"
        / "wiki"
        / "attention"
        / "self-attention.md"
    )
    text = staged_stub.read_text(encoding="utf-8")
    end = text.find("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])
    fm["created_by"] = "ep-1"  # inject legacy form
    corrupted = "---\n" + yaml.safe_dump(fm, allow_unicode=True) + "---\n\n" + text[end + 5:]
    staged_stub.write_text(corrupted, encoding="utf-8")

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)

    with pytest.raises(Exception, match="legacy"):
        M.phase_b_validate(pre_migration_kb, plan)


def test_phase_b_fails_on_stale_body_wikilink(pre_migration_kb: Path):
    """Manually corrupt staged body with legacy [[wiki/episodes/ep-1-test]] → Phase B raises."""
    plan = _run_phase_a(pre_migration_kb)

    # Corrupt a staged stub body to inject a legacy wikilink
    staged_stub = (
        pre_migration_kb
        / ".kb-migration"
        / "staging"
        / "wiki"
        / "attention"
        / "self-attention.md"
    )
    text = staged_stub.read_text(encoding="utf-8")
    # Re-inject the legacy wikilink into the body
    text = text + "\nAlso see [[wiki/episodes/ep-1-test]] (legacy link).\n"
    staged_stub.write_text(text, encoding="utf-8")

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)

    with pytest.raises(Exception, match="legacy"):
        M.phase_b_validate(pre_migration_kb, plan)


# ===========================================================================
# Phase C tests
# ===========================================================================

def test_phase_c_commits_all_entries(pre_migration_kb: Path):
    """Happy path: commit.log has every commit_order entry; legacy flat episode deleted."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)
    M.phase_c_commit(pre_migration_kb, plan)

    # Check commit.log exists and has all entries
    commit_log_path = pre_migration_kb / ".kb-migration" / "commit.log"
    assert commit_log_path.exists()
    log_entries = yaml.safe_load(commit_log_path.read_text(encoding="utf-8")) or []
    log_paths = {e["relative_path"] for e in log_entries}

    commit_order_paths = {e["relative_path"] for e in plan["commit_order"]}
    assert commit_order_paths == log_paths, \
        f"Missing from log: {commit_order_paths - log_paths}"

    # Check live tree: nested episode exists
    nested_ep = pre_migration_kb / "wiki" / "episodes" / SHOW_ID / "ep-1-test.md"
    assert nested_ep.exists(), "nested episode file was not committed"

    # Legacy flat episode was deleted
    flat_ep = pre_migration_kb / "wiki" / "episodes" / "ep-1-test.md"
    assert not flat_ep.exists(), "legacy flat episode was not deleted"

    # kb.yaml now has shows
    kb = yaml.safe_load((pre_migration_kb / "kb.yaml").read_text(encoding="utf-8"))
    assert "shows" in kb["integrations"]
    assert kb["integrations"]["shows"][0]["id"] == SHOW_ID


def test_phase_c_kb_yaml_committed_last(pre_migration_kb: Path):
    """kb.yaml must be the last entry in commit.log."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)
    M.phase_c_commit(pre_migration_kb, plan)

    commit_log_path = pre_migration_kb / ".kb-migration" / "commit.log"
    log_entries = yaml.safe_load(commit_log_path.read_text(encoding="utf-8")) or []
    assert log_entries, "commit.log is empty"
    last = log_entries[-1]
    assert last["relative_path"] == "kb.yaml", \
        f"kb.yaml was not last in commit.log; last entry was: {last['relative_path']!r}"


def test_phase_c_crash_between_copy_and_log_resumes_idempotently(pre_migration_kb: Path):
    """Monkeypatch crash between verify and log append; resume with sha256_live == sha256_staged → advances."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)

    # Find the first episode entry in commit_order
    commit_order = plan["commit_order"]
    first_entry = next(e for e in commit_order if e.get("category") == "episode")
    first_rel = first_entry["relative_path"]

    # Manually copy the staged file to live without logging it
    staged_path = pre_migration_kb / ".kb-migration" / "staging" / first_rel
    live_path = pre_migration_kb / first_rel
    live_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged_path, live_path)

    # Do NOT write commit.log (simulate crash after copy but before log)
    # Resume should detect sha256_live == sha256_staged and advance past it
    M.phase_c_commit(pre_migration_kb, plan, resume=True)

    # Verify commit.log was written
    commit_log_path = pre_migration_kb / ".kb-migration" / "commit.log"
    log_entries = yaml.safe_load(commit_log_path.read_text(encoding="utf-8")) or []
    log_paths = {e["relative_path"] for e in log_entries}
    assert first_rel in log_paths, f"{first_rel} not in commit.log after resume"


def test_phase_c_crash_before_legacy_delete_resumes(pre_migration_kb: Path):
    """Crash skips legacy delete; resume with commit.log showing entry → legacy deleted."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)

    # Find episode entry
    commit_order = plan["commit_order"]
    ep_entry = next(e for e in commit_order if e.get("category") == "episode")
    ep_rel = ep_entry["relative_path"]
    legacy_rel = ep_entry["legacy_path"]

    # Manually run copy + log but skip legacy delete
    staged_path = pre_migration_kb / ".kb-migration" / "staging" / ep_rel
    live_path = pre_migration_kb / ep_rel
    live_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged_path, live_path)

    sha256_staged = M._sha256(staged_path)
    M._append_commit_log(
        pre_migration_kb / ".kb-migration" / "commit.log",
        rel_path=ep_rel,
        sha256_committed=sha256_staged,
    )

    # Legacy file still exists (delete was skipped)
    legacy_path = pre_migration_kb / legacy_rel
    assert legacy_path.exists(), "Legacy file should still exist before resume"

    # Run full phase_c — for already-logged entries it should still do legacy delete
    M.phase_c_commit(pre_migration_kb, plan, resume=True)

    # Legacy should now be deleted
    assert not legacy_path.exists(), "Legacy flat file was not deleted on resume"


def test_phase_c_crash_before_kb_yaml_swap_resumes(pre_migration_kb: Path):
    """Everything except kb.yaml is committed; resume completes kb.yaml commit."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)

    commit_order = plan["commit_order"]

    # Commit everything except kb.yaml
    non_kb_order = [e for e in commit_order if e["relative_path"] != "kb.yaml"]
    kb_only_plan = dict(plan)
    kb_only_plan["commit_order"] = non_kb_order
    M.phase_c_commit(pre_migration_kb, kb_only_plan)

    # kb.yaml should NOT be updated yet (no shows key from migration)
    kb_before = yaml.safe_load((pre_migration_kb / "kb.yaml").read_text())
    assert "shows" not in (kb_before.get("integrations") or {}), \
        "kb.yaml was prematurely updated"

    # Resume full migration
    M.phase_c_commit(pre_migration_kb, plan, resume=True)

    # Now kb.yaml should be updated
    kb_after = yaml.safe_load((pre_migration_kb / "kb.yaml").read_text())
    assert "shows" in kb_after["integrations"]


def test_phase_c_live_drift_raises(pre_migration_kb: Path):
    """User edits a not-yet-committed existed_before=true file → LiveDriftError on resume."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)

    # Find a stub entry (existed_before=True)
    commit_order = plan["commit_order"]
    stub_entry = next((e for e in commit_order if e.get("category") == "stub"), None)
    if stub_entry is None:
        pytest.skip("No stub entries in commit_order")

    stub_rel = stub_entry["relative_path"]
    live_stub = pre_migration_kb / stub_rel

    # Simulate user edit: change a byte in the live file
    original_text = live_stub.read_text(encoding="utf-8")
    live_stub.write_text(original_text + "\n# User edit\n", encoding="utf-8")

    with pytest.raises(M.LiveDriftError, match="modified after Phase A"):
        M.phase_c_commit(pre_migration_kb, plan, resume=True)


def test_phase_c_live_drift_existed_before_false_raises(pre_migration_kb: Path):
    """A stray file at an existed_before=False destination → LiveDriftError."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)

    # Find an episode entry (existed_before=False — new nested path)
    commit_order = plan["commit_order"]
    ep_entry = next((e for e in commit_order if e.get("category") == "episode"), None)
    if ep_entry is None:
        pytest.skip("No episode entries in commit_order")

    ep_rel = ep_entry["relative_path"]
    live_ep = pre_migration_kb / ep_rel

    # Create a stray file at the destination with unexpected bytes
    live_ep.parent.mkdir(parents=True, exist_ok=True)
    live_ep.write_text("stray content with unexpected bytes", encoding="utf-8")

    with pytest.raises(M.LiveDriftError, match="existed_before=False"):
        M.phase_c_commit(pre_migration_kb, plan, resume=True)


def test_phase_c_resume_idempotent_for_existed_before_true_copy_succeeded_log_missing(pre_migration_kb: Path):
    """Critical: lived bytes == sha256_staged but commit.log doesn't have it → no LiveDriftError."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)

    # Find a stub entry (existed_before=True)
    commit_order = plan["commit_order"]
    stub_entry = next((e for e in commit_order if e.get("category") == "stub"), None)
    if stub_entry is None:
        pytest.skip("No stub entries in commit_order")

    stub_rel = stub_entry["relative_path"]
    staged_stub = pre_migration_kb / ".kb-migration" / "staging" / stub_rel
    live_stub = pre_migration_kb / stub_rel

    # Copy staged → live (simulating "copy succeeded but log append crashed")
    shutil.copy2(staged_stub, live_stub)

    # live bytes now == sha256_staged, but commit.log is empty
    assert not (pre_migration_kb / ".kb-migration" / "commit.log").exists()

    # Resume must NOT raise LiveDriftError — it should detect the match and advance
    M.phase_c_commit(pre_migration_kb, plan, resume=True)

    # Verify commit.log now has the entry
    log = yaml.safe_load(
        (pre_migration_kb / ".kb-migration" / "commit.log").read_text()
    ) or []
    log_paths = {e["relative_path"] for e in log}
    assert stub_rel in log_paths


def test_phase_c_delete_ordering_safety(pre_migration_kb: Path):
    """sha256 mismatch AFTER copy → legacy flat file must still exist; .kb-migration/ intact."""
    plan = _run_phase_a(pre_migration_kb)

    import migrate_multi_show as M
    M.phase_a_bis_sidecars(pre_migration_kb, plan)
    M.phase_b_validate(pre_migration_kb, plan)

    # Find episode entry
    commit_order = plan["commit_order"]
    ep_entry = next((e for e in commit_order if e.get("category") == "episode"), None)
    if ep_entry is None:
        pytest.skip("No episode entries in commit_order")

    ep_rel = ep_entry["relative_path"]
    legacy_rel = ep_entry["legacy_path"]
    legacy_path = pre_migration_kb / legacy_rel

    # Monkeypatch _sha256 to return a fake mismatch for the live file
    # after the copy (so verification fails before log+delete)
    original_sha256 = M._sha256
    call_count = [0]

    def _patched_sha256(path: Path) -> str:
        result = original_sha256(path)
        # After the first call (staged file sha), return garbage for the live file
        if str(path).endswith(ep_rel.replace("/", os.sep)) and call_count[0] > 0:
            return "0" * 64  # fake mismatch
        call_count[0] += 1
        return result

    with patch.object(M, "_sha256", _patched_sha256):
        with pytest.raises(RuntimeError, match="sha256 mismatch"):
            M.phase_c_commit(pre_migration_kb, plan)

    # Legacy flat file must still exist
    assert legacy_path.exists(), \
        "Legacy flat file was deleted despite sha256 mismatch (unsafe!)"

    # .kb-migration/ must still be intact
    assert (pre_migration_kb / ".kb-migration").exists()


# ===========================================================================
# CLI (main()) tests — Task 18
# ===========================================================================

def _cli(project_root: Path, *extra_args: str) -> list[str]:
    """Build a standard CLI argv list for main()."""
    return [
        "--project-root", str(project_root),
        "--show-id", "quanzhan-ai",
        "--show-title", "全栈AI",
        "--show-hosts", "瓜瓜龙,海发菜",
        *extra_args,
    ]


def test_cli_dry_run_leaves_live_tree_unchanged(pre_migration_kb: Path):
    """--dry-run must not modify any live .md or .yaml files; staging dir must exist."""
    import migrate_multi_show as M

    # Snapshot mtimes for all .md and .yaml files before dry run
    before_mtimes = {
        p: p.stat().st_mtime
        for p in pre_migration_kb.rglob("*")
        if p.is_file() and p.suffix in (".md", ".yaml")
        and ".kb-migration" not in str(p)
    }

    rc = M.main(_cli(pre_migration_kb, "--dry-run"))
    assert rc == 0, f"dry-run exited with {rc}"

    # Live files must be unmodified
    for p, mtime_before in before_mtimes.items():
        assert p.stat().st_mtime == mtime_before, \
            f"dry-run modified live file: {p}"

    # Staging directory must exist for inspection
    staging_dir = pre_migration_kb / ".kb-migration" / "staging"
    assert staging_dir.exists(), ".kb-migration/staging/ missing after dry-run"


def test_cli_dry_run_with_corrupt_staging(pre_migration_kb: Path, monkeypatch):
    """Force phase_b_validate to raise → exception propagates; live tree unchanged.

    Per spec, unhandled exceptions re-raise with traceback visible.
    A-bis is skipped in dry-run so live files are never touched.
    """
    import migrate_multi_show as M

    before_mtimes = {
        p: p.stat().st_mtime
        for p in pre_migration_kb.rglob("*")
        if p.is_file() and p.suffix in (".md", ".yaml")
        and ".kb-migration" not in str(p)
    }

    def _failing_phase_b(project_root, plan, **kwargs):
        raise ValueError("simulated Phase B failure")

    monkeypatch.setattr(M, "phase_b_validate", _failing_phase_b)

    # Unhandled ValueError propagates out of main() per spec
    with pytest.raises(ValueError, match="simulated Phase B failure"):
        M.main(_cli(pre_migration_kb, "--dry-run"))

    # Live files must still be unmodified (A-bis was never called)
    for p, mtime_before in before_mtimes.items():
        assert p.stat().st_mtime == mtime_before, \
            f"dry-run left live file modified after Phase B failure: {p}"


def test_cli_acquires_lock_before_idle_check(pre_migration_kb: Path, monkeypatch):
    """Lock is busy → LockBusyError; idle-check (load_state_file) is never called."""
    import json
    import migrate_multi_show as M
    import state as state_mod

    # Pre-create the lock file owned by current process (so it's "alive")
    lock_path = pre_migration_kb / ".kb-mutation.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid(), "command": "other-cmd"}))

    # Monkeypatch load_state_file to raise if ever called
    def _should_not_be_called(*a, **kw):
        raise AssertionError("idle-check was called before lock was acquired")

    monkeypatch.setattr(state_mod, "load_state_file", _should_not_be_called)
    # Also patch the reference inside the migrator module
    monkeypatch.setattr(M, "load_state_file", _should_not_be_called)

    rc = M.main(_cli(pre_migration_kb))
    assert rc == 75, f"Expected exit 75 (LockBusyError), got {rc}"

    # Clean up our lock
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def test_cli_idle_check_raises_on_pending_runs(pre_migration_kb: Path):
    """KB with a pending run → PendingWorkError → exit 2."""
    import migrate_multi_show as M

    # Seed .notebooklm-state.yaml with a pending run
    state_path = pre_migration_kb / ".notebooklm-state.yaml"
    state_path.write_text(
        "runs:\n"
        "  - id: run-001\n"
        "    status: pending\n"
        "    started_at: '2026-04-24T00:00:00Z'\n"
        "notebooks: []\n"
        "last_podcast: null\n"
        "last_digest: null\n"
        "last_quiz: null\n",
        encoding="utf-8",
    )

    rc = M.main(_cli(pre_migration_kb))
    assert rc == 2, f"Expected exit 2 (PendingWorkError), got {rc}"


def test_cli_resume_mismatched_show_id_raises(pre_migration_kb: Path):
    """dry-run builds plan.yaml with show-id quanzhan-ai; --resume --show-id other-show → exit 2."""
    import migrate_multi_show as M

    # First: dry-run to build .kb-migration/plan.yaml
    rc = M.main(_cli(pre_migration_kb, "--dry-run"))
    assert rc == 0, f"dry-run setup failed with exit {rc}"

    plan_path = pre_migration_kb / ".kb-migration" / "plan.yaml"
    assert plan_path.exists()

    # Now attempt resume with wrong show-id
    rc2 = M.main([
        "--project-root", str(pre_migration_kb),
        "--show-id", "other-show",
        "--resume",
    ])
    assert rc2 == 2, f"Expected exit 2 (ResumeMismatchError), got {rc2}"


def test_cli_full_happy_path(pre_migration_kb: Path):
    """Full non-dry-run migration: exits 0, live tree matches staging, lock file unlinked."""
    import migrate_multi_show as M

    rc = M.main(_cli(pre_migration_kb))
    assert rc == 0, f"Full migration exited with {rc}"

    # Verify live tree: nested episode exists
    nested_ep = (
        pre_migration_kb / "wiki" / "episodes" / "quanzhan-ai" / "ep-1-test.md"
    )
    assert nested_ep.exists(), "nested episode not committed to live tree"

    # Verify legacy flat episode deleted
    flat_ep = pre_migration_kb / "wiki" / "episodes" / "ep-1-test.md"
    assert not flat_ep.exists(), "legacy flat episode not removed"

    # Verify kb.yaml has shows
    import yaml as _yaml
    kb = _yaml.safe_load((pre_migration_kb / "kb.yaml").read_text(encoding="utf-8"))
    assert "shows" in kb["integrations"]
    assert kb["integrations"]["shows"][0]["id"] == "quanzhan-ai"

    # Verify lock file was released
    assert not (pre_migration_kb / ".kb-mutation.lock").exists(), \
        ".kb-mutation.lock not released after successful migration"


def test_cli_rejects_bad_show_id_format(pre_migration_kb: Path):
    """--show-id with uppercase letters → exit 1 (validation error)."""
    import migrate_multi_show as M

    rc = M.main([
        "--project-root", str(pre_migration_kb),
        "--show-id", "QuanZhanAI",          # uppercase — invalid
        "--show-title", "全栈AI",
        "--show-hosts", "瓜瓜龙,海发菜",
    ])
    assert rc == 1, f"Expected exit 1 for bad show-id, got {rc}"


def test_cli_blocks_on_partially_migrated(pre_migration_kb: Path):
    """KB already partially migrated without --resume → exit 2 with 'use --resume' message."""
    import migrate_multi_show as M

    # Mutate kb.yaml to add integrations.shows[] (but leave flat episode → partial)
    kb_path = pre_migration_kb / "kb.yaml"
    kb = yaml.safe_load(kb_path.read_text())
    kb["integrations"]["shows"] = [{
        "id": "quanzhan-ai",
        "title": "全栈AI",
        "wiki_episodes_dir": "episodes/quanzhan-ai",
        "episodes_registry": "episodes.yaml",
    }]
    kb_path.write_text(yaml.safe_dump(kb, allow_unicode=True), encoding="utf-8")
    # ep-1-test.md still flat → partially_migrated

    from io import StringIO
    import sys as _sys

    captured = StringIO()
    old_stderr = _sys.stderr
    _sys.stderr = captured
    try:
        rc = M.main(_cli(pre_migration_kb))
    finally:
        _sys.stderr = old_stderr

    assert rc == 2, f"Expected exit 2 for partially_migrated, got {rc}"
    output = captured.getvalue()
    assert "resume" in output.lower(), \
        f"Expected 'resume' hint in stderr output, got: {output!r}"
