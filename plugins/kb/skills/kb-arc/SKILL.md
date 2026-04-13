---
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Skill
description: "Use when archiving or saving the current session's Q&A into lesson files, or when user says 'archive', 'session wrap-up', 'save lessons', 'archive and exit', or 'archive this session'. Triggers on any request to save conversation knowledge to the MLL lessons repository."
---

# Archive Skill -- Session Q&A to Lessons

Archive substantive Q&A from the current conversation into `~/Documents/MLL/lessons/`. Merges new knowledge into existing lesson files or creates new ones, updates the README index, and pushes to the remote git repository.

**Invocation:** `/kb-arc` (no arguments)

**Executor:** Opus single-pass. No subagents.

## Workflow

### Step 1: Scan Conversation

Review all messages in the current session. Classify each exchange:

**Include:**
- Technical Q&A and explanations
- Code examples and walkthroughs
- Conceptual discussions and teaching exchanges
- Analogies, comparisons, and deep-dives

**Exclude:**
- Operational chatter: git commands, formatting fixes, settings changes
- Tool invocations, skill triggers, file management requests
- Greetings, acknowledgments, and non-teaching small talk
- This archival request itself

If no substantive Q&A is found, report "No teaching content found to archive" and stop.

### Step 2: Group by Topic

Cluster the included exchanges into distinct topics.

**Granularity guidelines:**
- Each topic should be a coherent subject area (e.g., "KV Cache and Attention Mechanisms")
- NOT overly broad (e.g., "LLM Concepts") or overly narrow (a single isolated question)
- Closely related questions belong in the same group
- A single session might produce 1-3 topics typically

**Language:** For each topic group, note the dominant language used in the conversation. Write the lesson output in that same language.

### Step 3: Read Existing Lessons

1. Glob `~/Documents/MLL/lessons/*.md`
2. Exclude `README.md`
3. For each lesson file, read its content to understand what topics and concepts it covers
4. Build a mental map of: topic area -> file path -> key concepts already documented

### Step 4: Match Topics to Existing Lessons

For each grouped topic from Step 2:

- Compare against existing lesson **content** (not just filenames) to find semantic overlap
- A match means the existing lesson covers the same or closely related subject matter
- If multiple existing lessons could match, pick the closest one
- If no match, this topic gets a new file

### Step 5: Write Lessons

#### 5a: Existing Lesson Found -- Merge

1. Read the existing lesson file fully
2. Identify what is genuinely new in the conversation that is not already covered
3. **Technical Summary section:** Rewrite and integrate new knowledge into the existing summary. Do not just append paragraphs -- merge cleanly so the summary reads as a unified document with no redundancy.
4. **Q&A Transcript section:** Append only new Q&A exchanges. Skip exchanges that cover ground already present in the file.
5. Rename the file to update the date suffix to today's date using `git mv`. If the existing file has no date suffix, skip the rename and write in place.

Example (substitute actual filename and today's date):

```bash
cd ~/Documents/MLL
git mv "lessons/KV_Cache_and_Attention_Mechanisms_2026-04-07.md" "lessons/KV_Cache_and_Attention_Mechanisms_2026-04-09.md"
```

#### 5b: No Match -- Create New Lesson

Create a new file at `~/Documents/MLL/lessons/Topic_Name_YYYY-MM-DD.md` using today's date.

**File format:**

```
# Topic Name

**Session Date:** YYYY-MM-DD
**Topic:** Brief description of what was covered

---

## Technical Summary

Synthesized knowledge covering the topic. Organized by sub-concepts with
clear headings. Written in the conversation's dominant language.

## Q&A Transcript

### Round 1: Sub-topic

#### Q: The question as asked

#### A: The answer as given

(Preserve code blocks, tables, and formatting from the original exchange.)
```

### Step 6: Generate Diagrams (Optional)

For each lesson file written or updated in Step 5, evaluate whether any technical content would benefit from an Excalidraw diagram:

**Criteria — generate a diagram when:**
- The lesson contains a workflow, pipeline, or multi-step process explanation
- The lesson describes an architecture with multiple interacting components
- The lesson covers a data flow or transformation chain
- A diagram would meaningfully aid comprehension beyond what the text provides

**Criteria — skip when:**
- The lesson is purely conceptual Q&A without visual structure
- The content is a single definition or isolated fact
- The lesson is thin (< 200 words of technical content)

**Incremental check:** Before generating, check if `wiki/diagrams/<lesson-slug>.excalidraw` already exists:
- If exists and lesson content is unchanged (merged with no new diagrammable material) → skip
- If exists but lesson has new diagrammable content → regenerate
- If does not exist → generate

**Generation:** Invoke the `kb-excalidraw` skill (via Skill tool) with:
- `concept_name`: the lesson's primary topic
- `relationships`: concepts mentioned in the lesson that have wiki articles (extract `[[wikilinks]]` from the lesson)
- `diagram_type`: inferred from content
- `context`: the Technical Summary section of the lesson
- `output_path`: `wiki/diagrams/<lesson-slug>.excalidraw`

**Naming:** `<lesson-slug>.excalidraw` — derived from the lesson filename, lowercase, hyphenated. Example: lesson file `KV_Cache_and_Attention_Mechanisms_2026-04-09.md` → `kv-cache-and-attention-mechanisms.excalidraw` (strip date suffix).

**Embedding:** Add `![[<lesson-slug>.excalidraw]]` to the lesson file, at the end of the Technical Summary section. Skip if embed already present.

**Open in Obsidian:** Read `obsidian.vault_name` from `kb.yaml` at `~/Documents/MLL/kb.yaml`. Run:
```bash
open "obsidian://open?vault=<vault_name>&file=wiki/diagrams/<lesson-slug>.excalidraw"
```

If no lessons qualify for diagrams, skip this step silently.

### Step 7: Update README.md

Read `~/Documents/MLL/lessons/README.md`. Update the topics table in the `## Topics` section:

- For renamed files (merged lessons): update the filename in the link and the date column
- For new lessons: add a new row to the table
- Maintain the existing table structure and sort order

### Step 8: Git Sync

Run these commands in sequence:

```bash
cd ~/Documents/MLL && git add lessons/ && git commit -m "<descriptive message>" && git pull --rebase && git push
```

**Commit message format:**
- Single new lesson: `Add lesson: Topic Name`
- Single updated lesson: `Update lesson: Topic Name`
- Multiple lessons: `Archive session: Topic1, Topic2`

No confirmation needed for any git operation. If `git pull --rebase` or `git push` fails, report the error to the user and stop. Do not retry or force-push.

### Step 9: Confirmation

Report to the user:

- Which topics were archived
- For each topic: whether it was merged into an existing lesson or created as new
- The filenames written (with full paths)
- Which diagrams were generated (if any), with Obsidian links
- Git push status

## Edge Cases

- **No substantive Q&A in session:** Report "No teaching content found to archive" and exit at Step 1.
- **Git push fails:** Report the error. Do not retry or force-push.
- **Rebase conflicts:** Report the conflict and leave the repo for manual resolution.
- **Lessons directory missing:** Run `mkdir -p ~/Documents/MLL/lessons` before proceeding.
- **README.md missing or has no topics table:** Create the table with the standard structure.
