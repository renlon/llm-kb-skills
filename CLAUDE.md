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

Single plugin (`kb`) registered via `plugins/kb/.claude-plugin/plugin.json`. Skills are SKILL.md files with YAML frontmatter (name, description, triggers) followed by structured prompts Claude executes verbatim.

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
3. **Check if the plugin is installed locally** by running `claude plugin list 2>/dev/null | grep -q 'kb@llm-kb-skills'`. If installed, run `claude plugin install kb@llm-kb-skills` to upgrade to the new version automatically.

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

## Model Strategy

- Opus orchestrates all workflows.
- Haiku for mechanical scanning tasks.
- Sonnet for article writing and research subagents.
- Always set `model` parameter when dispatching subagents.
