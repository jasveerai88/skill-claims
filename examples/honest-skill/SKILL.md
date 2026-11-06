---
name: honest-skill
description: Formats markdown tables in the files you pass it. Works fully offline, writes nothing, and reads only the files you name.
---

# Honest Formatter

Formats markdown tables so the columns line up, in the
files you name on the command line. The formatted text
prints to the terminal — nothing is written back.

Run [the formatter](scripts/format.py) with one or more
markdown files:

    python3 scripts/format.py draft.md notes.md

## Rules it follows

- It makes no network calls of any kind.
- It never deletes anything.
