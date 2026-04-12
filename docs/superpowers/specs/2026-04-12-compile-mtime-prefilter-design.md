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
last_compiled_at: "2026-04-12T10:30:00.123Z"  # ISO 8601 with max available precision, set by compile
```

If missing, unparseable, or in the future — fall back to full-scan behavior (hash everything). Zero migration required — the optimization activates from the second compile onward.

### Modified Incremental Detection

Replace the current "hash every file, diff against index" with three steps:

**Step 1 — Glob all sources** (unchanged, fast):
Glob `raw/` and `external_sources` to enumerate all source files. No content reading.

**Step 2 — Categorize without hashing:**
- **New files:** In glob but not in `_index.md` → add to process list directly. No hash needed at detection time.
- **Deleted files:** In `_index.md` but not in glob → flag for review.
- **Existing files:** In both glob and `_index.md` → proceed to mtime check.

**Step 3 — mtime pre-filter for existing files:**
- Read `last_compiled_at` from `kb.yaml`. Persist and compare with the highest available timestamp precision (fractional seconds). If `last_compiled_at` is missing, unparseable, or in the future → skip the pre-filter and hash all existing files (full-scan fallback).
- For each existing file, compare file mtime against `last_compiled_at` using inclusive comparison (`>=`).
- **mtime strictly older than `last_compiled_at`:** Skip. File hasn't changed since last compile. No hash computation.
- **mtime >= `last_compiled_at`:** Hash the file, compare against stored hash in `_index.md`. If different → add to process list as "changed". If same → skip (file was touched but content unchanged).

**Cost model:**
- Before: O(n) hashes every run, where n = total source files
- After: O(n) glob + O(changed) hashes

### Hash computation timing

New files bypass hashing at detection time — they're already known to need processing. However, the hash written to `_index.md` must come from the exact content snapshot used for compilation, not a post-compile re-read. When a file is read for extraction (Phase 2), hash the content at that moment and carry the hash forward to Phase 4. This prevents a race where a file is edited during compile: if compiled from bytes A but re-hashed as bytes B at Phase 4, the next run would see hash(B) matching the current file and skip recompilation, leaving stale output. This applies to all processed files (new and changed), not just new ones.

### Timestamp semantics

`last_compiled_at` uses the timestamp captured at the *start* of compile (before Phase 0), not the end. This ensures any file modified during a long-running compile is caught on the next run rather than silently missed.

Written to `kb.yaml` in Phase 4, at the same time as `_index.md` and other index updates. Use the highest available precision (fractional seconds) to minimize same-tick collisions.

### Partial failure behavior

If some files compile successfully and others fail during a run, `last_compiled_at` is still advanced. However, failed files do NOT get their hash updated in `_index.md`. This guarantees that on the next run, the failed file either: (a) has no index entry (new file) and is re-processed, or (b) still has its old hash in the index, so when mtime triggers a hash check, the mismatch causes recompilation. The invariant: a file's hash in `_index.md` always reflects the content that was last successfully compiled.

### Full-scan escape hatch

**Known limitation:** Any operation that changes file content without updating mtime will bypass the pre-filter. This includes: backup restore with preserved timestamps, rsync/copy with `-a` or `-p` flags, archive extraction preserving mtimes, manual `touch -r`, and clock skew. The escape hatch below handles all of these.

If the user suspects mtime missed a change, they can:
- Delete `last_compiled_at` from `kb.yaml`, or
- Say "full compile" (the skill recognizes this phrase and treats it as if `last_compiled_at` is missing for this run only — does not delete the field)

The skill detects the missing/ignored field and falls back to hash-everything behavior. One full scan resets the baseline (writes a fresh `last_compiled_at`), then mtime optimization resumes from the next compile.

## SKILL.md changes

Three localized modifications to the existing file:

1. **Incremental Detection section** — Replace steps 1-5 with the mtime-aware three-step version. Step 6 (merged file handling) and everything after remains untouched.

2. **Index Maintenance section** — Add two items:
   - Compute and store hashes for all newly compiled sources when writing `_index.md`
   - Write `last_compiled_at` (compile-start timestamp) to `kb.yaml`

3. **Common Mistakes section** — Add two entries:
   - Using compile-end time instead of compile-start time for `last_compiled_at` — files modified during a long compile would be missed on the next run
   - Hashing a file at Phase 4 instead of when it's read for extraction — if the file was edited during compile, the stored hash won't match the compiled content, causing the next run to skip a stale compilation

No new files, scripts, or sidecar formats.

## Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | mtime pre-filter over JSON sidecar | Biggest speedup for least complexity. The bottleneck is hashing, not index parsing. |
| 2 | No parallel hashing | YAGNI. mtime eliminates most hashing; parallel hashing can be added later if needed. |
| 3 | Compile-start timestamp | Files modified during compile must be caught next run, not missed. |
| 4 | Missing/invalid/future field = full scan | Zero-migration for existing KBs. Also serves as the escape hatch. Deterministic behavior across model executions. |
| 5 | Hash at read time, not post-compile | Hash the exact bytes used for compilation. Prevents stale-output bug from concurrent edits during compile. |
| 6 | No changes to _index.md format | Markdown table stays human-readable in Obsidian. Hashes still stored there. |
| 7 | Inclusive mtime comparison (`>=`) with max precision | Eliminates same-tick collision risk at the cost of a few extra hashes on the boundary. |
| 8 | Advance `last_compiled_at` even on partial failure | Failed files keep their old hash in `_index.md`, so they still appear "changed" on next run. Simpler than all-or-nothing semantics. |
