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

from typing import Literal

import yaml


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
