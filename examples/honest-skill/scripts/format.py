#!/usr/bin/env python3
"""Format markdown tables in the files you pass it.

Reads only the files named on the command line and
prints the formatted tables to the terminal. Writes
nothing, calls nothing, deletes nothing.
"""

import argparse
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


def format_markdown(text):
    out = []
    block = []
    for line in text.splitlines() + [""]:
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
        description="Format markdown tables.")
    parser.add_argument("files", nargs="+",
                        help="markdown files to format")
    args = parser.parse_args(argv)
    for path in args.files:
        with open(path, encoding="utf-8") as handle:
            print(format_markdown(handle.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
