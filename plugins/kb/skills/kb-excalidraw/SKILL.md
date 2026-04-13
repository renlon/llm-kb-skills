---
name: kb-excalidraw
description: "Excalidraw diagram engine. Generates .excalidraw JSON files from structured concept descriptions. Invoked by kb Workflow 5, compile Phase 3.5, and kb-arc. Not directly user-facing."
allowed-tools: Read, Write, Edit, Glob, Bash
---

# kb-excalidraw — Diagram Engine

Shared diagram engine that turns structured input into valid `.excalidraw` files. Three consumers invoke this skill:

- **`/kb diagram`** (Workflow 5) — user requests a diagram for a concept
- **Compile Phase 3.5** — auto-generates diagrams for articles that would benefit from visual explanation
- **`kb-arc`** — generates diagrams for archived session concepts

This skill is NOT user-facing. It receives a structured input contract from the caller and produces a single `.excalidraw` JSON file. No Playwright or browser rendering — diagrams are previewed directly in Obsidian's Excalidraw plugin.

---

## Input Contract

The invoking skill passes a structured prompt with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `concept_name` | string | The concept to visualize (e.g., "Multi-Head Attention") |
| `relationships` | list of strings | Related concepts from the wiki article (e.g., ["Query", "Key", "Value", "Softmax"]) |
| `diagram_type` | string | One of: `workflow`, `architecture`, `hierarchy`, `data_flow`, `comparison` |
| `context` | string | Relevant text excerpt for the engine to visualize |
| `output_path` | string | Target file path (e.g., `wiki/diagrams/attention-mechanism.excalidraw`) |

---

## Process

### Step 1: Read References

Before generating any JSON, read all three reference files:

1. `references/json-schema.md` — element types, properties, binding format
2. `references/element-templates.md` — copy-paste JSON templates for each element type
3. `references/color-palette.md` — the only allowed colors

**Never skip this step.** Never generate JSON from memory alone. The reference files are the single source of truth for valid Excalidraw structure and colors.

### Step 2: Assess Depth

Evaluate complexity based on the input:

| Category | Criteria | Element Count | Strategy |
|----------|----------|---------------|----------|
| **Simple** | 3 or fewer relationships | 10-20 elements | Single-pass JSON generation |
| **Comprehensive** | 4+ relationships | 20-50 elements | Section-by-section build with progressive assembly |

For comprehensive diagrams, plan sections before writing any JSON. Each section gets its own namespace (see Large Diagram Strategy below).

### Step 3: Map Concept to Visual Pattern

Select a visual pattern based on `diagram_type`. The type hint from the caller is a starting point, but **content-driven choice overrides the type hint** if the context clearly suggests a different pattern.

| `diagram_type` | Default Pattern | Visual Structure |
|-----------------|----------------|------------------|
| `workflow` | Timeline | Horizontal line with dots, labels branching off |
| `architecture` | Layered | Stacked horizontal sections with elements inside |
| `hierarchy` | Tree | Lines connecting free-floating text at levels |
| `data_flow` | Assembly line | Input shapes → process shapes → output shapes |
| `comparison` | Side-by-side | Parallel structures with shared axis |

If the context describes a cycle, use Spiral/Cycle regardless of the type hint. If it describes a one-to-many relationship, use Fan-out. Let the content drive the structure.

### Step 4: Design Before JSON

Before writing any JSON, plan the layout on paper (in your reasoning):

1. **Hero element** — What is the single most important concept? It gets the largest shape and the most whitespace.
2. **Flow direction** — Left-to-right for sequences and timelines. Top-to-bottom for hierarchies and architectures.
3. **Shape types** — Assign shapes based on the Shape Meaning Table below. Default to free-floating text unless a shape is semantically meaningful.
4. **Colors** — Assign semantic colors from the palette. Each element gets a color based on what it represents (concept, process, data, decision, external, highlight), not its position.
5. **Grouping** — Identify clusters of related elements. Plan whitespace gaps between clusters.

### Step 5: Generate Excalidraw JSON

Build the complete `.excalidraw` JSON file.

**JSON wrapper** — every file uses this structure:

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "https://excalidraw.com",
  "elements": [
    ...
  ],
  "appState": {
    "viewBackgroundColor": "#ffffff",
    "gridSize": 20
  },
  "files": {}
}
```

**Generation strategy:**

- **Simple diagrams (10-20 elements):** Write the entire JSON in one pass using the Write tool.
- **Comprehensive diagrams (20-50 elements):** Write the initial JSON wrapper and first section with Write. Then use Edit to append additional sections into the `elements` array. Review the whole file after all sections are complete.

**Element ID rules:**

- Use descriptive string IDs: `"attention_rect"`, `"arrow_q_to_k"`, `"label_softmax"` — never numeric IDs like `"1"`, `"2"`, `"3"`
- Text elements bound to shapes: `"text_in_attention_rect"`
- Arrows between elements: `"arrow_SOURCE_to_TARGET"`

**Seed rules:**

- Namespace seeds by section to avoid collisions
- Section 1: seeds in 100xxx range (100001, 100002, ...)
- Section 2: seeds in 200xxx range (200001, 200002, ...)
- Section 3: seeds in 300xxx range, and so on

**Binding rules:**

- When text is inside a shape: the text element must have `"containerId": "parent_shape_id"`, and the parent shape must list `{"id": "text_element_id", "type": "text"}` in its `boundElements` array.
- When an arrow connects two shapes: the arrow must have `startBinding` and `endBinding` referencing the shape IDs, and both shapes must list `{"id": "arrow_id", "type": "arrow"}` in their `boundElements` arrays.
- Arrow `points` must be consistent with `width` and `height`: the last point's coordinates should match `[width, height]`.

### Step 6: Write File

1. Ensure the output directory exists. If `wiki/diagrams/` does not exist, create it:
   ```bash
   mkdir -p wiki/diagrams
   ```

2. Write the `.excalidraw` JSON to `output_path` using the Write tool.

3. Return to the caller. The engine's job is done. The caller is responsible for:
   - Embedding the diagram in a wiki article (`![[diagram-name.excalidraw]]`)
   - Generating an Obsidian URI if needed
   - Logging the operation to `_evolution.md`

---

## Core Philosophy

These principles come from coleam00's diagram skill philosophy and are non-negotiable.

### Diagrams Should ARGUE, Not DISPLAY

A diagram is not a pretty picture of boxes and arrows. It is a visual argument. Every element should exist because it makes a point. Ask: "What claim does this diagram make?" If the answer is "it shows the components of X," that is displaying, not arguing. Instead: "it shows why Q, K, and V projections must happen before attention can be computed" — that is an argument.

### The Isomorphism Test

Remove all text labels from your diagram. Does the structure alone — the shapes, their sizes, positions, connections, and whitespace — still communicate something meaningful? If not, you are using shapes as label holders, not as structural elements. Redesign.

A good diagram encodes meaning in its structure: hierarchy through vertical position, importance through size, sequence through left-to-right flow, grouping through proximity.

### The Education Test

Could someone learn something concrete and non-obvious from this diagram? If the diagram only restates what the text already says in box form, it adds no value. A diagram should reveal relationships, sequences, or hierarchies that are hard to see in prose.

### Container vs Free-Floating Text

**Default to free-floating text.** Less than 30% of text elements should be inside containers (rectangles, ellipses). Typography alone — font size, color, and position — creates hierarchy without boxes.

Use containers only when the shape carries semantic meaning: a rectangle for a process step, an ellipse for an entry point, a diamond for a decision. If you are putting text in a rectangle just to "make it look nice," remove the rectangle.

### Typography as Hierarchy

Font size and color create visual hierarchy without boxes:

| Level | Size | Color | Example |
|-------|------|-------|---------|
| Title | 28px | `#1e40af` | Diagram title |
| Section heading | 20px | `#1e3a5f` | Major sections |
| Body / labels | 16px | `#374151` | Standard labels |
| Detail / annotation | 14px | `#64748b` | Supplementary info |

---

## Visual Pattern Library

Each pattern below includes an ASCII sketch showing the structural idea. When generating Excalidraw JSON, translate these spatial relationships into element positions.

### Fan-Out (One-to-Many)

```
                ┌── B
           ┌────┤
     A ────┤    └── C
           └────── D
```

One source distributes to multiple targets. The source element is on the left, targets fan out to the right. Use when a single concept produces or feeds into multiple downstream concepts. Arrows diverge from the source.

### Convergence (Many-to-One)

```
     A ──────┐
              ├────── D
     B ──────┤
              │
     C ──────┘
```

Multiple inputs combine into a single output. The inverse of fan-out. Use for aggregation, merging, or synthesis. Arrows converge on the target.

### Tree (Hierarchy)

```
              Root
            /      \
         A            B
       /   \        /   \
      C     D      E     F
```

Top-down hierarchy with branching levels. Use structural lines (not arrows) to connect parent and child nodes. Free-floating text at each node. Indent each level further down. Good for taxonomies, class hierarchies, and decompositions.

### Spiral / Cycle (Continuous Loop)

```
        ┌──── A ────┐
        │            │
        D            B
        │            │
        └──── C ────┘
```

Elements arranged in a loop with arrows forming a cycle. No start or end — the cycle is continuous. Use for feedback loops, iterative processes, and recurring patterns. Position elements at roughly equal spacing around an imaginary circle.

### Cloud (Abstract State)

```
        ╭───────────╮
       ╱  overlapping ╲
      │   ellipses     │
       ╲  = fuzzy      ╱
        ╰───────────╯
```

Multiple overlapping ellipses create a cloud-like shape representing an abstract, fuzzy, or emergent concept. Use for latent spaces, probability distributions, or any concept that lacks crisp boundaries. 2-4 overlapping ellipses with low-contrast fills.

### Assembly Line (Transformation / Data Flow)

```
     ┌─────┐      ┌─────┐      ┌─────┐
     │Input│ ───→ │Proc │ ───→ │Output│
     └─────┘      └─────┘      └─────┘
```

Linear left-to-right flow. Input transforms through process stages into output. Each stage is a distinct shape. Arrows connect them sequentially. Good for pipelines, data processing, and forward passes.

### Side-by-Side (Comparison)

```
     ┌──────────┐    ┌──────────┐
     │  Model A  │    │  Model B  │
     ├──────────┤    ├──────────┤
     │  Prop 1   │    │  Prop 1   │
     │  Prop 2   │    │  Prop 2   │
     │  Prop 3   │    │  Prop 3   │
     └──────────┘    └──────────┘
```

Two or more parallel structures sharing the same vertical axis. Properties are aligned horizontally for direct comparison. Use for comparing architectures, approaches, or tradeoffs.

### Gap / Break (Separation)

```
     ┌─────┐                    ┌─────┐
     │  A  │   ~~~~ gap ~~~~    │  B  │
     └─────┘                    └─────┘
```

Extra whitespace (200px+) between groups signals conceptual separation. No line or arrow crosses the gap. Use to show that two parts of a system are independent or loosely coupled.

### Lines as Structure (Timelines, Trees, Dividers)

```
     ●────────●────────●────────●
     │        │        │        │
    2020     2021     2022     2023
```

Lines are not just connectors — they are structural elements. A horizontal line with dots becomes a timeline. Vertical lines become tree branches. Horizontal lines become section dividers. Use `type: "line"` (not arrow) for structural lines.

---

## Shape Meaning Table

| Concept Type | Shape | Why |
|---|---|---|
| Labels, descriptions | none (free-floating text) | Typography creates hierarchy without boxes |
| Timeline markers | small ellipse (12px) | Visual anchor on structural lines |
| Start, trigger, input | ellipse | Soft, origin-like — signals beginning |
| End, output, result | ellipse | Symmetry with start — signals completion |
| Decision, condition | diamond | Classic decision symbol, universally understood |
| Process, action, step | rectangle | Contained action with clear boundaries |
| Abstract state | overlapping ellipses | Fuzzy, cloud-like — no crisp boundary |
| Hierarchy node | lines + text | Structure through lines, not boxes |
| Group boundary | frame | Lightweight grouping when needed |

**Default:** If unsure which shape to use, use free-floating text. Only add a shape when the shape itself carries meaning.

---

## Layout Principles

### Size Hierarchy

| Role | Width x Height | Whitespace Around |
|------|---------------|-------------------|
| Hero (central concept) | 300 x 150 | 200px+ on all sides |
| Primary (main supporting) | 180 x 90 | 100px between elements |
| Secondary (supporting) | 120 x 60 | 80px between elements |
| Small (annotations, dots) | 60 x 40 or 12 x 12 | 60px minimum gap |

### Spacing Rules

- **Minimum gap** between any two elements: 60px
- **Hero whitespace**: 200px+ clear space around the hero element
- **Section gap**: 150px between distinct sections of a comprehensive diagram
- **Grid alignment**: Position elements on a 20px grid (`gridSize: 20` in appState)

### Flow Direction

- **Left to right** for sequences, timelines, data flows, pipelines
- **Top to bottom** for hierarchies, architectures, layer stacks
- **Circular** for cycles and feedback loops

### Default Element Properties

All elements use these defaults unless there is a specific reason to deviate:

| Property | Value | Reason |
|----------|-------|--------|
| `roughness` | `0` | Clean, precise lines — not hand-drawn |
| `opacity` | `100` | Full opacity — no translucent elements |
| `fontFamily` | `3` | Monospace — consistent character width |
| `fillStyle` | `"solid"` | Clean fill — no hachure or cross-hatch |
| `strokeWidth` | `2` | Visible but not heavy (1 for text, 2 for shapes) |
| `roundness` | `{"type": 3}` | Rounded corners on rectangles |

---

## Large Diagram Strategy

For comprehensive diagrams (20-50 elements), generate JSON section-by-section to maintain accuracy and avoid malformed JSON.

### Process

1. **Plan sections** — Divide the diagram into 2-5 logical sections. Each section is a spatial cluster of related elements.

2. **Assign seed namespaces** — Each section gets a unique seed range:
   - Section 1: 100001, 100002, 100003, ...
   - Section 2: 200001, 200002, 200003, ...
   - Section 3: 300001, 300002, 300003, ...

3. **Use descriptive string IDs** — Every element gets a human-readable ID:
   - Shapes: `"encoder_rect"`, `"decoder_rect"`
   - Text: `"text_in_encoder_rect"`, `"label_attention"`
   - Arrows: `"arrow_encoder_to_decoder"`
   - Lines: `"line_timeline_main"`
   - Dots: `"dot_epoch_1"`

4. **Write first section** — Use the Write tool to create the file with the full JSON wrapper and the first section's elements.

5. **Append remaining sections** — Use the Edit tool to insert additional elements before the closing `]` of the elements array. Each edit adds one section.

6. **Add cross-section bindings** — After all sections are written, use Edit to update `boundElements`, `startBinding`, and `endBinding` for arrows that cross section boundaries.

7. **Review** — Read the complete file. Verify:
   - Valid JSON (no trailing commas, correct brackets)
   - All `containerId` references point to existing shape IDs
   - All `boundElements` entries reference existing element IDs
   - Arrow `points` last coordinate matches `[width, height]`
   - All colors come from the palette

---

## Text Rules

Text elements have strict requirements for Excalidraw compatibility:

1. **`text` and `originalText` must match exactly** — both fields contain the same readable string. Never put JSON, IDs, or metadata in these fields.

2. **Default text properties:**
   ```json
   "fontSize": 16,
   "fontFamily": 3,
   "textAlign": "center",
   "verticalAlign": "middle",
   "lineHeight": 1.25
   ```

3. **Text inside containers:**
   - Set `"containerId": "parent_shape_id"` on the text element
   - Set `"textAlign": "center"` and `"verticalAlign": "middle"`
   - The parent shape must include `{"id": "text_id", "type": "text"}` in its `boundElements`

4. **Free-floating text:**
   - Set `"containerId": null`
   - Set `"textAlign": "left"` and `"verticalAlign": "top"`
   - Adjust `fontSize` and `strokeColor` based on the Text Colors hierarchy from the palette

5. **Width estimation:** Approximate width as `fontSize * 0.6 * character_count`. Height is `fontSize * lineHeight * line_count`.

---

## Color Rules

**All colors must come from `references/color-palette.md`.** Never invent, interpolate, or hardcode colors.

### Semantic Color Assignment

Each element receives colors based on what it represents, not where it sits in the diagram:

| Element represents... | Fill | Stroke |
|----------------------|------|--------|
| A wiki concept or definition | `#dbeafe` | `#1e40af` |
| A process, action, or step | `#dcfce7` | `#166534` |
| Data, input, or output | `#ffedd5` | `#c2410c` |
| A decision or condition | `#fef3c7` | `#b45309` |
| An external system or API | `#f3e8ff` | `#7c3aed` |
| A warning, error, or key point | `#fecaca` | `#dc2626` |

### Arrow and Line Colors

- **Arrows** inherit the stroke color of their source element
- **Structural lines** use `#64748b` (slate)
- **Marker dots** use `#3b82f6` for both fill and stroke

### Text Colors

- **Title:** `#1e40af` at 28px
- **Heading:** `#1e3a5f` at 20px
- **Body:** `#374151` at 16px
- **Detail:** `#64748b` at 14px
- **Inside light shapes:** `#374151`
- **Inside dark shapes:** `#ffffff`

### Canvas Background

Always `#ffffff`. Set in `appState.viewBackgroundColor`.

---

## Output Contract

The engine writes the `.excalidraw` file to `output_path` and returns. That is its only responsibility.

**The caller is responsible for:**
- Embedding the diagram in the wiki article: `![[diagram-name.excalidraw]]`
- Creating an Obsidian URI link if needed
- Logging the operation to `wiki/_evolution.md`
- Updating `wiki/_sources.md` if the diagram was generated during compile

**The engine returns:** nothing beyond completing the file write. If an error occurs (invalid input, missing output directory despite mkdir), report the error to the caller.

---

## Common Mistakes

These are the most frequent errors when generating Excalidraw JSON. Check every diagram against this list before writing the file.

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Generating JSON without reading reference files first | Wrong property names, missing fields, invalid structure | Always execute Step 1 before any JSON generation |
| Using `roughness: 1` or `roughness: 2` | Hand-drawn look, inconsistent with KB style | Always set `roughness: 0` |
| Setting `opacity` less than 100 | Translucent elements look broken in Obsidian | Always set `opacity: 100` |
| Putting every text element in a container | Cluttered, box-heavy diagram that fails the Isomorphism Test | Default to free-floating text; < 30% in containers |
| Using numeric IDs (`"1"`, `"2"`, `"3"`) | Impossible to debug bindings, collisions across sections | Use descriptive string IDs (`"attention_rect"`, `"arrow_q_to_k"`) |
| Forgetting `originalText` on text elements | Excalidraw may not render the text | Always set `originalText` = `text` |
| Forgetting `containerId` on text inside shapes | Text floats independently instead of anchoring to shape | Set `containerId` to the parent shape's ID |
| Forgetting text element ID in parent shape's `boundElements` | Shape does not know it has text; editing shape may orphan text | Add `{"id": "text_id", "type": "text"}` to parent's `boundElements` |
| Arrow `points` not matching `width`/`height` | Arrow renders at wrong angle or length | Last point in `points` array must equal `[width, height]` |
| Inventing colors not in the palette | Visual inconsistency across diagrams | Only use colors from `references/color-palette.md` |
| Trailing commas in JSON | Invalid JSON, file will not load | Verify JSON structure before writing |
| Missing `boundElements` on shapes connected by arrows | Arrows may not track shape movement in Excalidraw editor | Both source and target shapes must list the arrow in `boundElements` |
