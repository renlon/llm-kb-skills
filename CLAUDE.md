# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Identity

- LLM Knowledge Base project -- a Claude Code plugin (`plugins/kb/`) that turns raw research material into LLM-maintained Obsidian wikis.
- The wiki is the domain of the LLM. Never manually edit wiki articles outside of the kb skill workflows.

## Development Commands

```bash
# Install plugin locally in Claude Code
/plugin install kb@llm-kb-skills

# Run Obsidian plugin installer (called automatically by kb-init)
bash plugins/kb/setup.sh /path/to/vault          # interactive mode
bash plugins/kb/setup.sh /path/to/vault --all     # install all plugins
bash plugins/kb/setup.sh /path/to/vault --only dataview,obsidian-git

# Validate research JSON output
python3 plugins/kb/skills/research/validate_json.py <result.json> <fields.yaml>
```

No build step, test suite, or linter -- the project is pure SKILL.md prompts and one bash script.

## Architecture

### Plugin Structure

Single plugin (`kb`) registered via `plugins/kb/.claude-plugin/plugin.json` (version source of truth). Top-level `.claude-plugin/marketplace.json` registers the repo in the Claude Code marketplace.

Skills are SKILL.md files with YAML frontmatter (name, description, triggers) followed by structured prompts Claude executes verbatim. Each skill lives in its own directory under `plugins/kb/skills/` and may contain:
- `prompts/` -- Reusable prompt templates referenced by the SKILL.md.
- `references/` -- Static reference docs (schemas, color palettes, CSS selectors).
- `scripts/` -- Python scripts for automation (validation, cover art generation, browser upload).

### Key Patterns

- **Incremental compilation** -- `wiki/_index.md` tracks source file hashes. Only new/changed sources are reprocessed; never recompiles the full `raw/` folder.
- **Index-first querying** -- Questions are answered from wiki indexes and summaries first, avoiding vector search or RAG infrastructure. Three depth levels: quick (indexes only), standard (full wiki + web), deep (multi-agent research pipeline).
- **Silent auto-evolve** -- After every query, a background subagent checks if the response contained new knowledge and silently files it into the wiki. The user is never prompted.
- **Graceful degradation** -- Optional integrations (Smaug for X/Twitter, output formats) degrade gracefully when unavailable.

### Subagent Dispatch

Skills dispatch subagents for parallel work (compilation, lint, research). Each subagent call must set the `model` parameter explicitly -- never inherit the parent model.

## Release Workflow

Before every `git push` to remote:

1. **Always `git pull --rebase` first** to avoid rejected pushes. The remote may have been updated by other sessions.
2. **Bump the version** in `plugins/kb/.claude-plugin/plugin.json` (patch bump unless the change warrants minor/major).
3. **Check if the plugin is installed locally** by running `claude plugin list 2>/dev/null | grep -q 'kb@llm-kb-skills'`. If installed, run `claude plugin marketplace update llm-kb-skills` first to refresh the cache, then `claude plugin install kb@llm-kb-skills` to upgrade. (`plugin install` alone does not pull the latest from remote.)

## Configuration

- Always read `kb.yaml` at the project root before operating. It contains paths, output format preferences, Obsidian config, and external source paths.
- `external_sources` in `kb.yaml` lists folders outside the project that are included in compile, lint, and indexing. These are read-only by default -- the skill never modifies files in external paths.
- `compile.diagrams.enabled` in `kb.yaml` controls auto-diagram generation during compile (default: `false`).
- `obsidian.vault_name` in `kb.yaml` is used for `obsidian://` URI construction to open diagrams in Obsidian.
- Generated diagrams are stored in `wiki/diagrams/` and embedded via `![[name.excalidraw]]`.

## Skills

- `kb-init` -- One-time setup to bootstrap a new knowledge base.
- `kb` -- Main operating skill with four workflows: compile (with X enrichment Phase 0), query, lint, evolve.
- `research` -- Initial research outline generation.
- `research-deep` -- Deep research via independent agents per outline item.
- `research-add-fields` -- Add field definitions to an existing research outline.
- `research-add-items` -- Add items (research targets) to an existing research outline.
- `research-report` -- Summarize deep research results into a markdown report.
- `kb-arc` -- Archive session Q&A into MLL lessons with intelligent merge and auto git-push.
- `kb-excalidraw` -- Diagram engine: generates Excalidraw JSON from concept descriptions. Used by `/kb diagram`, compile Phase 3.5, and `kb-arc`.
- `kb-notebooklm` -- Bridge KB to Google NotebookLM for podcasts, quizzes, digests, reports. Before podcast generation, cross-checks published episodes to avoid duplicate content and injects series bible into prompt for episode-to-episode continuity.
- `kb-publish` -- Publish podcast episodes to 小宇宙FM. Assigns episode IDs from shared registry, generates 口语化 titles with EP prefix, creates cover art via Gemini (大气/简约/接地气 style), uploads via Playwright persistent context. Writes content manifest to episodes.yaml after upload.
- `kb-x-setup` -- Configure automated X/Twitter ingestion via Smaug into `raw/articles/x/`.

## Formatting Rules (Obsidian-Compatible)

- `[[wikilinks]]` for all internal links (never markdown-style links).
- `[[wikilinks|display text]]` when the display name differs from the target.
- YAML frontmatter on every article with: title, aliases, tags, article_format, sources.
- `![[image.png]]` for image embeds.
- Always leave a full empty line between any text/heading and the first row of a markdown table. Without that blank line, Obsidian treats the table as plain text.

## Article Formats

- Two formats: `default` (reference-style) and `tutorial` (easy-to-hard teaching hierarchy).
- The LLM chooses the format per concept during compilation based on content type -- no manual config needed.
- Technical skills, tools, patterns, and methodologies with sufficient depth get `tutorial`. Everything else gets `default`.
- The `article_format` field in frontmatter records which format was used.

## Security

- Never include personal information (names, addresses, phone numbers, emails) in committed files, wiki articles, or output.
- Never include credentials, API keys, tokens, passwords, or session cookies in any file. If a credential is needed at runtime, reference it via environment variable or `kb.yaml` (which should be gitignored in user projects).
- If raw source material contains personal information or credentials, redact them before compiling into the wiki.
- Never log or echo secrets in bash commands or subagent prompts.

### Internal-confidential lessons — NEVER upload to NotebookLM or any public-facing service

Lessons in the user's KB can mix **personal learning notes** (fine for broadcast) with **employer/internal lessons** (strictly not for broadcast). Internal-confidential content includes:
- Employer or internal product/service names (real or code-named)
- Teammate names, usernames, review/ticket IDs (e.g., `CR-*`, approver handles)
- Internal architectural decisions, deployment topologies, proprietary IP
- Internal tooling names and their implementation details

**Hard rules — all workflows that upload lesson content externally (kb-notebooklm, any future public-facing integration):**

1. **Detect-and-sanitize step is MANDATORY before any upload.** Scan every candidate lesson for internal-confidential markers. If any are found, produce a **sanitized generic variant** that preserves the universal AI/ML teaching content but strips:
   - All employer/product/service/code names (replace with generic equivalents or omit)
   - All teammate names, handles, review/ticket IDs
   - All internal architecture specifics (topologies, deployment choices, file layouts, etc.)
2. **Upload only the sanitized variant.** The raw lesson stays local.
3. **If sanitization would leave nothing of general value, skip the lesson entirely** and report to the user. Do NOT upload a watered-down version that still contains internal details in subtle places.
4. **Defense-in-depth:** the audio-generation prompt must also instruct the model to speak only in generic terms about any proprietary systems, but the primary defense is never sending such lessons to NotebookLM in the first place.

The podcast audience is the general AI/ML community — they should never hear anything about the user's employer, its products, or internal implementations. Leaking internal content via a public podcast is a legal and career risk.

This rule applies to ALL lesson-upload workflows, not just podcasts.

## Documentation

- `docs/CODE_WALKTHROUGH.md` -- Guided tour of the codebase for new contributors.
- `docs/plans/` -- Original design and implementation documents.
- `docs/superpowers/specs/` -- Feature design specs (brainstorming output).
- `docs/superpowers/plans/` -- Feature implementation plans.

## Model Strategy

- Opus orchestrates all workflows.
- Haiku for mechanical scanning tasks.
- Sonnet for article writing and research subagents.
- Always set `model` parameter when dispatching subagents.
