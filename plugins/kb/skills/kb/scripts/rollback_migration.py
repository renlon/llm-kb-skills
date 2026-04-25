#!/usr/bin/env python3
"""Rollback a multi-show migration using .kb-migration/before/ snapshots.

Worst-case escape hatch — only run if something went wrong on the
real KB after running /kb migrate. Verifies pending-work is idle,
acquires kb_mutation_lock, then for each manifest entry:
- existed_before=true  → restore from before/<path> snapshot.
- existed_before=false → delete the live file if its sha256 matches
  sha256_staged (don't destroy user edits).
- Sidecars from Phase A-bis → restored from before/sidecars/.

Renames .kb-migration/ to .kb-migration.rolled-back-<timestamp>/ so
the user can inspect what happened.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_SIBLING_SCRIPTS = Path(__file__).resolve().parents[2] / "kb-publish" / "scripts"
if str(_SIBLING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SIBLING_SCRIPTS))

import yaml

from state import load_state_file, find_pending_runs, find_pending_notebooks, PendingWorkError
from lock import kb_mutation_lock, LockBusyError


# ---------------------------------------------------------------------------
# Constants (mirror migrate_multi_show.py)
# ---------------------------------------------------------------------------

MIGRATION_DIR = ".kb-migration"
BEFORE = "before"
MANIFEST = "before/manifest.yaml"
PLAN_FILE = "plan.yaml"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    """Return hex SHA-256 digest of the file at path."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy src → dst atomically via temp file + os.replace."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dst.parent), prefix=dst.name + ".", suffix=".tmp")
    try:
        data = src.read_bytes()
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    os.replace(tmp_path, dst)


# ---------------------------------------------------------------------------
# Core rollback logic
# ---------------------------------------------------------------------------

def _rollback_order(commit_order: list[dict]) -> list[dict]:
    """Return entries in rollback order.

    kb.yaml (the last entry in commit_order) must be restored LAST.
    If a crash occurs mid-rollback, kb.yaml remaining in multi-show
    form keeps the KB in a "still migrated" state — the user can
    safely retry the rollback. Restoring kb.yaml first and then
    crashing would leave a confused legacy kb.yaml + nested wiki
    files with no clean retry path.

    Algorithm: reverse commit_order, but move the kb.yaml entry back
    to the end.
    """
    reversed_order = list(reversed(commit_order))
    kb_entries = [e for e in reversed_order if e.get("category") == "kb"]
    non_kb_entries = [e for e in reversed_order if e.get("category") != "kb"]
    return non_kb_entries + kb_entries


def rollback(project_root: Path, *, yes: bool = False) -> int:
    """Execute the rollback. Returns an integer exit code.

    Exit codes:
      0  — rollback complete
      1  — unexpected error
      2  — nothing to roll back / pending work
      75 — lock held by another process
    """
    project_root = project_root.resolve()
    migration_dir = project_root / MIGRATION_DIR
    manifest_path = migration_dir / MANIFEST
    plan_path = migration_dir / PLAN_FILE

    # Step 1: Verify .kb-migration/before/manifest.yaml exists
    if not manifest_path.exists():
        print(
            f"Nothing to roll back: {manifest_path} not found.",
            file=sys.stderr,
        )
        return 2

    # Step 2: Load manifest + plan
    manifest_entries_list: list[dict] = yaml.safe_load(
        manifest_path.read_text(encoding="utf-8")
    ) or []
    manifest_by_path: dict[str, dict] = {
        e["relative_path"]: e for e in manifest_entries_list
    }

    plan: dict = {}
    if plan_path.exists():
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}

    default_show_id = plan.get("default_show_id", "")
    commit_order: list[dict] = plan.get("commit_order") or []

    # Step 3: Acquire lock
    try:
        with kb_mutation_lock(project_root, command="kb-rollback-migration", timeout=5.0):
            return _do_rollback(
                project_root=project_root,
                migration_dir=migration_dir,
                manifest_by_path=manifest_by_path,
                commit_order=commit_order,
                default_show_id=default_show_id,
                yes=yes,
            )
    except LockBusyError as exc:
        print(f"Cannot acquire lock: {exc}", file=sys.stderr)
        return 75


def _do_rollback(
    *,
    project_root: Path,
    migration_dir: Path,
    manifest_by_path: dict[str, dict],
    commit_order: list[dict],
    default_show_id: str,
    yes: bool,
) -> int:
    """Inner rollback body, called while lock is held."""
    state_path = project_root / ".notebooklm-state.yaml"

    # Step 4: Check for pending work using the (possibly migrated) state file
    state = load_state_file(state_path, default_show_id=default_show_id)
    pending_runs = find_pending_runs(state)
    pending_nb = find_pending_notebooks(state)
    if pending_runs or pending_nb:
        print(
            f"Cannot roll back: {len(pending_runs)} pending run(s) and "
            f"{len(pending_nb)} pending notebook(s) in state file. "
            f"Wait for them to complete first.",
            file=sys.stderr,
        )
        raise PendingWorkError(
            f"{len(pending_runs)} pending runs, {len(pending_nb)} pending notebooks"
        )

    # Step 5: Sanity prompt (unless --yes)
    before_dir = migration_dir / BEFORE
    n_to_restore = sum(
        1 for e in manifest_by_path.values() if e.get("existed_before")
    )
    n_pre_existing = n_to_restore  # alias for clarity
    n_new = sum(
        1 for e in manifest_by_path.values() if not e.get("existed_before")
    )

    if not yes:
        print(
            f"\nRollback summary:\n"
            f"  {n_to_restore} file(s) to restore from before/ snapshot\n"
            f"  {n_new} file(s) created by migration (will be deleted if unedited)\n"
        )
        sys.stderr.write("Roll back this migration? [y/N] ")
        sys.stderr.flush()
        try:
            resp = input().strip().lower()
        except EOFError:
            resp = ""
        if resp not in ("y", "yes"):
            print("Aborted.")
            return 1

    # Step 6: Process manifest entries in rollback order
    order = _rollback_order(commit_order)

    n_restored = 0
    n_deleted = 0
    n_skipped = 0

    for entry in order:
        rel_path = entry["relative_path"]
        manifest_entry = manifest_by_path.get(rel_path)
        if manifest_entry is None:
            # Entry in commit_order but not in manifest — skip silently
            continue

        existed_before: bool = bool(manifest_entry.get("existed_before"))
        sha256_before: str | None = manifest_entry.get("sha256_before")
        sha256_staged: str | None = manifest_entry.get("sha256_staged")
        snapshot_path_rel: str | None = manifest_entry.get("snapshot_path")

        live_path = project_root / rel_path

        if existed_before:
            # Restore from before/ snapshot
            # The snapshot_path field (if present) gives the relative path within
            # before/; otherwise use relative_path directly.
            if snapshot_path_rel:
                snapshot_path = before_dir / snapshot_path_rel
            else:
                snapshot_path = before_dir / rel_path

            if not snapshot_path.exists():
                print(
                    f"  WARN: snapshot missing for {rel_path} at {snapshot_path}; skipping.",
                    file=sys.stderr,
                )
                n_skipped += 1
                continue

            _atomic_copy(snapshot_path, live_path)

            # Verify sha256
            if sha256_before is not None:
                live_sha = _sha256(live_path)
                if live_sha != sha256_before:
                    print(
                        f"  WARN: sha256 mismatch after restoring {rel_path}; "
                        f"expected {sha256_before!r}, got {live_sha!r}.",
                        file=sys.stderr,
                    )

            n_restored += 1

        else:
            # File was created by the migration (existed_before=False)
            # Delete only if live sha256 matches sha256_staged (unedited).
            # For episode entries, a snapshot_path records the legacy flat file
            # that was deleted by the migration — restore it too.
            if not live_path.exists():
                # Already gone — nothing to do, but still restore legacy if present
                pass
            else:
                live_sha = _sha256(live_path)
                if sha256_staged and live_sha != sha256_staged:
                    # File was edited after migration — do not destroy user work
                    print(
                        f"  SKIP (drifted): {rel_path} was edited after migration; "
                        f"leaving it in place.",
                    )
                    n_skipped += 1
                    # Still restore the legacy flat file if snapshot_path is present
                    if snapshot_path_rel:
                        legacy_snapshot = before_dir / snapshot_path_rel
                        if legacy_snapshot.exists():
                            legacy_live = project_root / snapshot_path_rel
                            _atomic_copy(legacy_snapshot, legacy_live)
                            n_restored += 1
                    continue

                live_path.unlink()
                n_deleted += 1

                # Clean up now-empty parent directories under wiki/episodes/<show>/
                # Best-effort — don't fail if non-empty
                try:
                    parent = live_path.parent
                    if parent != project_root and not any(parent.iterdir()):
                        parent.rmdir()
                except OSError:
                    pass

            # Restore legacy flat file if snapshot_path is present
            # (e.g. episodes: new path existed_before=false, but old flat file was snapshotted)
            if snapshot_path_rel:
                legacy_snapshot = before_dir / snapshot_path_rel
                if legacy_snapshot.exists():
                    legacy_live = project_root / snapshot_path_rel
                    _atomic_copy(legacy_snapshot, legacy_live)
                    n_restored += 1

    # Step 7: Restore sidecars from before/sidecars/
    before_sidecars_dir = before_dir / "sidecars"
    if before_sidecars_dir.exists():
        for snapshot_path in sorted(before_sidecars_dir.rglob("*.manifest.yaml")):
            try:
                rel = snapshot_path.relative_to(before_sidecars_dir)
            except ValueError:
                continue
            live_path = project_root / rel
            if live_path.parent.exists() or live_path.exists():
                try:
                    _atomic_copy(snapshot_path, live_path)
                    n_restored += 1
                except OSError as exc:
                    print(
                        f"  WARN: failed to restore sidecar {rel}: {exc}",
                        file=sys.stderr,
                    )

    # Step 8: Rename .kb-migration/ to .kb-migration.rolled-back-<timestamp>/
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rolled_back_dir = project_root / f".kb-migration.rolled-back-{ts}"
    migration_dir.rename(rolled_back_dir)

    # Step 9: Print summary
    print(
        f"\nRollback complete: {n_restored} restored, "
        f"{n_deleted} deleted, {n_skipped} skipped (drift or missing snapshot)."
    )
    print(f"Migration artefacts preserved at: {rolled_back_dir.name}")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    """Entry point callable in-process from tests."""
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__,
        exit_on_error=False,
    )
    parser.add_argument(
        "--project-root", default=".",
        help="KB project root (contains .kb-migration/).",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip interactive confirmation prompt.",
    )

    try:
        args = parser.parse_args(argv)
    except (SystemExit, Exception) as exc:
        print(f"argument error: {exc}", file=sys.stderr)
        return 1

    project_root = Path(args.project_root).resolve()

    try:
        return rollback(project_root, yes=args.yes)
    except PendingWorkError:
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
