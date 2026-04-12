# Compile mtime Pre-filter Design

## Problem

The KB compile workflow hashes every file in `raw/` and `external_sources` on every run to diff against `wiki/_index.md`. As the source tree grows (hundreds of tweets, web-clipped articles, lessons), this O(n) hash operation becomes the bottleneck — compile time grows linearly with total file count, not with the number of changed files.

## Goal

Make incremental detection proportional to the number of *changed* files, not the total file count. A compile with 3 changed files out of 500 should do 3 hashes, not 500.

## Approach: mtime pre-filter

Use file modification time (`mtime`) as a fast pre-filter to skip hashing unchanged files. Store a `last_compiled_at` timestamp in `kb.yaml` and only hash files whose mtime is newer than that timestamp.

## Design

### New config field

Add `last_compiled_at` to `kb.yaml`, written by the compile skill at the end of each successful compile (Phase 4, alongside index updates):

```yaml
last_compiled_at: "2026-04-12T10:30:00Z"  # ISO 8601, set by compile
```

If missing (first run or legacy KB), fall back to full-scan behavior (hash everything). Zero migration required — the optimization activates from the second compile onward.

### Modified Incremental Detection

Replace the current "hash every file, diff against index" with three steps:

**Step 1 — Glob all sources** (unchanged, fast):
Glob `raw/` and `external_sources` to enumerate all source files. No content reading.

**Step 2 — Categorize without hashing:**
- **New files:** In glob but not in `_index.md` → add to process list directly. No hash needed at detection time.
- **Deleted files:** In `_index.md` but not in glob → flag for review.
- **Existing files:** In both glob and `_index.md` → proceed to mtime check.

**Step 3 — mtime pre-filter for existing files:**
- Read `last_compiled_at` from `kb.yaml`.
- For each existing file, compare file mtime against `last_compiled_at`.
- **mtime older than `last_compiled_at`:** Skip. File hasn't changed since last compile. No hash computation.
- **mtime newer than `last_compiled_at`:** Hash the file, compare against stored hash in `_index.md`. If different → add to process list as "changed". If same → skip (file was touched but content unchanged).

**Cost model:**
- Before: O(n) hashes every run, where n = total source files
- After: O(n) glob + O(changed) hashes

### Hash computation timing

New files bypass hashing at detection time — they're already known to need processing. Compute their hash *after* compile succeeds, right before writing the updated `_index.md` entry. This avoids double-hashing (once to detect, once to store).

### Timestamp semantics

`last_compiled_at` uses the timestamp captured at the *start* of compile (before Phase 0), not the end. This ensures any file modified during a long-running compile is caught on the next run rather than silently missed.

Written to `kb.yaml` in Phase 4, at the same time as `_index.md` and other index updates.

### Full-scan escape hatch

If the user suspects mtime missed a change (backup restore with preserved timestamps, clock skew), they can:
- Delete `last_compiled_at` from `kb.yaml`, or
- Say "full compile" (the skill recognizes this phrase and treats it as if `last_compiled_at` is missing for this run only — does not delete the field)

The skill detects the missing/ignored field and falls back to hash-everything behavior. One full scan resets the baseline (writes a fresh `last_compiled_at`), then mtime optimization resumes from the next compile.

## SKILL.md changes

Three localized modifications to the existing file:

1. **Incremental Detection section** — Replace steps 1-5 with the mtime-aware three-step version. Step 6 (merged file handling) and everything after remains untouched.

2. **Index Maintenance section** — Add two items:
   - Compute and store hashes for all newly compiled sources when writing `_index.md`
   - Write `last_compiled_at` (compile-start timestamp) to `kb.yaml`

3. **Common Mistakes section** — Add one entry:
   - Using compile-end time instead of compile-start time for `last_compiled_at` — files modified during a long compile would be missed on the next run

No new files, scripts, or sidecar formats.

## Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | mtime pre-filter over JSON sidecar | Biggest speedup for least complexity. The bottleneck is hashing, not index parsing. |
| 2 | No parallel hashing | YAGNI. mtime eliminates most hashing; parallel hashing can be added later if needed. |
| 3 | Compile-start timestamp | Files modified during compile must be caught next run, not missed. |
| 4 | Missing field = full scan | Zero-migration for existing KBs. Also serves as the escape hatch. |
| 5 | Hash new files after compile, not at detection | Avoids double-hashing. Detection only needs to know "this is new." |
| 6 | No changes to _index.md format | Markdown table stays human-readable in Obsidian. Hashes still stored there. |
