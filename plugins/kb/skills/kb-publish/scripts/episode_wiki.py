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
  Tasks 6-9 (multi-show) — show-scoped scan, EpRef dict form throughout, new helpers.

NOTE: this module carries temporary single-show compatibility shims
(`_scan_episode_wiki_legacy`, `_compute_depth_deltas_legacy`,
`_compute_stub_update_legacy`) to avoid breaking pre-migration callers
during the multi-show rollout. These will be removed in Task 23 of the
multi-show plan, after every caller has been updated to pass a `Show`.
See docs/superpowers/plans/2026-04-23-multi-show-podcast-support-implementation.md
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

from shows import (
    EpRef, Show, UnknownShowError, MigrationRequiredError,
    ShowConfigError, parse_ep_ref_field,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SlugValidationError(ValueError):
    """Raised when a slug fails any validation rule from spec §2."""


class EpisodeParseError(ValueError):
    """Raised when a wiki/episodes/*.md article cannot be parsed."""


class TransactionAbortedError(RuntimeError):
    """Raised when a transactional index operation fails before committing."""


class MixedShowCoverageError(ShowConfigError):
    """Raised when compute_depth_deltas receives indexed entries for multiple shows."""


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
    prior_episode_ref: dict | None  # {show, ep} dict or None
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
    series_builds_on: list[dict]        # list of {show, ep} dicts
    series_followup_candidates: list[str]
    show_id: str = ""                   # populated by scan_episode_wiki from the passed Show.id


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
    current_episode_show_id: str,
    current_concepts: list[dict],
    indexed: list[IndexedEpisode],
) -> list[dict]:
    """Given raw extracted concepts and a list of prior IndexedEpisodes for the
    same show, return concepts with depth_delta_vs_past and prior_episode_ref filled in.

    prior_episode_ref is emitted as a {show, ep} dict.

    Raises MixedShowCoverageError if any entry in `indexed` has a different show_id
    than current_episode_show_id. Hard fail — do NOT silently filter.

    Tie-breaking rule: when multiple prior episodes share the same deepest
    depth, prior_episode_ref resolves to the one with the LOWEST episode_id
    (matches publish chronology, deterministic).
    """
    # Validate that all indexed episodes belong to the same show.
    for ep in indexed:
        if ep.show_id != current_episode_show_id:
            raise MixedShowCoverageError(
                f"coverage_map contains show {ep.show_id!r}, expected {current_episode_show_id!r}"
            )

    # Build coverage map from indexed episodes: {slug: [{ep_id, depth, key_points, date}, ...]}
    coverage_map: dict[str, list[dict]] = {}
    for ep in indexed:
        for c in ep.concepts:
            coverage_map.setdefault(c.slug, []).append({
                "ep_id": ep.episode_id,
                "depth": c.depth_this_episode,
                "key_points": list(c.key_points),
                "date": ep.date,
            })

    out = []
    for c in current_concepts:
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
            # Emit as {show, ep} dict
            c["prior_episode_ref"] = {"show": current_episode_show_id, "ep": deepest["ep_id"]}
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Stub frontmatter update (pure, no I/O)
# ---------------------------------------------------------------------------

def compute_stub_update(
    existing_frontmatter: dict,
    concept: dict,
    episode_id: int,
    show_id: str,
) -> dict | None:
    """Compute the updated frontmatter for an existing stub, or None if no change.

    Rules (spec §3):
    - Always updates `last_seen_by`.
    - Updates `best_depth_episode` + `best_depth` ONLY when new depth > stored best.
    - Appends `referenced_by` if this episode isn't already in the list.
    - NEVER modifies `created_by` (immutable provenance).

    All episode refs emitted as {show, ep} dicts.

    Returns the full updated frontmatter dict on change, None on no-op.
    """
    fm = dict(existing_frontmatter)
    changed = False
    ep_ref_dict = {"show": show_id, "ep": episode_id}

    def _ref_matches(existing_val, ref_dict: dict) -> bool:
        """Check whether existing_val (already stored) matches the new ref dict."""
        if isinstance(existing_val, dict):
            return existing_val.get("show") == ref_dict["show"] and existing_val.get("ep") == ref_dict["ep"]
        return False

    # Always update last_seen_by
    if not _ref_matches(fm.get("last_seen_by"), ep_ref_dict):
        fm["last_seen_by"] = ep_ref_dict
        changed = True

    # Update best_depth only when new depth is strictly greater
    existing_best_raw = fm.get("best_depth", "mentioned")
    existing_best = _DEPTH_ORDER.get(str(existing_best_raw), 0)
    new_depth = concept["depth_this_episode"]
    new_depth_val = _DEPTH_ORDER.get(new_depth, 0)
    if new_depth_val > existing_best:
        fm["best_depth"] = new_depth
        fm["best_depth_episode"] = ep_ref_dict
        changed = True

    # Append to referenced_by if not already present
    referenced_by = list(fm.get("referenced_by") or [])
    already_present = any(
        (isinstance(r, dict) and r.get("show") == ep_ref_dict["show"] and r.get("ep") == ep_ref_dict["ep"])
        for r in referenced_by
    )
    if not already_present:
        referenced_by.append(ep_ref_dict)
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
# New helpers: resolve_episode_wikilink, validate_body_wikilinks (Task 6)
# ---------------------------------------------------------------------------

def resolve_episode_wikilink(
    ref: EpRef,
    shows_by_id: dict[str, Show],
    wiki_path: Path,
) -> str:
    """Resolve an EpRef to a wikilink stem by looking up the episode file on disk.

    Looks up shows_by_id[ref.show] (raises UnknownShowError if not found),
    then globs wiki_path / show.wiki_episodes_dir / f"ep-{ref.ep}-*.md" to
    recover the slug from the filename stem (strips ep-<N>- prefix).

    Returns ref.wikilink_stem(slug).

    Raises:
      UnknownShowError: if ref.show not in shows_by_id
      FileNotFoundError: if no matching ep-<N>-*.md file is found
      ValueError: if multiple matching files are found (ambiguous)
    """
    if ref.show not in shows_by_id:
        raise UnknownShowError(
            f"show {ref.show!r} not in shows_by_id {sorted(shows_by_id)}"
        )
    show = shows_by_id[ref.show]
    ep_dir = wiki_path / show.wiki_episodes_dir
    matches = list(ep_dir.glob(f"ep-{ref.ep}-*.md"))
    if not matches:
        raise FileNotFoundError(
            f"no episode file found for ep-{ref.ep} under {ep_dir}"
        )
    if len(matches) > 1:
        names = [m.name for m in matches]
        raise ValueError(
            f"multiple episode files found for ep-{ref.ep} under {ep_dir}: {names}"
        )
    # Extract slug: strip "ep-<N>-" prefix and ".md" suffix
    stem = matches[0].stem  # e.g. "ep-3-quantization"
    prefix = f"ep-{ref.ep}-"
    if stem.startswith(prefix):
        slug = stem[len(prefix):]
    else:
        slug = stem
    return ref.wikilink_stem(slug)


# Regex to match episode wikilinks (with or without display text)
# Matches: [[wiki/episodes/ep-N-slug]] (legacy flat)
#      and [[wiki/episodes/<show>/ep-N-slug]] (new show-scoped)
# Capture groups: (path_without_display_text)
_EPISODE_WIKILINK_RE = re.compile(
    r"\[\[wiki/episodes/"
    r"((?:ep-\d+|[a-z][a-z0-9-]*/ep-\d+)[^\]|]*)"
    r"(?:\|[^\]]*)?"
    r"\]\]"
)

# Legacy flat pattern: wiki/episodes/ep-N-...  (no show sub-path)
_LEGACY_EP_RE = re.compile(r"^ep-\d+")
# Show-scoped pattern: <show>/ep-N-...
_SHOW_SCOPED_EP_RE = re.compile(r"^([a-z][a-z0-9-]*)/ep-\d+")


def validate_body_wikilinks(text: str, known_shows: set[str]) -> list[str]:
    """Scan `text` for episode wikilinks and return a list of error strings.

    Error conditions:
    - Legacy flat path [[wiki/episodes/ep-N-<slug>...]] → "legacy wikilink: <match>"
    - Show-scoped path [[wiki/episodes/<show>/ep-N-...]] where <show> not in
      known_shows → "unknown show in wikilink: <show>"

    Returns an empty list on success (no errors).
    """
    errors: list[str] = []
    for m in _EPISODE_WIKILINK_RE.finditer(text):
        path = m.group(1)  # everything after "wiki/episodes/" up to | or ]]
        full_match = m.group(0)
        if _LEGACY_EP_RE.match(path):
            errors.append(f"legacy wikilink: {full_match}")
        else:
            sm = _SHOW_SCOPED_EP_RE.match(path)
            if sm:
                show_token = sm.group(1)
                if show_token not in known_shows:
                    errors.append(f"unknown show in wikilink: {show_token}")
    return errors


# ---------------------------------------------------------------------------
# Rendering (pure, no I/O)
# ---------------------------------------------------------------------------

def render_stub(
    slug: str,
    concept: dict,
    episode_id: int,
    episode_slug: str,
    date: str,
    show_id: str = "",
) -> str:
    """Deterministically render a stub article (frontmatter + body).

    Pure function — no filesystem writes. The caller is responsible for writing
    the returned string to the correct path.

    All episode refs emitted as {show, ep} dicts when show_id is provided.
    """
    ep_ref: Any
    if show_id:
        ep_ref = {"show": show_id, "ep": episode_id}
    else:
        ep_ref = f"ep-{episode_id}"

    # Derive a human-readable title from the slug's last component
    title = slug.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()

    fm: dict[str, Any] = {
        "title": title,
        "tags": ["stub"],
        "aliases": [],
        "status": "stub",
        "created_by": ep_ref,           # immutable provenance
        "last_seen_by": ep_ref,
        "best_depth_episode": ep_ref,
        "best_depth": concept.get("depth_this_episode", "mentioned"),
        "referenced_by": [ep_ref],
        "created": date,
    }

    # Build episode link — show-scoped if show_id available
    if show_id:
        ep_link = f"wiki/episodes/{show_id}/{episode_slug}"
    else:
        ep_link = f"wiki/episodes/{episode_slug}"

    body = (
        f"# {title}\n\n"
        f"> **Stub.** Auto-created by `kb-publish` while indexing "
        f"[[{ep_link}]]. "
        f"It will be fleshed out the next time this concept appears in compile/lint, "
        f"or when you write about it manually.\n\n"
        f"## What the introducing episode said\n\n"
        f"{concept.get('what', '')}\n\n"
        f"## Why it matters\n\n"
        f"{concept.get('why_it_matters', '')}\n\n"
        f"## Referenced by\n\n"
        f"- Introduced in: [[{ep_link}]]\n"
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
    series_builds_on: list[Any],
    series_followup_candidates: list[str],
    source_lessons: list[str],
    tags: list[str],
    aliases: list[str] | None = None,
    show_id: str = "",
) -> str:
    """Deterministic markdown rendering of an episode index record.

    The frontmatter carries the machine-readable `index:` block (parsed by
    scan_episode_wiki). The body below the frontmatter is rendered markdown
    for human reading in Obsidian.

    series_builds_on: list of {show, ep} dicts (or legacy strings for compat).
    All episode-level refs emitted as {show, ep} dicts when show_id is provided.
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
        show_id=show_id,
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
    builds_on: list[Any],
    followups: list[str],
    show_id: str = "",
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
            if isinstance(b, dict):
                # New dict form — build wikilink from show+ep
                show = b.get("show", show_id)
                ep = b.get("ep", "")
                parts.append(f"- Builds on: [[wiki/episodes/{show}/ep-{ep}]]\n")
            else:
                parts.append(f"- Builds on: [[{b}]]\n")
        for f in followups:
            parts.append(f"- Follow-up candidate: {f}\n")
        parts.append("\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# I/O helpers (Task 3) — filesystem reads only; no network, no Haiku
# ---------------------------------------------------------------------------

import logging

log = logging.getLogger(__name__)


def scan_episode_wiki(
    wiki_path: Path,
    show: Show | None = None,
    strict: bool = False,
    # Legacy keyword-only alias so older call sites that passed wiki_dir still
    # work during transition. Removed once all callers updated.
    **kwargs: Any,
) -> list[IndexedEpisode]:
    """Parse all episode articles for the given show into structured records.

    New signature: scan_episode_wiki(wiki_path, show, *, strict=False)
      - walks wiki_path / show.wiki_episodes_dir, globs ep-*.md
      - populates IndexedEpisode.show_id from show.id

    Legacy compatibility: if show is None, falls back to wiki_path/episodes/*.md
    (useful during smoke-parse inside staging where no Show object is available).

    strict=False (default): malformed frontmatter or missing `index` block logs
    a warning and skips the file. Used by dedup at podcast-generation time.

    strict=True: any parse failure raises EpisodeParseError. Used by reindex
    staging smoke-parse.
    """
    # Handle legacy call: scan_episode_wiki(wiki_dir, strict=bool)
    # Detect if caller passed strict as second positional arg (old API).
    if isinstance(show, bool):
        # Caller used old positional API: scan_episode_wiki(wiki_dir, strict)
        strict = show
        show = None

    if show is not None:
        ep_dir = wiki_path / show.wiki_episodes_dir
        show_id = show.id
    else:
        ep_dir = wiki_path / "episodes"
        show_id = ""

    if not ep_dir.is_dir():
        return []
    out: list[IndexedEpisode] = []
    # Only match ep-*.md files (not subdirectories)
    for fp in sorted(ep_dir.glob("ep-*.md")):
        try:
            ep = _parse_episode_article(fp, known_shows={show_id} if show_id else None)
            ep.show_id = show_id
            out.append(ep)
        except (MigrationRequiredError, UnknownShowError):
            # These are always propagated directly — they signal a data problem
            # that requires action, not just a malformed file to skip.
            raise
        except Exception as e:
            if strict:
                raise EpisodeParseError(f"{fp.name}: {e}") from e
            log.warning("Skipping malformed episode %s: %s", fp.name, e)
    out.sort(key=lambda e: e.episode_id)
    return out


def _parse_episode_article(
    path: Path,
    known_shows: set[str] | None = None,
) -> IndexedEpisode:
    """Parse a single episode article .md file.

    known_shows: set of valid show IDs for parsing EpRef fields.
    If None, legacy null/omitted refs are tolerated (for backward compat
    during initial migration where prior_episode_ref may be null).
    If provided, dict-form EpRef fields are validated; legacy str/int
    refs raise MigrationRequiredError.
    """
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
        prior_ref_raw = c.get("prior_episode_ref")
        if prior_ref_raw is not None and known_shows is not None:
            # Parse and validate; raises MigrationRequiredError on legacy str/int
            parsed_ref = parse_ep_ref_field(prior_ref_raw, known_shows=known_shows)
            prior_ref = parsed_ref.to_dict()
        else:
            prior_ref = prior_ref_raw  # None or unparsed (legacy compat)
        concepts.append(IndexedConcept(
            slug=c.get("slug", ""),
            depth_this_episode=c.get("depth_this_episode", "mentioned"),
            depth_delta_vs_past=c.get("depth_delta_vs_past", "new"),
            prior_episode_ref=prior_ref,
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
    builds_on_raw = list(sl.get("builds_on") or [])
    builds_on: list[Any] = []
    for b in builds_on_raw:
        if b is None:
            continue
        if isinstance(b, dict) and known_shows is not None:
            # Validate dict-form ref
            parsed_b = parse_ep_ref_field(b, known_shows=known_shows)
            builds_on.append(parsed_b.to_dict())
        else:
            builds_on.append(b)

    return IndexedEpisode(
        episode_id=ep_id,
        title=fm.get("title", ""),
        date=str(fm.get("date", "")),
        depth=fm.get("depth", ""),
        audio_file=fm.get("audio_file", ""),
        transcript_file=fm.get("transcript_file"),
        concepts=concepts,
        open_threads=threads,
        series_builds_on=builds_on,
        series_followup_candidates=list(sl.get("followup_candidates") or []),
        show_id="",  # caller sets this after return
    )


def concept_catalog(
    wiki_dir: Path,
    include_stubs: bool = True,
) -> dict[str, list[dict]]:
    """{top-level-category: [{slug, title, tags, aliases, is_stub}, ...]} — for Haiku prompts.

    Episode articles (wiki/episodes/**) are always excluded.
    Stubs are included by default (flagged via is_stub=True), so Haiku can
    canonicalize to them and avoid duplicate-stub proliferation.
    """
    out: dict[str, list[dict]] = {}
    for fp in wiki_dir.rglob("*.md"):
        rel = fp.relative_to(wiki_dir)
        # Exclude episodes always
        if rel.parts and rel.parts[0] == "episodes":
            continue
        # Top-level flat file (like README.md) — skip
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
    """{slug: [{ep_id, depth, key_points, date}, ...]} — what each concept has been taught."""
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


# ---------------------------------------------------------------------------
# Task 4: Transactional core — staging + atomic commit
# ---------------------------------------------------------------------------

import shutil


def staging_dir(wiki_dir: Path) -> Path:
    """Create and return a unique per-session staging directory with an episodes/ subdir.

    Location: <wiki_dir.parent>/.kb-publish-staging/<uuid>/
    The caller owns cleanup; index_episode_transactional always removes it in finally.
    """
    root = wiki_dir.parent / ".kb-publish-staging" / uuid.uuid4().hex
    (root / "episodes").mkdir(parents=True, exist_ok=False)
    return root


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown string into (frontmatter_dict, body_string).

    body_string starts immediately after the closing '---\\n' delimiter.
    Returns ({}, text) if no valid frontmatter is found.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm = yaml.safe_load(text[4:end]) or {}
    return fm, text[end + len("\n---\n"):]


def _iter_staged_non_episode(staging: Path):
    """Yield relative Path objects for all staged .md files outside the episodes/ subdir."""
    for fp in staging.rglob("*.md"):
        rel = fp.relative_to(staging)
        if rel.parts[0] == "episodes":
            continue
        yield rel


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
    show: Show | None = None,
) -> TransactionalIndexResult:
    """Stage, smoke-parse, then atomically commit an episode article and concept stubs.

    The caller supplies a post-validated extraction dict (Haiku not called here).
    Raises TransactionAbortedError on any pre-commit failure; no wiki files are
    touched when an exception is raised.

    Commit order: stubs first (wikilinks must resolve before episode article lands),
    then other-episode stub frontmatter updates, then episode article last.

    show: optional Show object; when provided, episode dir and EpRef dicts use show.
    """
    show_id = show.id if show else ""

    # 1. Determine episode filename slug and validate the resulting episode slug.
    filename_slug = normalize_filename_slug(episode_topic, aliases)

    # Build the episode article path relative to wiki_dir
    if show:
        ep_dir_rel = show.wiki_episodes_dir  # e.g. "episodes/quanzhan-ai"
        validate_slug(f"wiki/{ep_dir_rel}/ep-{episode_id}-{filename_slug}", allow_episode=True)
    else:
        ep_dir_rel = "episodes"
        validate_slug(f"wiki/episodes/ep-{episode_id}-{filename_slug}", allow_episode=True)

    ep_article_basename = f"ep-{episode_id}-{filename_slug}.md"

    # 2. Create isolated staging area.
    staging = staging_dir(wiki_dir)
    # Ensure the episodes subdir matches the show-scoped path
    (staging / ep_dir_rel).mkdir(parents=True, exist_ok=True)
    new_stubs: list[str] = []
    stubs_updated: list[str] = []
    collisions_skipped: list[str] = []
    # Deferred frontmatter-only updates for stubs owned by a different episode.
    stub_updates_to_apply: list[tuple[Path, dict]] = []

    try:
        # 3. Validate ALL concept slugs before any I/O.
        for c in extraction["concepts"]:
            validate_slug(c["slug"], allow_episode=False)

        # 4. Stage stubs and compute frontmatter-only updates.
        for c in extraction["concepts"]:
            rel = slug_to_wiki_relative_path(c["slug"])
            dest = wiki_dir / rel

            if dest.exists():
                fm, _body = _split_frontmatter(dest.read_text(encoding="utf-8"))
                if fm.get("status") == "stub":
                    # Determine if this stub was created by the current episode.
                    # Support both old string form (ep-N) and new dict form ({show, ep}).
                    created_by = fm.get("created_by")
                    is_same_episode = False
                    if isinstance(created_by, dict):
                        is_same_episode = (
                            created_by.get("show") == show_id and
                            created_by.get("ep") == episode_id
                        )
                    elif isinstance(created_by, str):
                        is_same_episode = (created_by == f"ep-{episode_id}")

                    if is_same_episode:
                        # Same-episode reindex: fully replace the stub in staging.
                        staged = staging / rel
                        staged.parent.mkdir(parents=True, exist_ok=True)
                        staged.write_text(
                            render_stub(
                                c["slug"], c, episode_id,
                                ep_article_basename.replace(".md", ""),
                                episode_date,
                                show_id=show_id,
                            ),
                            encoding="utf-8",
                        )
                        stubs_updated.append(c["slug"])
                    else:
                        # Different-episode stub: frontmatter-only update at commit time.
                        if show_id:
                            updated_fm = compute_stub_update(fm, c, episode_id, show_id)
                        else:
                            # TODO(task-23): remove this legacy branch once every caller passes a Show.
                            updated_fm = _compute_stub_update_legacy(fm, c, episode_id)
                        if updated_fm is not None:
                            stub_updates_to_apply.append((dest, updated_fm))
                            stubs_updated.append(c["slug"])
                else:
                    # Non-stub canonical article: leave untouched.
                    collisions_skipped.append(c["slug"])
            else:
                # Brand-new stub: stage the full article.
                staged = staging / rel
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_text(
                    render_stub(
                        c["slug"], c, episode_id,
                        ep_article_basename.replace(".md", ""),
                        episode_date,
                        show_id=show_id,
                    ),
                    encoding="utf-8",
                )
                new_stubs.append(c["slug"])

        # 5. Render and stage the episode article.
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
            show_id=show_id,
        )
        (staging / ep_dir_rel / ep_article_basename).write_text(ep_md, encoding="utf-8")

        # 6. Smoke-parse staging in strict mode — aborts before any wiki writes on failure.
        # Pass show if available; otherwise use legacy flat scan.
        if show:
            scan_episode_wiki(staging, show, strict=True)
        else:
            # TODO(task-23): remove this legacy branch once every caller passes a Show.
            # Legacy: scan the flat episodes dir
            _scan_episode_wiki_legacy(staging, strict=True)

        # 7. Commit — stubs first (new/replaced), then other-ep frontmatter updates, episode last.
        for rel_md in _iter_staged_non_episode(staging):
            src = staging / rel_md
            dst = wiki_dir / rel_md
            if dst.exists():
                existing_fm, _ = _split_frontmatter(dst.read_text(encoding="utf-8"))
                if existing_fm.get("status") != "stub":
                    # Concurrent race: article was promoted while we staged. Skip.
                    continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)

        for dest, updated_fm in stub_updates_to_apply:
            text = dest.read_text(encoding="utf-8")
            _, body = _split_frontmatter(text)
            new_text = (
                "---\n"
                + yaml.safe_dump(updated_fm, allow_unicode=True, sort_keys=False)
                + "---\n"
                + body
            )
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_text(new_text, encoding="utf-8")
            os.replace(tmp, dest)

        ep_dst = wiki_dir / ep_dir_rel / ep_article_basename
        ep_dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging / ep_dir_rel / ep_article_basename, ep_dst)

    except (SlugValidationError, EpisodeParseError, KeyError) as e:
        raise TransactionAbortedError(str(e)) from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return TransactionalIndexResult(
        episode_article=ep_dst,
        new_stubs_created=new_stubs,
        stubs_updated=stubs_updated,
        collisions_skipped=collisions_skipped,
    )


def _compute_stub_update_legacy(
    existing_frontmatter: dict,
    concept: dict,
    episode_id: int,
) -> dict | None:
    """DEPRECATED — legacy single-show fallback.

    Removed in Task 23 of the multi-show migration plan, after Tasks 10 + 19 +
    20 wire a `Show` object through every call site. Do NOT call this from new
    code. Existing callers MUST migrate to the new (Show-aware) API.

    Legacy (no show_id) compute_stub_update for backward compat.
    Emits ep-N strings instead of {show, ep} dicts.
    Used when no Show object is available.
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


def _scan_episode_wiki_legacy(wiki_dir: Path, strict: bool = False) -> list[IndexedEpisode]:
    """DEPRECATED — legacy single-show fallback.

    Removed in Task 23 of the multi-show migration plan, after Tasks 10 + 19 +
    20 wire a `Show` object through every call site. Do NOT call this from new
    code. Existing callers MUST migrate to the new (Show-aware) API.

    Legacy flat scan for use during staging smoke-parse when no Show is available.
    """
    ep_dir = wiki_dir / "episodes"
    if not ep_dir.is_dir():
        return []
    out: list[IndexedEpisode] = []
    for fp in sorted(ep_dir.glob("ep-*.md")):
        try:
            ep = _parse_episode_article(fp, known_shows=None)
            out.append(ep)
        except Exception as e:
            if strict:
                raise EpisodeParseError(f"{fp.name}: {e}") from e
            log.warning("Skipping malformed episode %s: %s", fp.name, e)
    out.sort(key=lambda e: e.episode_id)
    return out


# ---------------------------------------------------------------------------
# Task 5: Orchestration — orchestrate_episode_index (Haiku-injected callable)
# ---------------------------------------------------------------------------


def _validate_extraction_shape(data: dict) -> None:
    """Raise TransactionAbortedError if the extraction dict is missing required fields.

    Validates top-level keys and per-concept required fields including
    depth_this_episode enum values.
    """
    if not isinstance(data, dict):
        raise TransactionAbortedError("extraction not a dict")
    for k in ("summary", "concepts", "open_threads"):
        if k not in data:
            raise TransactionAbortedError(f"extraction missing top-level key {k!r}")
    for c in data.get("concepts", []) or []:
        for k in ("slug", "depth_this_episode", "what", "why_it_matters", "key_points"):
            if k not in c:
                raise TransactionAbortedError(f"concept missing key {k!r}")
        if c["depth_this_episode"] not in ("mentioned", "explained", "deep-dive"):
            raise TransactionAbortedError(f"invalid depth_this_episode: {c['depth_this_episode']!r}")


def _normalize_haiku_slug(slug: str) -> str:
    """Best-effort normalize a Haiku-proposed slug to our canonical form.

    Haiku sometimes emits slugs with uppercase letters, spaces, or mixed
    punctuation ("wiki/gpu/NVIDIA Compute Capability"). Normalize to
    "wiki/gpu/nvidia-compute-capability" so validate_slug() accepts them.

    Preserves the 'wiki/' prefix and path-component structure (slashes between
    components). Within each component: lowercase, replace any non-alphanumeric
    run with a single hyphen, trim edges.
    """
    if not isinstance(slug, str) or not slug:
        return slug  # let validate_slug() raise the clearer error
    if slug.startswith("wiki/"):
        prefix = "wiki/"
        rest = slug[len(prefix):]
    else:
        prefix = ""
        rest = slug
    components = rest.split("/")
    normalized = []
    for comp in components:
        n = re.sub(r"[^a-z0-9]+", "-", comp.lower()).strip("-")
        if n:
            normalized.append(n)
    return prefix + "/".join(normalized) if normalized else slug


def _normalize_extraction_slugs(data: dict) -> dict:
    """Normalize every slug in the extraction dict before strict validation."""
    data = dict(data)
    new_concepts = []
    for c in data.get("concepts", []) or []:
        c = dict(c)
        if "slug" in c:
            c["slug"] = _normalize_haiku_slug(c["slug"])
        new_concepts.append(c)
    data["concepts"] = new_concepts
    new_threads = []
    for t in data.get("open_threads", []) or []:
        t = dict(t)
        if t.get("slug"):
            t["slug"] = _normalize_haiku_slug(t["slug"])
        new_threads.append(t)
    data["open_threads"] = new_threads
    # Also normalize series_links
    sl = data.get("series_links") or {}
    if isinstance(sl, dict):
        sl = dict(sl)
        sl["builds_on"] = [_normalize_haiku_slug(s) if isinstance(s, str) else s
                           for s in (sl.get("builds_on") or [])]
        # followup_candidates is free-form prose, not slugs — leave alone
        data["series_links"] = sl
    return data


def _recompute_existed_before(concepts: list[dict], wiki_dir: Path) -> list[dict]:
    """Override Haiku's existed_before claim with the actual filesystem state.

    Haiku's claim is advisory; we always re-check the disk.
    """
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
    show: Show | None = None,
) -> TransactionalIndexResult:
    """Full pipeline: read transcript, build catalog+context, call Haiku,
    validate, recompute existed_before, compute depth_deltas excluding current
    episode, invoke index_episode_transactional, return result.

    Used by kb-publish step 8c (at publish time) and /kb-publish backfill-index.
    """
    transcript = transcript_path.read_text(encoding="utf-8")
    catalog = concept_catalog(wiki_dir, include_stubs=True)

    # Scan episodes for the given show (or legacy flat if no show)
    if show:
        all_eps = scan_episode_wiki(wiki_dir, show, strict=False)
    else:
        # TODO(task-23): remove this legacy branch once every caller passes a Show.
        all_eps = _scan_episode_wiki_legacy(wiki_dir, strict=False)

    # Recent-episodes context: most-recent 3 EXCLUDING the current episode.
    others = [e for e in all_eps if e.episode_id != episode_id]
    recent = sorted(others, key=lambda e: e.episode_id, reverse=True)[:3]
    template = prompt_template_path.read_text(encoding="utf-8")

    prompt = (template
              .replace("{transcript}", transcript)
              .replace("{episode_metadata}",
                       yaml.safe_dump({
                           "id": episode_id,
                           "title": f"EP{episode_id} | {episode_topic}",
                           "date": episode_date,
                           "depth": episode_depth,
                           "topic": episode_topic,
                           "source_lessons": source_lessons,
                       }, allow_unicode=True))
              .replace("{concept_catalog}",
                       yaml.safe_dump(catalog, allow_unicode=True))
              .replace("{recent_episodes}",
                       yaml.safe_dump([{
                           "ep_id": e.episode_id,
                           "title": e.title,
                           "depth": e.depth,
                           "concepts": [c.slug for c in e.concepts],
                           "open_threads": [t.slug or t.note for t in e.open_threads],
                       } for e in recent], allow_unicode=True)))

    data = None
    last_err: Exception | None = None
    for attempt in range(2):
        raw = haiku_call(prompt)
        candidate = raw.strip()
        # Strip common code fences
        if candidate.startswith("```"):
            first_nl = candidate.find("\n")
            candidate = candidate[first_nl + 1:] if first_nl >= 0 else candidate
            if candidate.rstrip().endswith("```"):
                candidate = candidate.rstrip()[:-3]
        candidate = candidate.strip()
        try:
            parsed = json.loads(candidate)
            # Normalize slugs BEFORE shape validation so Haiku's casing / spacing
            # quirks (e.g. "wiki/gpu/NVIDIA Compute Capability") don't abort
            # indexing before we get a chance to canonicalize.
            parsed = _normalize_extraction_slugs(parsed)
            _validate_extraction_shape(parsed)
            data = parsed
            break
        except (json.JSONDecodeError, TransactionAbortedError) as e:
            last_err = e
            continue
    if data is None:
        raise TransactionAbortedError(f"Haiku returned invalid JSON after retry: {last_err}")

    # Recompute existed_before post slug validation (before full transactional call)
    # NOTE: slug validation happens inside index_episode_transactional; if that
    # raises, we abort. Here we just normalize existed_before from disk.
    data["concepts"] = _recompute_existed_before(data["concepts"], wiki_dir)

    # Coverage map excluding current episode — use new compute_depth_deltas signature
    show_id = show.id if show else ""
    if show_id:
        data["concepts"] = compute_depth_deltas(show_id, data["concepts"], others)
    else:
        # TODO(task-23): remove this legacy branch once every caller passes a Show.
        # Legacy path: no show, use old-style coverage map
        coverage = concepts_covered_by_episodes(others)
        data["concepts"] = _compute_depth_deltas_legacy(data["concepts"], coverage)

    return index_episode_transactional(
        wiki_dir=wiki_dir, episode_id=episode_id, episode_topic=episode_topic,
        episode_date=episode_date, episode_depth=episode_depth,
        audio_file=audio_file, transcript_file=transcript_file,
        tags=tags, aliases=aliases, source_lessons=source_lessons,
        extraction=data,
        show=show,
    )


def _compute_depth_deltas_legacy(
    concepts: list[dict],
    coverage_map: dict[str, list[dict]],
) -> list[dict]:
    """DEPRECATED — legacy single-show fallback.

    Removed in Task 23 of the multi-show migration plan, after Tasks 10 + 19 +
    20 wire a `Show` object through every call site. Do NOT call this from new
    code. Existing callers MUST migrate to the new (Show-aware) API.

    Legacy compute_depth_deltas that emits prior_episode_ref as bare int.
    Used when no Show object is available (pre-migration or legacy callers).
    """
    out = []
    for c in concepts:
        c = dict(c)
        priors = coverage_map.get(c["slug"], [])
        if not priors:
            c["depth_delta_vs_past"] = "new"
            c["prior_episode_ref"] = None
        else:
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
# Task 6: Dedup judge — judge_candidate_episode (Haiku-injected callable)
# ---------------------------------------------------------------------------


@dataclass
class DedupJudgement:
    per_concept: list[dict]
    episode_verdict: str
    framing_recommendation: str


def judge_candidate_episode(
    wiki_dir: Path,
    candidate_concepts: list[str],
    open_threads_allow: list[str] | None = None,
    haiku_call: Callable[[str], str] | None = None,
    prompt_template_path: Path | None = None,
    show: Show | None = None,
) -> DedupJudgement:
    """Layer 3 dedup judge. Pre-computes prior-coverage per candidate then
    delegates verdict-per-candidate classification to Haiku.

    Callers MUST inject haiku_call + prompt_template_path; this function
    never binds the Anthropic SDK directly.
    """
    if haiku_call is None or prompt_template_path is None:
        raise RuntimeError("haiku_call and prompt_template_path are required")

    if show:
        all_eps = scan_episode_wiki(wiki_dir, show, strict=False)
    else:
        # TODO(task-23): remove this legacy branch once every caller passes a Show.
        all_eps = _scan_episode_wiki_legacy(wiki_dir, strict=False)

    coverage = concepts_covered_by_episodes(all_eps)
    catalog = concept_catalog(wiki_dir, include_stubs=True)

    prior_hits: dict[str, list[dict]] = {}
    for cand in candidate_concepts:
        resolved = resolve_concept_candidate(cand, catalog) or cand
        prior_hits[cand] = coverage.get(resolved, [])

    # Open threads from the 5 most recent episodes
    open_threads = []
    for ep in sorted(all_eps, key=lambda e: e.episode_id)[-5:]:
        for t in ep.open_threads:
            open_threads.append({
                "ep_id": ep.episode_id,
                "note": t.note,
                "slug": t.slug,
            })

    template = prompt_template_path.read_text(encoding="utf-8")
    prompt = (template
              .replace("{candidates}", yaml.safe_dump(candidate_concepts, allow_unicode=True))
              .replace("{prior_hits}", yaml.safe_dump(prior_hits, allow_unicode=True))
              .replace("{open_threads}", yaml.safe_dump(open_threads, allow_unicode=True)))

    raw = haiku_call(prompt)
    candidate = raw.strip()
    if candidate.startswith("```"):
        first_nl = candidate.find("\n")
        candidate = candidate[first_nl + 1:] if first_nl >= 0 else candidate
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3]
    candidate = candidate.strip()
    data = json.loads(candidate)  # raises JSONDecodeError if malformed — caller can decide to retry

    return DedupJudgement(
        per_concept=list(data.get("per_concept") or []),
        episode_verdict=str(data.get("episode_verdict", "proceed")),
        framing_recommendation=str(data.get("framing_recommendation", "")),
    )
