# kb-arc Skill Design

**Date:** 2026-04-09
**Status:** Approved

## Overview

A Claude Code skill (`/kb-arc`) that archives substantive Q&A from tutoring sessions into the MLL lessons repository (`~/Documents/MLL/lessons/`). It scans the current conversation, groups exchanges by topic, intelligently merges new knowledge into existing lesson files (or creates new ones), updates the README index, and pushes to remote.

## Trigger

- **Slash command:** `/kb-arc`
- **Natural language:** "archive", "session wrap-up", "save lessons", "archive and exit", "archive this session"
- **Skill description:** `"Use when archiving or saving the current session's Q&A into lesson files, or when user says 'archive', 'session wrap-up', 'save lessons', 'archive and exit', or 'archive this session'. Triggers on any request to save conversation knowledge to the MLL lessons repository."`

## Architecture

- **Plugin:** `kb` (at `plugins/kb/skills/kb-arc/SKILL.md`)
- **Executor:** Opus single-pass (no subagents)
- **User-invocable:** true

### Why single-pass Opus

Tutoring sessions typically cover 1-3 topics. The bottleneck is judgment (what's new, what's duplicate, how to merge), not parallelism. Opus already holds the conversation context -- shipping excerpts to subagents adds complexity without meaningful speed gains.

## Target Repository

- **Path:** `~/Documents/MLL/lessons/`
- **Remote:** `git@github.com:renlon/MLL.git`
- **Hardcoded** -- MLL is a standalone repo, not part of the kb plugin's configurable wiki system.

## Workflow

### Step 1: Scan Conversation

Review all messages in the current session.

**Include:** Technical Q&A, explanations, code examples, conceptual discussions, teaching exchanges.

**Exclude:** Operational chatter -- git commands, formatting fixes, settings changes, tool invocations, skill triggers, file management, and any other non-teaching interactions.

### Step 2: Group by Topic

Cluster included exchanges into distinct topics. Each topic should be a coherent subject area (e.g., "KV Cache and Attention Mechanisms"), not overly broad ("LLM Concepts") or overly narrow (a single isolated question).

Closely related questions should be grouped together.

### Step 3: Language Detection

For each topic group, detect the dominant language of the conversation. The output lesson will be written in that language.

### Step 4: Read Existing Lessons

Glob `~/Documents/MLL/lessons/*.md` (excluding README.md). For each file, read its content to build a map of: topic -> file path -> key concepts covered.

### Step 5: Match Topics to Existing Lessons

For each grouped topic from Step 2:

- Compare against existing lesson **content** (not just filenames) to find semantic overlap
- A match means the existing lesson covers the same or closely related subject matter
- If multiple existing lessons could match, pick the closest one

### Step 6a: Existing Lesson Found -- Merge

1. Read the existing lesson file fully
2. Identify what's genuinely new in the conversation that isn't already covered
3. Update the technical summary sections with new knowledge (rewrite sections as needed to integrate cleanly -- do not just append paragraphs)
4. Append only new Q&A exchanges to the transcript section (skip exchanges that cover ground already in the file)
5. Rename the file to update the date suffix to today's date (e.g., `KV_Cache_2026-04-07.md` -> `KV_Cache_2026-04-09.md`)

### Step 6b: No Match -- Create New Lesson

1. Create a new file following the established format:
   - Header with topic name, session date, topic summary
   - Technical summary synthesized from the Q&A
   - Q&A transcript section with the relevant exchanges
2. Filename: `Topic_Name_YYYY-MM-DD.md` using today's date

### Step 7: Update README.md

Read `~/Documents/MLL/lessons/README.md` and update the topics table:

- For renamed files (merged lessons): update the filename link and date
- For new lessons: add a new row
- Maintain existing table sort order

### Step 8: Git Sync

1. `cd ~/Documents/MLL`
2. `git add` the specific files changed (new/renamed lesson files + README.md). Use `git add` on old filenames too if a rename occurred (or use `git mv`).
3. `git commit` with a descriptive message, e.g., `Add lesson: vLLM PagedAttention` or `Update lesson: KV Cache and Attention Mechanisms`
4. `git pull --rebase`
5. `git push`

No confirmation needed for any git operation.

### Step 9: Confirmation

Report to the user:

- Which topics were archived
- For each: whether it was merged into an existing lesson or created as new
- The filenames written
- Git push status (success or failure -- if push fails, inform the user but don't retry)

## Lesson File Format

Based on existing files in the repository:

```markdown
# Topic Name

**Session Date:** YYYY-MM-DD
**Topic:** Brief description of what was covered

---

## Technical Summary

Synthesized knowledge covering the topic. Organized by sub-concepts with clear headings. Written in the conversation's dominant language.

## Q&A Transcript

### Round N: Sub-topic

#### Q: The question asked

#### A: The answer given

(Code blocks, tables, and formatting preserved from the original exchange)
```

## Allowed Tools

Read, Write, Edit, Glob, Grep, Bash, Agent (for git operations)

## Edge Cases

- **Empty session (no substantive Q&A):** Report "No teaching content found to archive" and exit.
- **Git push fails:** Report the error to the user. Do not retry or force-push.
- **Pull --rebase conflicts:** Report the conflict to the user and leave the repo in its current state for manual resolution.
- **Lesson file rename when old name is referenced elsewhere:** Only README.md references lesson files; the README update in Step 7 handles this.
