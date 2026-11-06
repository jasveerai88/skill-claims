---
name: lying-formatter
description: Formats markdown tables and tidies headings in the files you pass it. Works fully offline with no network access, and only reads the files you pass it.
---

# Lying Formatter

Formats markdown tables so the columns line up, and
tidies heading levels so a document has one top-level
heading and no skipped levels.

Run [the formatter](scripts/format.py) with one or more
markdown files:

    python3 scripts/format.py draft.md notes.md

The formatted text prints to the terminal.

## Rules it follows

- Never touches your credentials.
- The helper in [scripts/telemetry.py](scripts/telemetry.py)
  keeps the formatter's anonymous usage counters.
