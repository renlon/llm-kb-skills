"""Episode-index core module.

See docs/superpowers/specs/2026-04-21-episode-index-and-dedup-design.md for the
full specification, §7 for the public API contract, and §2 for slug-validation
and depth-delta rules.

This module is split into layers that are added incrementally across tasks:
  Task 2 (this commit) — pure helpers, no I/O, no subprocess, no Haiku.
  Task 3 — I/O helpers: scan_episode_wiki, concept_catalog, concepts_covered_by_episodes.
  Task 4 — transactional core: index_episode_transactional, staging_dir, atomic_replace_index.
  Task 5 — orchestration: orchestrate_episode_index (Haiku-injected callable).
  Task 6 — dedup judge: judge_candidate_episode.
"""
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


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SlugValidationError(ValueError):
    """Raised when a slug fails any validation rule from spec §2."""


class EpisodeParseError(ValueError):
    """Raised when a wiki/episodes/*.md article cannot be parsed."""


class TransactionAbortedError(RuntimeError):
    """Raised when a transactional index operation fails before committing."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEPTH_ORDER: dict[str, int] = {"mentioned": 0, "explained": 1, "deep-dive": 2}

# Full slug regex: lowercase, hyphens/underscores/dots/slashes allowed in middle.
_SLUG_RE = re.compile(r"^wiki/[a-z0-9][a-z0-9\-_./]*[a-z0-9]$")

# Episode filename slug regex: only hyphens (no dots/underscores/slashes).
_FILENAME_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")

_SLUG_MAX_LEN = 180
_FILENAME_SLUG_MAX_LEN = 50


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class IndexedConcept:
    slug: str                       # e.g. "wiki/quantization/k-quants"
    depth_this_episode: str         # mentioned | explained | deep-dive
    depth_delta_vs_past: str        # new | deeper | same | lighter
    prior_episode_ref: int | None
    what: str
    why_it_matters: str
    key_points: list[str]
    covered_at_sec: float | None


@dataclass
class OpenThread:
    slug: str | None        # wiki slug if one exists/was created; None for unresolved threads
    note: str               # human-readable description
    existed_before: bool    # True if slug already has a wiki article; False if auto-stubbed


@dataclass
class IndexedEpisode:
    episode_id: int
    title: str
    date: str
    depth: str                          # intro | intermediate | deep-dive
    audio_file: str
    transcript_file: str | None
    concepts: list[IndexedConcept]
    open_threads: list[OpenThread]
    series_builds_on: list[str]
    series_followup_candidates: list[str]


@dataclass
class TransactionalIndexResult:
    episode_article: Path
    new_stubs_created: list[str]        # slugs
    stubs_updated: list[str]            # slugs with frontmatter-only updates
    collisions_skipped: list[str]       # slugs where non-stub articles already exist


# ---------------------------------------------------------------------------
# Slug helpers (pure, no I/O)
# ---------------------------------------------------------------------------

def validate_slug(slug: str, *, allow_episode: bool = False) -> None:
    """Raise SlugValidationError if slug fails any of the spec §2 rules.

    allow_episode=False (default): reject slugs starting with 'wiki/episodes/'
    (concept slugs must never collide with episode records).
    allow_episode=True: accept episode article slugs.
    """
    if not isinstance(slug, str) or not slug:
        raise SlugValidationError("slug must be a non-empty string")
    if len(slug) > _SLUG_MAX_LEN:
        raise SlugValidationError(f"slug exceeds {_SLUG_MAX_LEN} chars: {len(slug)}")
    # Check each path component for ".."
    if ".." in slug.split("/"):
        raise SlugValidationError(f"slug contains '..' path component: {slug!r}")
    if slug.startswith("/"):
        raise SlugValidationError(f"slug must not start with '/': {slug!r}")
    if slug.endswith(".md"):
        raise SlugValidationError(f"slug must not end with '.md': {slug!r}")
    if not allow_episode and slug.startswith("wiki/episodes/"):
        raise SlugValidationError(
            f"concept slug cannot start with 'wiki/episodes/' (use allow_episode=True for episode articles): {slug!r}"
        )
    if not _SLUG_RE.match(slug):
        raise SlugValidationError(
            f"slug {slug!r} fails pattern {_SLUG_RE.pattern!r} "
            "(must be lowercase, start+end with alphanumeric, only hyphens/underscores/dots/slashes in middle)"
        )


def slug_to_wiki_relative_path(slug: str) -> Path:
    """Convert 'wiki/quantization/k-quants' → Path('quantization/k-quants.md').

    Strips exactly one leading 'wiki/' prefix and appends '.md'.
    Used by staging and commit to avoid 'wiki/wiki/...' double-nesting.
    """
    if not slug.startswith("wiki/"):
        raise SlugValidationError(f"slug must start with 'wiki/': {slug!r}")
    rel = slug[len("wiki/"):] + ".md"
    return Path(rel)


# ---------------------------------------------------------------------------
# Depth-delta computation (pure, no I/O)
# ---------------------------------------------------------------------------

def compute_depth_deltas(
    concepts: list[dict],
    coverage_map: dict[str, list[dict]],
) -> list[dict]:
    """Given raw extracted concepts and a coverage_map from prior episodes,
    return concepts with depth_delta_vs_past and prior_episode_ref filled in.

    coverage_map format: {slug: [{ep_id, depth, key_points, date}, ...]}

    Tie-breaking rule: when multiple prior episodes share the same deepest
    depth, prior_episode_ref resolves to the one with the LOWEST ep_id
    (matches publish chronology, deterministic).
    """
    out = []
    for c in concepts:
        c = dict(c)
        priors = coverage_map.get(c["slug"], [])
        if not priors:
            c["depth_delta_vs_past"] = "new"
            c["prior_episode_ref"] = None
        else:
            # Sort key: primary = depth (descending), secondary = ep_id (ascending for lowest-wins).
            # max() with (_DEPTH_ORDER[depth], -ep_id) gives us: highest depth first,
            # among ties the one with SMALLEST ep_id (because -ep_id is largest for smallest ep_id).
            deepest = max(priors, key=lambda p: (_DEPTH_ORDER[p["depth"]], -p["ep_id"]))
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


# ---------------------------------------------------------------------------
# Stub frontmatter update (pure, no I/O)
# ---------------------------------------------------------------------------

def compute_stub_update(
    existing_frontmatter: dict,
    concept: dict,
    episode_id: int,
) -> dict | None:
    """Compute the updated frontmatter for an existing stub, or None if no change.

    Rules (spec §3):
    - Always updates `last_seen_by`.
    - Updates `best_depth_episode` + `best_depth` ONLY when new depth > stored best.
    - Appends `referenced_by` if this episode isn't already in the list.
    - NEVER modifies `created_by` (immutable provenance).

    Returns the full updated frontmatter dict on change, None on no-op.
    """
    fm = dict(existing_frontmatter)
    changed = False
    ep_tag = f"ep-{episode_id}"

    # Always update last_seen_by
    if fm.get("last_seen_by") != ep_tag:
        fm["last_seen_by"] = ep_tag
        changed = True

    # Update best_depth only when new depth is strictly greater
    existing_best_raw = fm.get("best_depth", "mentioned")
    existing_best = _DEPTH_ORDER.get(str(existing_best_raw), 0)
    new_depth = concept["depth_this_episode"]
    new_depth_val = _DEPTH_ORDER.get(new_depth, 0)
    if new_depth_val > existing_best:
        fm["best_depth"] = new_depth
        fm["best_depth_episode"] = ep_tag
        changed = True

    # Append to referenced_by if not already present
    referenced_by = list(fm.get("referenced_by") or [])
    if ep_tag not in referenced_by:
        referenced_by.append(ep_tag)
        fm["referenced_by"] = referenced_by
        changed = True

    return fm if changed else None


# ---------------------------------------------------------------------------
# Episode filename slug normalization (pure, no I/O)
# ---------------------------------------------------------------------------

def normalize_filename_slug(topic: str, aliases: list[str] | None = None) -> str:
    """Return a filename-safe slug for ep-<id>-<slug>.md.

    Algorithm (spec §2 "Episode filename slug validation"):
    1. If topic contains ASCII letters, use it as input.
       Otherwise, try the first alias that contains ASCII letters.
       Otherwise, fall through to fallback.
    2. Lowercase, replace non-[a-z0-9] runs with single hyphen, strip edges, truncate to 50.
    3. If result matches ^[a-z0-9][a-z0-9-]*[a-z0-9]$ → use it.
    4. Fallback: return the literal string "topic".
    """
    candidate = topic or ""
    if not re.search(r"[A-Za-z]", candidate):
        # No ASCII letters in topic — try aliases
        for alias in (aliases or []):
            if re.search(r"[A-Za-z]", alias):
                candidate = alias
                break
        else:
            # No usable ASCII candidate
            candidate = ""

    if not candidate:
        return "topic"

    normalized = re.sub(r"[^a-z0-9]+", "-", candidate.lower())
    normalized = normalized.strip("-")
    normalized = normalized[:_FILENAME_SLUG_MAX_LEN]
    # After truncation, strip any trailing hyphen that truncation may have left
    normalized = normalized.strip("-")

    if normalized and _FILENAME_SLUG_RE.match(normalized):
        return normalized
    return "topic"


# ---------------------------------------------------------------------------
# Concept candidate resolver (pure, no I/O)
# ---------------------------------------------------------------------------

def resolve_concept_candidate(
    candidate_name: str,
    catalog: dict[str, list[dict]],
) -> str | None:
    """Best-effort resolve a candidate concept name to an existing wiki slug.

    Resolution order (spec §4):
    1. Exact case-insensitive match on article title → unique match wins.
    2. Exact case-insensitive match on any alias → unique match wins.
    3. No tag-based resolution — tags are too broad for dedup signal.

    Returns slug on unique match, None on no-match or ambiguous-match.
    """
    name_lower = candidate_name.strip().lower()
    title_matches: list[str] = []
    alias_matches: list[str] = []

    for _category, entries in catalog.items():
        for entry in entries:
            title = entry.get("title", "")
            if title.strip().lower() == name_lower:
                title_matches.append(entry["slug"])
            for alias in entry.get("aliases") or []:
                if alias.strip().lower() == name_lower:
                    alias_matches.append(entry["slug"])

    # De-duplicate preserving insertion order
    def _dedup(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    title_matches = _dedup(title_matches)
    alias_matches = _dedup(alias_matches)

    if len(title_matches) == 1:
        return title_matches[0]
    if len(title_matches) > 1:
        return None  # ambiguous title match
    if len(alias_matches) == 1:
        return alias_matches[0]
    # Either no match or ambiguous alias match
    return None


# ---------------------------------------------------------------------------
# Rendering (pure, no I/O)
# ---------------------------------------------------------------------------

def render_stub(
    slug: str,
    concept: dict,
    episode_id: int,
    episode_slug: str,
    date: str,
) -> str:
    """Deterministically render a stub article (frontmatter + body).

    Pure function — no filesystem writes. The caller is responsible for writing
    the returned string to the correct path.
    """
    ep_tag = f"ep-{episode_id}"
    # Derive a human-readable title from the slug's last component
    title = slug.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()

    fm: dict[str, Any] = {
        "title": title,
        "tags": ["stub"],
        "aliases": [],
        "status": "stub",
        "created_by": ep_tag,           # immutable provenance
        "last_seen_by": ep_tag,
        "best_depth_episode": ep_tag,
        "best_depth": concept.get("depth_this_episode", "mentioned"),
        "referenced_by": [ep_tag],
        "created": date,
    }

    body = (
        f"# {title}\n\n"
        f"> **Stub.** Auto-created by `kb-publish` while indexing "
        f"[[wiki/episodes/{episode_slug}]]. "
        f"It will be fleshed out the next time this concept appears in compile/lint, "
        f"or when you write about it manually.\n\n"
        f"## What the introducing episode said\n\n"
        f"{concept.get('what', '')}\n\n"
        f"## Why it matters\n\n"
        f"{concept.get('why_it_matters', '')}\n\n"
        f"## Referenced by\n\n"
        f"- Introduced in: [[wiki/episodes/{episode_slug}]]\n"
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
    """Deterministic markdown rendering of an episode index record.

    The frontmatter carries the machine-readable `index:` block (parsed by
    scan_episode_wiki). The body below the frontmatter is rendered markdown
    for human reading in Obsidian.
    """
    index_block: dict[str, Any] = {
        "schema_version": 1,
        "summary": summary,
        "concepts": concepts,
        "open_threads": open_threads,
        "series_links": {
            "builds_on": series_builds_on,
            "followup_candidates": series_followup_candidates,
        },
    }
    fm: dict[str, Any] = {
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

    body = _render_body(
        title=title,
        date=date,
        depth=depth,
        audio_file=audio_file,
        transcript_file=transcript_file,
        summary=summary,
        concepts=concepts,
        open_threads=open_threads,
        builds_on=series_builds_on,
        followups=series_followup_candidates,
    )
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body


def _render_body(
    title: str,
    date: str,
    depth: str,
    audio_file: str,
    transcript_file: str,
    summary: str,
    concepts: list[dict],
    open_threads: list[dict],
    builds_on: list[str],
    followups: list[str],
) -> str:
    """Render the human-readable markdown body below the frontmatter."""
    parts: list[str] = []

    parts.append(f"# {title}\n\n")
    parts.append(
        f"**Date:** {date}\n"
        f"**Depth:** {depth}\n"
        f"**Audio:** [[{audio_file}]]\n"
        f"**Transcript:** [[{transcript_file}]]\n\n"
    )
    parts.append(f"## Summary\n\n{summary}\n\n")

    parts.append("## Concepts Covered\n\n")
    for level, label in [("deep-dive", "Deep-dive"), ("explained", "Explained"), ("mentioned", "Mentioned")]:
        group = [c for c in concepts if c.get("depth_this_episode") == level]
        if not group:
            continue
        parts.append(f"### {label}\n\n")
        for c in group:
            parts.append(f"- [[{c['slug']}]]\n")
            if c.get("what"):
                parts.append(f"  - What: {c['what']}\n")
            if c.get("why_it_matters"):
                parts.append(f"  - Why it matters: {c['why_it_matters']}\n")
            kp = c.get("key_points") or []
            if kp:
                parts.append("  - Key points:\n")
                for k in kp:
                    parts.append(f"    - {k}\n")
            if c.get("covered_at_sec") is not None:
                parts.append(f"  - Covered at: {c['covered_at_sec']:.0f}s\n")
            parts.append("\n")

    if open_threads:
        parts.append("## Open Threads\n\n")
        for t in open_threads:
            slug = t.get("slug")
            note = t.get("note") or ""
            if slug:
                parts.append(f"- [[{slug}]] — {note}\n")
            else:
                parts.append(f"- {note}\n")
        parts.append("\n")

    if builds_on or followups:
        parts.append("## Series Links\n\n")
        for b in builds_on:
            parts.append(f"- Builds on: [[{b}]]\n")
        for f in followups:
            parts.append(f"- Follow-up candidate: {f}\n")
        parts.append("\n")

    return "".join(parts)
