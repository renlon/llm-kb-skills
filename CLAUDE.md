# CLAUDE.md -- Project Instructions

## Project Identity

- LLM Knowledge Base project -- a system of skills for maintaining personal knowledge bases as Obsidian wikis.
- The wiki is the domain of the LLM. Never manually edit wiki articles outside of the kb skill workflows.

## Configuration

- Always read `kb.yaml` at the project root before operating. It contains paths, output format preferences, and Obsidian config.

## Skills

- `kb-init` -- One-time setup to bootstrap a new knowledge base.
- `kb` -- Main operating skill with four workflows: compile, query, lint, evolve.
- `research` -- Initial research outline generation.
- `research-deep` -- Deep research via independent agents per outline item.
- `research-add-fields` -- Add field definitions to an existing research outline.
- `research-add-items` -- Add items (research targets) to an existing research outline.
- `research-report` -- Summarize deep research results into a markdown report.

## Formatting Rules (Obsidian-Compatible)

- `[[wikilinks]]` for all internal links (never markdown-style links).
- `[[wikilinks|display text]]` when the display name differs from the target.
- YAML frontmatter on every article with: title, aliases, tags, article_format, sources.
- `![[image.png]]` for image embeds.

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
