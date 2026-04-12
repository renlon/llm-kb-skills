# Compile mtime Pre-filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make compile incremental detection O(changed) instead of O(n) by using file mtime as a pre-filter before hashing.

**Architecture:** Add `last_compiled_at` timestamp to `kb.yaml`, captured at compile start. Incremental Detection globs all files, categorizes as new/deleted/existing without hashing, then only hashes existing files whose mtime >= `last_compiled_at`. Hashes stored in `_index.md` come from the exact bytes read for compilation, not a post-compile re-read.

**Tech Stack:** Pure markdown SKILL.md modifications (behavioral instructions for LLM executor). No scripts or code files.

---

## File Structure

- Modify: `plugins/kb/skills/kb/SKILL.md` — Incremental Detection (lines 172-178), Index Maintenance (lines 317-325), Common Mistakes (lines 467-481)
- Modify: `plugins/kb/.claude-plugin/plugin.json` — version bump
- Modify: `CLAUDE.md` — no changes needed (kb skill description already updated in 1.6.0)

---

### Task 1: Replace Incremental Detection steps 1-5

**Files:**
- Modify: `plugins/kb/skills/kb/SKILL.md:172-178`

- [ ] **Step 1: Read the current Incremental Detection section**

Read `plugins/kb/skills/kb/SKILL.md` lines 172-194 to confirm current content before editing.

- [ ] **Step 2: Replace steps 1-5 with mtime-aware detection**

Replace lines 174-178 (the five current steps) with the following. Do NOT touch step 6 (merged file handling) — it stays exactly as-is.

```markdown
**Capture compile-start timestamp** before any other work in the compile workflow (before Phase 0). Store in memory as `compile_start_ts` (ISO 8601 with maximum available precision, e.g. fractional seconds). This timestamp will be written to `kb.yaml` in Phase 4.

If the user said "full compile", treat `last_compiled_at` as missing for this run (full-scan mode). Do not delete the field from `kb.yaml`.

1. Read `wiki/_index.md` (lists every raw source with its last-compiled hash)
2. Scan `raw/` recursively with Glob
3. Scan each `external_sources` path from `kb.yaml` (if any). Prefix entries in the index with `external:<label>/` to distinguish them from `raw/` sources.
4. **Categorize without hashing:**
   - **New files:** In glob but not in `_index.md` → add to process list directly. No hash needed at detection time.
   - **Deleted files:** In `_index.md` but not in glob → flag for review.
   - **Existing files:** In both glob and `_index.md` → proceed to mtime check (step 5).
5. **mtime pre-filter for existing files:**
   - Read `last_compiled_at` from `kb.yaml`. If missing, unparseable, or in the future → fall back to full-scan mode: hash ALL existing files against the index (skip the mtime check).
   - For each existing file, compare file mtime against `last_compiled_at` using inclusive comparison (`>=`):
     - **mtime strictly older:** Skip -- file hasn't changed since last compile. No hash computation.
     - **mtime >= `last_compiled_at`:** Hash the file, compare against stored hash in `_index.md`. If different → add to process list as "changed". If same → skip (touched but content unchanged).
   - Log: "Incremental detection: N new, M changed, D deleted (K files skipped via mtime)"
```

- [ ] **Step 3: Verify step 6 (merged file handling) is untouched**

Read the file again and confirm step 6 begins immediately after the new step 5 with no duplication or gap.

- [ ] **Step 4: Commit**

```bash
git add plugins/kb/skills/kb/SKILL.md
git commit -m "feat(kb): replace O(n) hash detection with mtime pre-filter in Incremental Detection"
```

---

### Task 2: Update Index Maintenance section

**Files:**
- Modify: `plugins/kb/skills/kb/SKILL.md:317-325`

- [ ] **Step 1: Read the current Index Maintenance section**

Read `plugins/kb/skills/kb/SKILL.md` lines 317-326 to confirm current content.

- [ ] **Step 2: Add hash-at-read-time instruction and last_compiled_at write**

After the existing `_evolution.md` bullet (line 324) and before the `needs_canonical_recompile` clear bullet (line 325), insert the following two items:

```markdown
- **Hash at read time:** When writing source hashes to `_index.md`, use the hash computed when the file was read for extraction (Phase 2), NOT a re-read of the file at Phase 4. This prevents stale-output bugs if a file is edited during compile. For failed files, do NOT update their hash in `_index.md` -- leave the old hash so they appear "changed" on the next run.
- **Write `last_compiled_at`:** Write the `compile_start_ts` (captured before Phase 0) to `kb.yaml` as `last_compiled_at` (ISO 8601 with maximum available precision). This advances the mtime baseline for the next compile. Write this even if some files failed -- failed files are protected by their stale hash in `_index.md`.
```

- [ ] **Step 3: Verify the section reads correctly end-to-end**

Read the full Index Maintenance section and confirm the bullet order is:
1. `_index.md`
2. `_sources.md`
3. `_categories.md`
4. `_evolution.md`
5. Hash at read time (NEW)
6. Write `last_compiled_at` (NEW)
7. Clear `needs_canonical_recompile`

- [ ] **Step 4: Commit**

```bash
git add plugins/kb/skills/kb/SKILL.md
git commit -m "feat(kb): add hash-at-read-time and last_compiled_at to Index Maintenance"
```

---

### Task 3: Add common mistakes

**Files:**
- Modify: `plugins/kb/skills/kb/SKILL.md:467-481`

- [ ] **Step 1: Read the current Common Mistakes section**

Read `plugins/kb/skills/kb/SKILL.md` lines 467-481 to confirm end of file.

- [ ] **Step 2: Append two new entries**

Add the following two lines at the end of the Common Mistakes section (after the last existing entry about scanning file body):

```markdown
- Using compile-end time instead of compile-start time for `last_compiled_at` -- files modified during a long compile would be missed on the next run
- Hashing a source file at Phase 4 instead of when it's read for extraction -- if the file was edited during compile, the stored hash won't match the compiled content, and the next run will skip a stale compilation
```

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/skills/kb/SKILL.md
git commit -m "feat(kb): add mtime and hash-timing common mistakes"
```

---

### Task 4: Version bump

**Files:**
- Modify: `plugins/kb/.claude-plugin/plugin.json`

- [ ] **Step 1: Read plugin.json**

Read `plugins/kb/.claude-plugin/plugin.json` and confirm current version is `1.6.0`.

- [ ] **Step 2: Bump version to 1.7.0**

Change `"version": "1.6.0"` to `"version": "1.7.0"`.

- [ ] **Step 3: Commit**

```bash
git add plugins/kb/.claude-plugin/plugin.json
git commit -m "chore(kb): bump version to 1.7.0 for mtime pre-filter"
```

---

### Task 5: Verification

- [ ] **Step 1: Read the full Incremental Detection section**

Read `plugins/kb/skills/kb/SKILL.md` from `### Incremental Detection` through `### Per-File Extraction`. Verify:
- Steps 1-3 (glob) are present
- Step 4 (categorize without hashing) lists new/deleted/existing
- Step 5 (mtime pre-filter) has: `last_compiled_at` read, missing/invalid/future fallback, `>=` comparison, skip-if-older, hash-if-newer
- Step 6 (merged file handling) is unchanged with all sub-steps a-e
- `compile_start_ts` capture instruction appears before step 1
- "full compile" override instruction appears before step 1
- Log line instruction at end of step 5

- [ ] **Step 2: Read the full Index Maintenance section**

Verify:
- Hash-at-read-time bullet mentions Phase 2 read, not Phase 4 re-read
- Hash-at-read-time bullet says failed files keep old hash
- `last_compiled_at` bullet references `compile_start_ts`, mentions max precision
- `last_compiled_at` bullet says write even on partial failure
- `needs_canonical_recompile` clear bullet is still last

- [ ] **Step 3: Read Common Mistakes**

Verify both new entries are present at the end of the section.

- [ ] **Step 4: Verify version**

Read `plugins/kb/.claude-plugin/plugin.json` and confirm `1.7.0`.

---

## Self-Review

**Spec coverage:**
| Spec Section | Plan Task |
|---|---|
| New config field (`last_compiled_at`) | Task 2 (Index Maintenance writes it), Task 1 (Detection reads it) |
| Modified Incremental Detection (3-step) | Task 1 |
| Hash computation timing (read-time) | Task 2 |
| Timestamp semantics (compile-start, max precision) | Task 1 (capture), Task 2 (write) |
| Partial failure behavior | Task 2 (failed files keep old hash) |
| Full-scan escape hatch | Task 1 ("full compile" override, missing/invalid/future fallback) |
| SKILL.md changes — Incremental Detection | Task 1 |
| SKILL.md changes — Index Maintenance | Task 2 |
| SKILL.md changes — Common Mistakes | Task 3 |

All spec sections covered. No gaps.

**Placeholder scan:** No TBD, TODO, "add appropriate", or "similar to Task N" found.

**Type consistency:** `compile_start_ts` used consistently in Task 1 (capture) and Task 2 (write). `last_compiled_at` used consistently as the YAML field name. `>=` comparison specified in both spec and Task 1.
