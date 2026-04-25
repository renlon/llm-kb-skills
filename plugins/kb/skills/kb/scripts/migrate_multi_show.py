#!/usr/bin/env python3
"""Multi-show migrator — converts a legacy single-show KB to the new
multi-show format. See docs/superpowers/specs/2026-04-23-multi-show-podcast-support-design.md
and docs/superpowers/plans/2026-04-23-multi-show-podcast-support-implementation.md
(Tasks 13-18).

This module carries a sibling-path sys.path insert so it can import the
shared helpers from kb-publish/scripts/ when invoked standalone.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from the sibling kb-publish/scripts/ dir. This MUST be done
# before the imports that follow. parents[2] = skills dir (this file is at
# plugins/kb/skills/kb/scripts/migrate_multi_show.py).
_SIBLING_SCRIPTS = Path(__file__).resolve().parents[2] / "kb-publish" / "scripts"
if str(_SIBLING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SIBLING_SCRIPTS))

import hashlib
import io
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Any, Literal

import yaml

from shows import (
    Show, EpRef, load_shows, validate_shows,
    parse_ep_ref_field, UnknownShowError, MigrationRequiredError,
    ShowConfigError,
)
from state import load_state_file, write_state_file, find_pending_runs, find_pending_notebooks, PendingWorkError
from lock import kb_mutation_lock, LockBusyError
import episode_wiki as E


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

MIGRATION_DIR = ".kb-migration"
STAGING = "staging"
BEFORE = "before"
MANIFEST = "before/manifest.yaml"
COMMIT_LOG = "commit.log"
PLAN_FILE = "plan.yaml"


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class LiveDriftError(RuntimeError):
    """Live file was modified after Phase A snapshot (resume guard)."""


class ResumeMismatchError(RuntimeError):
    """--resume flags don't match the persisted Phase-A plan."""


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at path."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    """Write content atomically via temp file + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    os.replace(tmp_path, path)


def _rewrite_body_wikilinks(
    text: str,
    default_show_id: str,
    known_episode_files: dict[int, str],
) -> str:
    """Rewrite legacy body wikilinks to show-scoped form.

    Pattern matched: [[wiki/episodes/ep-N-slug]] and [[wiki/episodes/ep-N-slug|display]]
    Rewrites to: [[wiki/episodes/<default_show_id>/ep-N-slug]] (display preserved).

    known_episode_files: {ep_id: slug} mapping from staged episode filenames.
    Raises ValueError if an ep-N reference can't be resolved to a file on disk.
    """
    _LEGACY_EP_WL = re.compile(
        r'\[\[wiki/episodes/ep-(\d+)-([^\]\|]+)(\|[^\]]*)?\]\]'
    )

    def _replace(m: re.Match) -> str:
        ep_num = int(m.group(1))
        slug_in_link = m.group(2)
        display = m.group(3) or ""
        if ep_num not in known_episode_files:
            raise ValueError(
                f"unresolvable legacy wikilink ep-{ep_num}-{slug_in_link}: "
                f"no episode {ep_num} found on disk"
            )
        return f"[[wiki/episodes/{default_show_id}/ep-{ep_num}-{slug_in_link}{display}]]"

    return _LEGACY_EP_WL.sub(_replace, text)


# ---------------------------------------------------------------------------
# Phase A: plan + staging tree + snapshots
# ---------------------------------------------------------------------------

def phase_a_plan_and_stage(
    project_root: Path,
    *,
    default_show_id: str,
    default_show_title: str,
    default_show_hosts: list[str],
) -> dict:
    """Build .kb-migration/ containing plan.yaml, staging/, and before/ snapshots.

    Uses an atomic-build approach: builds in a temp dir
    (.kb-migration.tmp-<pid>/) then renames to .kb-migration/ only after all
    writes succeed.

    Returns the plan dict.
    """
    project_root = Path(project_root)
    kb_yaml_path = project_root / "kb.yaml"
    if not kb_yaml_path.exists():
        raise FileNotFoundError(f"kb.yaml not found at {kb_yaml_path}")

    kb = yaml.safe_load(kb_yaml_path.read_text(encoding="utf-8")) or {}
    integrations = kb.get("integrations") or {}
    notebooklm_cfg = integrations.get("notebooklm") or {}
    xiaoyuzhou_cfg = integrations.get("xiaoyuzhou") or {}

    wiki_path_str = notebooklm_cfg.get("wiki_path")
    if not wiki_path_str:
        raise ShowConfigError("integrations.notebooklm.wiki_path is required")
    wiki_path = Path(wiki_path_str)

    output_path_str = notebooklm_cfg.get("output_path")
    if not output_path_str:
        raise ShowConfigError("integrations.notebooklm.output_path is required")
    output_path = Path(output_path_str)

    state_path = project_root / ".notebooklm-state.yaml"

    # Build the staged kb.yaml
    podcast_cfg = notebooklm_cfg.get("podcast") or {}
    episodes_registry = xiaoyuzhou_cfg.get("episodes_registry", "episodes.yaml")

    show_entry = {
        "id": default_show_id,
        "title": default_show_title,
        "hosts": default_show_hosts,
        "wiki_episodes_dir": f"episodes/{default_show_id}",
        "episodes_registry": episodes_registry,
        "language": notebooklm_cfg.get("language", "zh_Hans"),
        "podcast_format": podcast_cfg.get("format", "deep-dive"),
        "podcast_length": podcast_cfg.get("length", "long"),
        "intro_music": podcast_cfg.get("intro_music"),
        "intro_music_length_seconds": podcast_cfg.get("intro_music_length_seconds", 12),
        "intro_crossfade_seconds": podcast_cfg.get("intro_crossfade_seconds", 3),
        "transcript": podcast_cfg.get("transcript") or {},
        "xiaoyuzhou": {
            "podcast_id": xiaoyuzhou_cfg.get("podcast_id"),
        },
    }

    # Build new kb.yaml dict
    new_kb = dict(kb)
    new_integrations = dict(integrations)
    new_integrations["shows"] = [show_entry]
    new_kb["integrations"] = new_integrations

    # --- Collect all episode files in legacy flat path ---
    episodes_flat_dir = wiki_path / "episodes"
    episode_files: dict[int, tuple[Path, str]] = {}  # ep_id -> (path, slug)

    if episodes_flat_dir.exists():
        for ep_file in sorted(episodes_flat_dir.glob("ep-*.md")):
            if not ep_file.is_file():
                continue
            stem = ep_file.stem  # e.g. "ep-1-test"
            m = re.match(r"^ep-(\d+)-(.+)$", stem)
            if m:
                ep_id = int(m.group(1))
                slug = m.group(2)
                episode_files[ep_id] = (ep_file, slug)

    # Build known_episode_files mapping {ep_id: slug}
    known_episode_files: dict[int, str] = {
        ep_id: slug for ep_id, (_, slug) in episode_files.items()
    }

    # --- Collect stubs ---
    stub_files: list[Path] = []
    for md_file in sorted(wiki_path.rglob("*.md")):
        rel = md_file.relative_to(wiki_path)
        parts = rel.parts
        # Skip anything in episodes/
        if parts and parts[0] == "episodes":
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end < 0:
            continue
        fm = yaml.safe_load(text[4:end]) or {}
        if fm.get("status") == "stub":
            stub_files.append(md_file)

    # --- Collect all wiki .md files that need body wikilink rewrites ---
    # (non-episode, non-stub files with legacy wikilinks)
    other_wiki_files: list[Path] = []  # files that are neither episode nor stub but have legacy wikilinks
    _LEGACY_WL_CHECK = re.compile(r'\[\[wiki/episodes/ep-\d+')

    stub_paths_set = set(stub_files)
    for md_file in sorted(wiki_path.rglob("*.md")):
        rel = md_file.relative_to(wiki_path)
        parts = rel.parts
        # Skip episode directory
        if parts and parts[0] == "episodes":
            continue
        # Skip stubs (handled separately)
        if md_file in stub_paths_set:
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if _LEGACY_WL_CHECK.search(text):
            other_wiki_files.append(md_file)

    # --- Validate all wikilinks can be resolved BEFORE writing anything ---
    # This is the fail-fast check to prevent half-written staging state.
    def _validate_wikilinks_in_text(text: str, source_path: Path) -> None:
        """Raise ValueError if any legacy ep-N wikilink can't be resolved."""
        _CHECK_RE = re.compile(r'\[\[wiki/episodes/ep-(\d+)-([^\]\|]+)(\|[^\]]*)?\]\]')
        for m in _CHECK_RE.finditer(text):
            ep_num = int(m.group(1))
            slug_in_link = m.group(2)
            if ep_num not in known_episode_files:
                raise ValueError(
                    f"unresolvable legacy wikilink [[wiki/episodes/ep-{ep_num}-{slug_in_link}]] "
                    f"in {source_path}: no episode {ep_num} file on disk"
                )

    # Validate all episode articles
    for ep_id, (ep_file, slug) in episode_files.items():
        try:
            text = ep_file.read_text(encoding="utf-8")
        except OSError:
            continue
        _validate_wikilinks_in_text(text, ep_file)

    # Validate all stubs
    for stub_file in stub_files:
        try:
            text = stub_file.read_text(encoding="utf-8")
        except OSError:
            continue
        _validate_wikilinks_in_text(text, stub_file)

    # Validate all other wiki files
    for other_file in other_wiki_files:
        try:
            text = other_file.read_text(encoding="utf-8")
        except OSError:
            continue
        _validate_wikilinks_in_text(text, other_file)

    # --- All validation passed — now build staging in a temp dir ---
    final_migration_dir = project_root / MIGRATION_DIR
    tmp_migration_dir = project_root / f".kb-migration.tmp-{os.getpid()}"

    # Clean up any leftover temp dir
    if tmp_migration_dir.exists():
        shutil.rmtree(tmp_migration_dir)

    try:
        tmp_migration_dir.mkdir(parents=True)
        staging_dir = tmp_migration_dir / STAGING
        before_dir = tmp_migration_dir / BEFORE
        staging_dir.mkdir(parents=True)
        before_dir.mkdir(parents=True)

        manifest_entries: list[dict] = []
        commit_order: list[dict] = []

        # --- Stage episode articles ---
        for ep_id in sorted(episode_files.keys()):
            ep_file, slug = episode_files[ep_id]

            text = ep_file.read_text(encoding="utf-8")

            # Parse and rewrite frontmatter
            if text.startswith("---\n"):
                end = text.find("\n---\n", 4)
                if end >= 0:
                    fm_raw = text[4:end]
                    body_after = text[end + 5:]  # after closing ---\n
                    fm = yaml.safe_load(fm_raw) or {}

                    # Rewrite index.concepts[].prior_episode_ref
                    idx = fm.get("index") or {}
                    concepts = idx.get("concepts") or []
                    for c in concepts:
                        per = c.get("prior_episode_ref")
                        if per is not None:
                            c["prior_episode_ref"] = EpRef.from_legacy(
                                per, default_show=default_show_id
                            ).to_dict()
                        # else leave as null

                    # Rewrite index.series_links.builds_on
                    sl = idx.get("series_links") or {}
                    builds_on = sl.get("builds_on") or []
                    new_builds_on = []
                    for b in builds_on:
                        if b is None:
                            continue
                        if isinstance(b, (int, str)):
                            new_builds_on.append(
                                EpRef.from_legacy(b, default_show=default_show_id).to_dict()
                            )
                        elif isinstance(b, dict):
                            # Already dict form — leave as is
                            new_builds_on.append(b)
                        else:
                            new_builds_on.append(b)
                    sl["builds_on"] = new_builds_on
                    idx["series_links"] = sl
                    idx["concepts"] = concepts
                    fm["index"] = idx

                    # Rewrite body wikilinks
                    rewritten_body = _rewrite_body_wikilinks(
                        body_after, default_show_id, known_episode_files
                    )

                    # Serialize
                    staged_text = "---\n" + yaml.safe_dump(
                        fm, allow_unicode=True, sort_keys=False
                    ) + "---\n\n" + rewritten_body
                else:
                    staged_text = text
            else:
                staged_text = text

            # New path: wiki/episodes/<show-id>/ep-N-slug.md
            new_rel_wiki = Path("episodes") / default_show_id / f"ep-{ep_id}-{slug}.md"
            staged_ep_path = staging_dir / "wiki" / new_rel_wiki
            staged_ep_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(staged_ep_path, staged_text.encode("utf-8"))

            # Snapshot the legacy flat file
            old_rel_wiki = Path("episodes") / f"ep-{ep_id}-{slug}.md"
            before_ep_path = before_dir / "wiki" / old_rel_wiki
            before_ep_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ep_file, before_ep_path)

            sha256_before = _sha256(ep_file)
            sha256_staged = _sha256(staged_ep_path)

            # commit_order uses relative-to-project-root paths
            new_live_rel = Path("wiki") / new_rel_wiki  # wiki/episodes/show/ep-N-slug.md
            old_live_rel = Path("wiki") / old_rel_wiki  # wiki/episodes/ep-N-slug.md (legacy)

            commit_entry = {
                "relative_path": str(new_live_rel),
                "category": "episode",
                "legacy_path": str(old_live_rel),
            }
            commit_order.append(commit_entry)

            manifest_entries.append({
                "relative_path": str(new_live_rel),
                "existed_before": False,
                "sha256_before": None,
                "sha256_staged": sha256_staged,
                "category": "episode",
                "legacy_path": str(old_live_rel),
                "snapshot_path": str(Path("wiki") / old_rel_wiki),
            })

        # --- Stage stubs ---
        for stub_file in sorted(stub_files):
            text = stub_file.read_text(encoding="utf-8")

            if text.startswith("---\n"):
                end = text.find("\n---\n", 4)
                if end >= 0:
                    fm_raw = text[4:end]
                    body_after = text[end + 5:]
                    fm = yaml.safe_load(fm_raw) or {}

                    # Rewrite single-value ep ref fields
                    for field in ("created_by", "last_seen_by", "best_depth_episode"):
                        val = fm.get(field)
                        if val is not None and isinstance(val, (str, int)):
                            fm[field] = EpRef.from_legacy(
                                val, default_show=default_show_id
                            ).to_dict()

                    # Rewrite referenced_by list
                    ref_by = fm.get("referenced_by")
                    if isinstance(ref_by, list):
                        new_refs = []
                        for r in ref_by:
                            if isinstance(r, (str, int)):
                                new_refs.append(
                                    EpRef.from_legacy(
                                        r, default_show=default_show_id
                                    ).to_dict()
                                )
                            else:
                                new_refs.append(r)
                        fm["referenced_by"] = new_refs

                    # Rewrite body wikilinks
                    rewritten_body = _rewrite_body_wikilinks(
                        body_after, default_show_id, known_episode_files
                    )

                    staged_text = "---\n" + yaml.safe_dump(
                        fm, allow_unicode=True, sort_keys=False
                    ) + "---\n\n" + rewritten_body
                else:
                    staged_text = text
            else:
                staged_text = text

            # Staged path: same relative path from wiki root
            rel_from_wiki = stub_file.relative_to(wiki_path)
            staged_stub_path = staging_dir / "wiki" / rel_from_wiki
            staged_stub_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(staged_stub_path, staged_text.encode("utf-8"))

            # Snapshot
            before_stub_path = before_dir / "wiki" / rel_from_wiki
            before_stub_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stub_file, before_stub_path)

            sha256_before = _sha256(stub_file)
            sha256_staged = _sha256(staged_stub_path)

            live_rel = Path("wiki") / rel_from_wiki

            commit_order.append({
                "relative_path": str(live_rel),
                "category": "stub",
            })
            manifest_entries.append({
                "relative_path": str(live_rel),
                "existed_before": True,
                "sha256_before": sha256_before,
                "sha256_staged": sha256_staged,
                "category": "stub",
            })

        # --- Stage other wiki files (with legacy wikilinks, non-episode non-stub) ---
        for other_file in sorted(other_wiki_files):
            text = other_file.read_text(encoding="utf-8")
            rewritten_text = _rewrite_body_wikilinks(text, default_show_id, known_episode_files)

            rel_from_wiki = other_file.relative_to(wiki_path)
            staged_other_path = staging_dir / "wiki" / rel_from_wiki
            staged_other_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(staged_other_path, rewritten_text.encode("utf-8"))

            # Snapshot
            before_other_path = before_dir / "wiki" / rel_from_wiki
            before_other_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(other_file, before_other_path)

            sha256_before = _sha256(other_file)
            sha256_staged = _sha256(staged_other_path)

            live_rel = Path("wiki") / rel_from_wiki

            commit_order.append({
                "relative_path": str(live_rel),
                "category": "other",
            })
            manifest_entries.append({
                "relative_path": str(live_rel),
                "existed_before": True,
                "sha256_before": sha256_before,
                "sha256_staged": sha256_staged,
                "category": "other",
            })

        # --- Stage state file ---
        staged_state_path = staging_dir / ".notebooklm-state.yaml"
        state = load_state_file(state_path, default_show_id=default_show_id)
        write_state_file(staged_state_path, state)

        # Snapshot state file
        before_state_path = before_dir / ".notebooklm-state.yaml"
        if state_path.exists():
            shutil.copy2(state_path, before_state_path)
            sha256_before_state = _sha256(state_path)
        else:
            sha256_before_state = None

        sha256_staged_state = _sha256(staged_state_path)

        commit_order.append({
            "relative_path": ".notebooklm-state.yaml",
            "category": "state",
        })
        manifest_entries.append({
            "relative_path": ".notebooklm-state.yaml",
            "existed_before": state_path.exists(),
            "sha256_before": sha256_before_state,
            "sha256_staged": sha256_staged_state,
            "category": "state",
        })

        # --- Stage kb.yaml ---
        staged_kb_path = staging_dir / "kb.yaml"
        staged_kb_content = yaml.safe_dump(
            new_kb, allow_unicode=True, sort_keys=False
        ).encode("utf-8")
        _atomic_write(staged_kb_path, staged_kb_content)

        # Snapshot kb.yaml
        before_kb_path = before_dir / "kb.yaml"
        shutil.copy2(kb_yaml_path, before_kb_path)
        sha256_before_kb = _sha256(kb_yaml_path)
        sha256_staged_kb = _sha256(staged_kb_path)

        # kb.yaml goes LAST in commit_order
        commit_order.append({
            "relative_path": "kb.yaml",
            "category": "kb",
        })
        manifest_entries.append({
            "relative_path": "kb.yaml",
            "existed_before": True,
            "sha256_before": sha256_before_kb,
            "sha256_staged": sha256_staged_kb,
            "category": "kb",
        })

        # --- Write manifest.yaml ---
        manifest_path = tmp_migration_dir / MANIFEST
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            manifest_path,
            yaml.safe_dump(manifest_entries, allow_unicode=True, sort_keys=False).encode("utf-8"),
        )

        # --- Write plan.yaml ---
        plan = {
            "default_show_id": default_show_id,
            "default_show_title": default_show_title,
            "default_show_hosts": list(default_show_hosts),
            "wiki_path": str(wiki_path),
            "output_path": str(output_path),
            "commit_order": commit_order,
        }

        plan_path = tmp_migration_dir / PLAN_FILE
        _atomic_write(
            plan_path,
            yaml.safe_dump(plan, allow_unicode=True, sort_keys=False).encode("utf-8"),
        )

        # --- Atomic rename of temp dir to final dir ---
        if final_migration_dir.exists():
            shutil.rmtree(final_migration_dir)
        tmp_migration_dir.rename(final_migration_dir)

        return plan

    except Exception:
        # Clean up partial temp dir — never leave half-written state
        if tmp_migration_dir.exists():
            shutil.rmtree(tmp_migration_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# Phase A-bis: atomic sidecar in-place migration
# ---------------------------------------------------------------------------

def phase_a_bis_sidecars(project_root: Path, plan: dict) -> None:
    """Scan output/*.manifest.yaml and output/notebooklm/*.manifest.yaml.

    For each sidecar:
    1. Snapshot bytes to .kb-migration/before/sidecars/<relative>.
    2. Rewrite in-place atomically (temp+fsync+os.replace) adding show: <default_show_id>.

    On any failure, restore from snapshots (best-effort).
    """
    project_root = Path(project_root)
    migration_dir = project_root / MIGRATION_DIR
    before_sidecars_dir = migration_dir / BEFORE / "sidecars"
    before_sidecars_dir.mkdir(parents=True, exist_ok=True)

    default_show_id = plan["default_show_id"]
    output_path = Path(plan["output_path"])

    # Collect all sidecar paths from both locations
    sidecar_paths: list[Path] = []
    for pattern_base in (output_path, output_path / "notebooklm"):
        if pattern_base.exists():
            for p in sorted(pattern_base.glob("*.manifest.yaml")):
                if p.is_file():
                    sidecar_paths.append(p)

    # Track which ones have been rewritten (for rollback)
    rewritten: list[tuple[Path, Path]] = []  # (live_path, snapshot_path)

    for sidecar_path in sidecar_paths:
        # Compute relative path for snapshot key
        try:
            rel = sidecar_path.relative_to(project_root)
        except ValueError:
            rel = Path(sidecar_path.name)

        snapshot_path = before_sidecars_dir / rel
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        # Snapshot BEFORE rewriting
        shutil.copy2(sidecar_path, snapshot_path)

        # Rewrite: add show: field
        try:
            content = yaml.safe_load(sidecar_path.read_text(encoding="utf-8")) or {}
            if not isinstance(content, dict):
                content = {}
        except Exception:
            content = {}

        content["show"] = default_show_id

        new_bytes = yaml.safe_dump(
            content, allow_unicode=True, sort_keys=False
        ).encode("utf-8")

        try:
            _atomic_write(sidecar_path, new_bytes)
        except Exception:
            # Restore all rewritten sidecars, then re-raise
            _restore_sidecars_from_snapshots(rewritten)
            raise

        rewritten.append((sidecar_path, snapshot_path))


def _restore_sidecars_from_snapshots(
    rewritten: list[tuple[Path, Path]],
) -> None:
    """Restore sidecar files from their snapshots (byte-exact)."""
    for live_path, snapshot_path in rewritten:
        try:
            if snapshot_path.exists():
                shutil.copy2(snapshot_path, live_path)
        except OSError:
            pass  # best-effort


def restore_sidecars_from_snapshots(project_root: Path, plan: dict) -> None:
    """Public API: restore all sidecar snapshots from .kb-migration/before/sidecars/."""
    project_root = Path(project_root)
    before_sidecars_dir = project_root / MIGRATION_DIR / BEFORE / "sidecars"
    if not before_sidecars_dir.exists():
        return

    output_path = Path(plan["output_path"])

    for snapshot_path in sorted(before_sidecars_dir.rglob("*.manifest.yaml")):
        try:
            rel = snapshot_path.relative_to(before_sidecars_dir)
        except ValueError:
            continue

        # Find the live path: could be relative to project_root or absolute
        # Try to reconstruct from the relative path stored under before/sidecars/
        live_path = project_root / rel
        if live_path.exists() or (project_root / rel).parent.exists():
            shutil.copy2(snapshot_path, live_path)


# ---------------------------------------------------------------------------
# Phase B: full validation of staged tree + live sidecars
# ---------------------------------------------------------------------------

def phase_b_validate(project_root: Path, plan: dict) -> None:
    """Validate the staged tree and live sidecars.

    On ANY failure: restore Phase A-bis sidecars from snapshot, delete
    .kb-migration/staging/ (keep before/ for debugging), then raise.
    """
    project_root = Path(project_root)
    migration_dir = project_root / MIGRATION_DIR
    staging_dir = migration_dir / STAGING

    default_show_id = plan["default_show_id"]
    default_show_title = plan["default_show_title"]
    default_show_hosts = plan.get("default_show_hosts", [])

    errors: list[str] = []

    try:
        # 1. Load staging/kb.yaml → load_shows must succeed
        staged_kb_path = staging_dir / "kb.yaml"
        if not staged_kb_path.exists():
            raise ValueError("staging/kb.yaml missing")

        kb_raw = yaml.safe_load(staged_kb_path.read_text(encoding="utf-8")) or {}
        try:
            # Use a dummy wiki_path for validation — the staged wiki
            staged_wiki_path = staging_dir / "wiki"
            shows = load_shows(kb_raw, project_root=project_root)
        except ShowConfigError as e:
            errors.append(f"staging/kb.yaml load_shows failed: {e}")
            shows = []

        if not shows:
            # Build a minimal show for further validation
            from shows import Show
            try:
                shows = [Show(
                    id=default_show_id,
                    title=default_show_title,
                    description="",
                    default=False,
                    language="zh_Hans",
                    hosts=list(default_show_hosts),
                    extra_host_names=[],
                    intro_music=None,
                    intro_music_length_seconds=12,
                    intro_crossfade_seconds=3,
                    podcast_format="deep-dive",
                    podcast_length="long",
                    transcript={},
                    episodes_registry="episodes.yaml",
                    wiki_episodes_dir=f"episodes/{default_show_id}",
                    xiaoyuzhou={},
                )]
            except Exception:
                pass

        known_shows_set = {s.id for s in shows}

        # 2. For each show, scan_episode_wiki(staging/wiki, show, strict=True)
        staged_wiki = staging_dir / "wiki"
        for show in shows:
            try:
                episodes = E.scan_episode_wiki(staged_wiki, show, strict=True)
                for ep in episodes:
                    # Validate prior_episode_ref fields
                    for concept in ep.concepts:
                        per = concept.prior_episode_ref
                        if per is not None:
                            if isinstance(per, (str, int)):
                                errors.append(
                                    f"episode {ep.episode_id} concept {concept.slug}: "
                                    f"legacy prior_episode_ref: {per!r}"
                                )
                            elif isinstance(per, dict):
                                try:
                                    parse_ep_ref_field(per, known_shows=known_shows_set)
                                except Exception as e:
                                    errors.append(
                                        f"episode {ep.episode_id} concept {concept.slug}: "
                                        f"invalid prior_episode_ref: {e}"
                                    )
            except E.EpisodeParseError as e:
                errors.append(f"scan_episode_wiki failed for show {show.id}: {e}")
            except MigrationRequiredError as e:
                errors.append(f"migration required error in staged episode: {e}")

        # 3. Parse every stub's frontmatter — no legacy str/int remaining
        for md_file in sorted(staged_wiki.rglob("*.md")):
            rel = md_file.relative_to(staged_wiki)
            if rel.parts and rel.parts[0] == "episodes":
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            if not text.startswith("---\n"):
                continue
            end = text.find("\n---\n", 4)
            if end < 0:
                continue
            fm = yaml.safe_load(text[4:end]) or {}
            if fm.get("status") != "stub":
                continue

            # Check stub EpRef fields
            for field_name in ("created_by", "last_seen_by", "best_depth_episode"):
                val = fm.get(field_name)
                if val is not None:
                    if isinstance(val, (str, int)):
                        errors.append(
                            f"stub {rel}: {field_name} is legacy form: {val!r}"
                        )
                    elif isinstance(val, dict):
                        try:
                            parse_ep_ref_field(val, known_shows=known_shows_set)
                        except (UnknownShowError, ValueError) as e:
                            errors.append(f"stub {rel}: {field_name} invalid: {e}")

            ref_by = fm.get("referenced_by")
            if isinstance(ref_by, list):
                for i, r in enumerate(ref_by):
                    if isinstance(r, (str, int)):
                        errors.append(
                            f"stub {rel}: referenced_by[{i}] is legacy form: {r!r}"
                        )
                    elif isinstance(r, dict):
                        try:
                            parse_ep_ref_field(r, known_shows=known_shows_set)
                        except (UnknownShowError, ValueError) as e:
                            errors.append(
                                f"stub {rel}: referenced_by[{i}] invalid: {e}"
                            )

            # 4. validate_body_wikilinks on body
            body_start = end + 5
            body = text[body_start:]
            wl_errors = E.validate_body_wikilinks(body, known_shows_set)
            for we in wl_errors:
                errors.append(f"stub {rel} body: {we}")

        # 5. validate_body_wikilinks on all episode article bodies in staged wiki
        for show in shows:
            ep_dir = staged_wiki / show.wiki_episodes_dir
            if not ep_dir.exists():
                continue
            for ep_file in sorted(ep_dir.glob("ep-*.md")):
                try:
                    text = ep_file.read_text(encoding="utf-8")
                except OSError:
                    continue
                if not text.startswith("---\n"):
                    continue
                end = text.find("\n---\n", 4)
                if end < 0:
                    continue
                body = text[end + 5:]
                wl_errors = E.validate_body_wikilinks(body, known_shows_set)
                rel = ep_file.relative_to(staged_wiki)
                for we in wl_errors:
                    errors.append(f"episode {rel} body: {we}")

        # 6. validate_body_wikilinks on all other wiki files in staged wiki
        for md_file in sorted(staged_wiki.rglob("*.md")):
            rel = md_file.relative_to(staged_wiki)
            if rel.parts and rel.parts[0] == "episodes":
                continue  # already handled above
            # Skip stubs (already handled)
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            if text.startswith("---\n"):
                end = text.find("\n---\n", 4)
                if end >= 0:
                    fm = yaml.safe_load(text[4:end]) or {}
                    if fm.get("status") == "stub":
                        continue  # stub already checked above
                    body = text[end + 5:]
                else:
                    body = text
            else:
                body = text
            wl_errors = E.validate_body_wikilinks(body, known_shows_set)
            for we in wl_errors:
                errors.append(f"other wiki file {rel} body: {we}")

        # 7. Load staged state file
        staged_state_path = staging_dir / ".notebooklm-state.yaml"
        try:
            state = load_state_file(staged_state_path, default_show_id=default_show_id)
            if "shows" not in state:
                errors.append("staged .notebooklm-state.yaml missing 'shows' key")
        except Exception as e:
            errors.append(f"staged .notebooklm-state.yaml load failed: {e}")

        # 8. Every live sidecar must now have show: <default_show_id>
        output_path = Path(plan["output_path"])
        for pattern_base in (output_path, output_path / "notebooklm"):
            if not pattern_base.exists():
                continue
            for sidecar_path in sorted(pattern_base.glob("*.manifest.yaml")):
                if not sidecar_path.is_file():
                    continue
                try:
                    content = yaml.safe_load(sidecar_path.read_text(encoding="utf-8")) or {}
                    if content.get("show") != default_show_id:
                        errors.append(
                            f"sidecar {sidecar_path.name}: missing or wrong show field "
                            f"(got {content.get('show')!r}, expected {default_show_id!r})"
                        )
                except Exception as e:
                    errors.append(f"sidecar {sidecar_path.name}: load failed: {e}")

        if errors:
            raise ValueError("Phase B validation failed:\n" + "\n".join(errors))

    except Exception:
        # Restore sidecars from snapshots
        _restore_sidecars_phase_b(project_root, plan)
        # Delete staging dir but keep before/ for debugging
        staging_path = migration_dir / STAGING
        if staging_path.exists():
            shutil.rmtree(staging_path)
        raise


def _restore_sidecars_phase_b(project_root: Path, plan: dict) -> None:
    """Restore all sidecar snapshots from .kb-migration/before/sidecars/."""
    migration_dir = project_root / MIGRATION_DIR
    before_sidecars_dir = migration_dir / BEFORE / "sidecars"
    if not before_sidecars_dir.exists():
        return

    for snapshot_path in sorted(before_sidecars_dir.rglob("*.manifest.yaml")):
        try:
            rel = snapshot_path.relative_to(before_sidecars_dir)
        except ValueError:
            continue
        live_path = project_root / rel
        try:
            shutil.copy2(snapshot_path, live_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Phase C: copy-then-verify commit with commit.log + resume
# ---------------------------------------------------------------------------

def phase_c_commit(
    project_root: Path,
    plan: dict,
    *,
    resume: bool = False,
) -> None:
    """Per-entry copy-then-verify to live tree with sha256 commit.log.

    For each entry in plan.commit_order:
    1. Check commit.log — if already committed, skip.
    2. If not in log, check for live drift (sha256 guard).
    3. Copy staged → live (atomic).
    4. sha256-verify live matches staged.
    5. Append to commit.log.
    6. For "episode" entries: delete the legacy flat file.

    kb.yaml is committed LAST.
    """
    project_root = Path(project_root)
    migration_dir = project_root / MIGRATION_DIR
    staging_dir = migration_dir / STAGING
    commit_log_path = migration_dir / COMMIT_LOG
    manifest_path = migration_dir / MANIFEST

    commit_order = plan.get("commit_order") or []
    default_show_id = plan["default_show_id"]

    # Load manifest for drift-guard lookups
    manifest_entries: dict[str, dict] = {}
    if manifest_path.exists():
        raw_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or []
        for entry in raw_manifest:
            rel_path = entry.get("relative_path")
            if rel_path:
                manifest_entries[rel_path] = entry

    # Load existing commit.log
    committed: dict[str, str] = {}  # relative_path -> sha256_committed
    if commit_log_path.exists():
        raw_log = yaml.safe_load(commit_log_path.read_text(encoding="utf-8")) or []
        if isinstance(raw_log, list):
            for entry in raw_log:
                rel = entry.get("relative_path")
                sha = entry.get("sha256_committed")
                if rel and sha:
                    committed[rel] = sha

    for entry in commit_order:
        rel_path = entry["relative_path"]
        category = entry.get("category", "")
        legacy_path = entry.get("legacy_path")

        live_path = project_root / rel_path
        staged_path = staging_dir / rel_path

        if not staged_path.exists():
            raise FileNotFoundError(
                f"Staged file not found: {staged_path}"
            )

        sha256_staged = _sha256(staged_path)

        # --- Resume check ---
        if rel_path in committed:
            # Already in commit.log — verify and skip
            # (Handle legacy-delete even if log shows committed)
            if category == "episode" and legacy_path:
                legacy_live = project_root / legacy_path
                if legacy_live.exists():
                    legacy_live.unlink()
            continue

        # Compute sha256 of live file if it exists
        sha256_live = _sha256(live_path) if live_path.exists() else None

        # First check: if live matches staged → already committed (log was lost)
        if sha256_live == sha256_staged:
            # Treat as already committed — append to log and skip copy
            _append_commit_log(
                commit_log_path,
                rel_path=rel_path,
                sha256_committed=sha256_staged,
            )
            committed[rel_path] = sha256_staged
            # Handle legacy delete
            if category == "episode" and legacy_path:
                legacy_live = project_root / legacy_path
                if legacy_live.exists():
                    legacy_live.unlink()
            continue

        # Drift guard
        manifest_entry = manifest_entries.get(rel_path)
        if manifest_entry:
            existed_before = manifest_entry.get("existed_before", True)
            sha256_before = manifest_entry.get("sha256_before")

            if existed_before:
                # Live file MUST match sha256_before (or not exist, which is also drift)
                if sha256_live is None:
                    # File existed before but is now gone — that's unexpected but not drift per se
                    # Actually: if it existed before and is now missing, that IS drift
                    raise LiveDriftError(
                        f"Live file {rel_path} was expected to exist (existed_before=True) "
                        f"but is missing"
                    )
                if sha256_live != sha256_before:
                    raise LiveDriftError(
                        f"Live file {rel_path} has been modified after Phase A snapshot "
                        f"(expected sha256={sha256_before!r}, got {sha256_live!r})"
                    )
            else:
                # File did not exist before — if it now exists with unexpected bytes, that's drift
                if sha256_live is not None:
                    raise LiveDriftError(
                        f"Live file {rel_path} was expected to not exist (existed_before=False) "
                        f"but found with unexpected bytes (sha256={sha256_live!r})"
                    )

        # --- Copy staged → live (atomic) ---
        live_path.parent.mkdir(parents=True, exist_ok=True)
        staged_bytes = staged_path.read_bytes()
        _atomic_write(live_path, staged_bytes)

        # --- sha256-verify ---
        sha256_live_after = _sha256(live_path)
        if sha256_live_after != sha256_staged:
            # Verification failed — do NOT append to log or delete legacy
            raise RuntimeError(
                f"sha256 mismatch after copying {rel_path}: "
                f"expected {sha256_staged!r}, got {sha256_live_after!r}"
            )

        # --- Append to commit.log ---
        _append_commit_log(
            commit_log_path,
            rel_path=rel_path,
            sha256_committed=sha256_staged,
        )
        committed[rel_path] = sha256_staged

        # --- Delete legacy flat file (episodes only, AFTER commit.log written) ---
        if category == "episode" and legacy_path:
            legacy_live = project_root / legacy_path
            if legacy_live.exists():
                legacy_live.unlink()


def _append_commit_log(
    commit_log_path: Path,
    *,
    rel_path: str,
    sha256_committed: str,
) -> None:
    """Atomically append a commit log entry."""
    # Load existing log
    existing: list[dict] = []
    if commit_log_path.exists():
        raw = yaml.safe_load(commit_log_path.read_text(encoding="utf-8")) or []
        if isinstance(raw, list):
            existing = raw

    existing.append({
        "relative_path": rel_path,
        "sha256_committed": sha256_committed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    _atomic_write(
        commit_log_path,
        yaml.safe_dump(existing, allow_unicode=True, sort_keys=False).encode("utf-8"),
    )


# ---------------------------------------------------------------------------
# Detection (Task 13 — preserved)
# ---------------------------------------------------------------------------

def classify_kb_state(project_root) -> Literal["unmigrated", "partially_migrated", "fully_migrated"]:
    """Classify a KB's migration state based on kb.yaml and the wiki layout.

    - ``unmigrated``: kb.yaml lacks ``integrations.shows[]``.
    - ``partially_migrated``: kb.yaml has shows[] but flat ``wiki/episodes/ep-*.md`` files remain.
    - ``fully_migrated``: kb.yaml has shows[] AND no flat ``wiki/episodes/ep-*.md`` files.
    """
    project_root = Path(project_root)
    kb_yaml_path = project_root / "kb.yaml"
    if not kb_yaml_path.exists():
        raise FileNotFoundError(f"kb.yaml not found at {kb_yaml_path}")

    kb = yaml.safe_load(kb_yaml_path.read_text(encoding="utf-8")) or {}
    shows = (kb.get("integrations") or {}).get("shows")
    if not isinstance(shows, list) or not shows:
        return "unmigrated"

    # Resolve wiki_path (may be absolute in kb.yaml)
    wiki_path_str = ((kb.get("integrations") or {}).get("notebooklm") or {}).get("wiki_path")
    if wiki_path_str:
        wiki_path = Path(wiki_path_str)
    else:
        wiki_path = project_root / "wiki"

    # Scan for flat episode files directly under wiki/episodes/
    episodes_flat_dir = wiki_path / "episodes"
    if episodes_flat_dir.exists():
        for p in episodes_flat_dir.glob("ep-*.md"):
            if p.is_file():
                return "partially_migrated"

    return "fully_migrated"


# ---------------------------------------------------------------------------
# CLI entry point (full migration CLI in Task 18 — stub here)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="KB project root (contains kb.yaml)")
    parser.add_argument(
        "--classify-only",
        action="store_true",
        help="Just classify the KB and print the state; no migration.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if args.classify_only:
        print(classify_kb_state(project_root))
        sys.exit(0)

    # Full migration flow comes in Tasks 14-18.
    print(
        "Full migration not implemented yet — this is Task 13 (detection only).",
        file=sys.stderr,
    )
    sys.exit(2)
