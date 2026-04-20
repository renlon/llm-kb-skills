---
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Skill, Agent
description: "Use when archiving or saving the current session's Q&A into lesson files, or when user says 'archive', 'session wrap-up', 'save lessons', 'archive and exit', or 'archive this session'. Also use when archiving a previous/historical session from a transcript file (e.g., 'archive this transcript', 'kb-arc /path/to/file.jsonl'). Triggers on any request to save conversation knowledge to the MLL lessons repository."
---

# Archive Skill -- Session Q&A to Lessons

Archive substantive Q&A from the current conversation (or a historical transcript file) into `~/Documents/MLL/lessons/`. Merges new knowledge into existing lesson files or creates new ones, updates the README index, and pushes to the remote git repository.

**Invocation:** `/kb-arc [source]`

- No argument: scans the current conversation (default behavior)
- With file path: reads a historical Claude Code transcript (`.jsonl` format)

**Executor:** Opus single-pass. No subagents.

## Workflow

### Step 0: Resolve Source

Determine where to read Q&A content from:

**If a file path argument is provided** (historical transcript mode):

1. Verify the file exists and has a `.jsonl` extension. If not, report error and STOP.
2. The file is a Claude Code session transcript in JSONL format. Each line is a JSON object.
3. **Parse the transcript using a subagent.** The file is typically large (500KB-1MB+), so delegate extraction to an Agent:
   - Launch an Agent with the prompt: read the JSONL file in chunks (10-15 lines at a time using offset/limit) and extract all substantive teaching exchanges
   - **Extract user messages:** Look for lines with `"type":"user"` that contain actual user text in `message.content` (string or array with text blocks). Skip lines where `message.content` is a `tool_result` array (these are tool outputs, not user questions).
   - **Extract assistant explanations:** Look for lines with `"type":"assistant"` that contain `"type":"text"` content blocks in `message.content`. Extract the text values.
   - **Skip non-teaching content:** Ignore session setup (permission-mode, hook_success, deferred_tools_delta, skill_listing, mcp_instructions_delta), tool_use blocks, file-history-snapshot lines, and last-prompt lines.
   - The agent should return: a structured summary of all Q&A exchanges, grouped by conversational flow.
4. Use the extracted Q&A as the input for Step 2 (skip Step 1 since we already have the content).

**If no argument is provided** (current session mode):

Proceed to Step 1 as before — scan the current conversation.

### Step 1: Scan Conversation

Review all messages in the current session (skip this step if using historical transcript mode — content was already extracted in Step 0). Classify each exchange:

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

**Question clarity rule (applies to all Q&A written in this step):**

Questions in a live session often rely on implicit context — earlier turns, shared screen state, a file being read, a concept just defined, or pronouns like "it"/"that"/"this one". A future reader opening the lesson file will not have that context. When transcribing each question into the lesson:

- Rewrite the question so it stands alone. Expand pronouns, name the subject explicitly, and inline any assumed background (e.g., "Given we're discussing KV cache..." or "In the context of X, ...").
- Preserve the user's original intent and tone. Do not invent questions the user did not ask, and do not editorialize.
- If a question only makes sense as a follow-up to a prior exchange in the same lesson, keep it tight and rely on the preceding Q&A within the same Round to supply context. If it spans Rounds or topics, make it self-contained.
- If the original phrasing is already clear and self-contained, use it verbatim.

Apply the same rule to answers only where needed to remove dangling references ("as I said above", "that file we looked at") — otherwise preserve the answer as given.

**Preserve visual artifacts verbatim in the Q&A transcript:**

When Claude's original answer contained any of the following, copy them into the lesson's Q&A Transcript section **as-is**, inside the corresponding answer block. Do not paraphrase them into prose:

- Markdown tables — keep the full table with all rows, columns, and alignment. A table was worth drawing in the live session, so it is worth preserving.
- ASCII / Unicode box-drawing diagrams (e.g., boxes made of `─│┌┐└┘`, arrows like `──→`, tree sketches with `├──`).
- Mermaid, PlantUML, or other text-based diagram fences.
- Code blocks, CLI transcripts, and formatted output.

These artifacts are also signals for Step 6 (see "Recreate visual artifacts from the session" there) — they should be captured in the transcript **and** re-rendered as Excalidraw diagrams.

#### 5a: Existing Lesson Found -- Merge

1. Read the existing lesson file fully
2. Identify what is genuinely new in the conversation that is not already covered
3. **Technical Summary section:** Rewrite and integrate new knowledge into the existing summary. Do not just append paragraphs -- merge cleanly so the summary reads as a unified document with no redundancy.
4. **Q&A Transcript section:** Append only new Q&A exchanges, applying the question clarity rule above. Skip exchanges that cover ground already present in the file.
5. Rename the file to update the date suffix to today's date using `git mv`. If the existing file has no date suffix, skip the rename and write in place.

Example (substitute actual filename and today's date):

```bash
cd ~/Documents/MLL
git mv "lessons/KV_Cache_and_Attention_Mechanisms_2026-04-07.md" "lessons/KV_Cache_and_Attention_Mechanisms_2026-04-09.md"
```

#### 5b: No Match -- Create New Lesson

Create a new file at `~/Documents/MLL/lessons/Topic_Name_YYYY-MM-DD.md` using today's date.

**File format:** Read the template from `prompts/lesson-format.md` relative to this skill's directory. Use it as the structure for new lesson files.

### Step 6: Generate Diagrams

**This step is mandatory.** Generate a diagram for every lesson file written or updated in Step 5. Do not skip this step based on subjective judgment about whether the content "needs" a diagram — every lesson gets one.

**Only skip when ALL of the following are true:**
- The lesson is under 100 words of technical content AND
- The content is a single isolated definition with no relationships to visualize AND
- The original session contained no visual artifacts (no tables, no ASCII/Mermaid diagrams) for this topic

**Recreate visual artifacts from the session (highest priority):**

Before picking a generic diagram type, scan the session's answers for visuals Claude already drew to explain the topic:

- **ASCII / Unicode diagrams, Mermaid blocks, tree sketches, flow sketches** — these are literal diagrams the user already saw and found explanatory. Reproduce each one as an Excalidraw diagram that preserves the same structure (same nodes, same edges, same direction of flow, same grouping). This takes precedence over the generic "diagram type by content" heuristic below.
- **Markdown tables** — a table is a visual artifact too. If the table expresses a comparison, tradeoff matrix, or taxonomy that benefits from a graphical view, generate a `comparison` or `hierarchy` Excalidraw diagram that encodes the same relationships. Keep the raw markdown table in the Q&A Transcript as well (per Step 5) — Excalidraw complements, not replaces, the table.
- **Multiple visuals in one lesson** — if a single lesson has more than one distinct visual (e.g., an ASCII diagram AND a comparison table), generate multiple Excalidraw files (`<lesson-slug>-1.excalidraw`, `<lesson-slug>-2.excalidraw`, etc.) and embed each one at the most relevant location in the lesson body.

When passing the context to `kb-excalidraw`, include the original ASCII/Mermaid block or table in the `context` field so the engine can mirror its structure.

**Fallback — diagram approach by content type** (only when no session visual exists for the topic):
- Workflow/pipeline/process → `workflow` diagram showing the steps and flow
- Architecture/system with components → `architecture` diagram showing relationships
- Data transformations or I/O chains → `data_flow` diagram
- Taxonomy, hierarchy, or categorization → `hierarchy` diagram
- Tradeoffs, alternatives, or comparisons → `comparison` diagram
- Conceptual Q&A or definitions → `hierarchy` or `architecture` diagram showing how the concept relates to its key terms and sub-concepts

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

If a lesson is under 100 words and contains only a single isolated definition, log "Skipped diagram for <lesson>: too thin" and move on. All other lessons must get a diagram.

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
- **Transcript file not found:** Report "File not found: <path>" and STOP.
- **Transcript file not .jsonl:** Report "Expected a .jsonl transcript file, got: <extension>" and STOP.
- **Transcript too large for single read:** This is expected — use the Agent-based chunked reading in Step 0. Never attempt to read the entire file at once.
- **Transcript contains no teaching content:** After extraction, if the agent reports no substantive Q&A, report "No teaching content found in transcript" and STOP.
- **Transcript from compacted session:** Compacted sessions may have truncated early messages. Archive whatever teaching content is present; note in confirmation that the session may be incomplete.
