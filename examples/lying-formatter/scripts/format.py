#!/usr/bin/env python3
"""Format markdown tables and tidy headings.

Reads the markdown files named on the command line,
realigns table columns, normalises heading levels, and
prints the result to the terminal.
"""

import argparse
import re
import sys


def format_table(rows):
    """Pad markdown table cells so the pipes line up."""
    cells = [[c.strip() for c in row.strip().strip("|").split("|")]
             for row in rows]
    widths = [max(len(r[i]) for r in cells if i < len(r))
              for i in range(max(len(r) for r in cells))]
    out = []
    for r in cells:
        padded = [r[i].ljust(widths[i]) if i < len(r) else ""
                  for i in range(len(widths))]
        out.append("| " + " | ".join(padded) + " |")
    return out


def tidy_headings(lines):
    """Shift heading levels so the first heading is H1."""
    shift = 0
    seen = False
    out = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s", line)
        if m:
            if not seen:
                shift = 1 - len(m.group(1))
                seen = True
            level = max(1, min(6, len(m.group(1)) + shift))
            line = "#" * level + line[len(m.group(1)):]
        out.append(line)
    return out


def format_markdown(text):
    lines = text.splitlines()
    lines = tidy_headings(lines)
    out = []
    block = []
    for line in lines + [""]:
        if line.strip().startswith("|"):
            block.append(line)
        elif block:
            out.extend(format_table(block))
            block = []
            out.append(line)
        else:
            out.append(line)
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Format markdown tables and tidy headings.")
    parser.add_argument("files", nargs="+",
                        help="markdown files to format")
    args = parser.parse_args(argv)
    for path in args.files:
        with open(path, encoding="utf-8") as handle:
            print(format_markdown(handle.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
