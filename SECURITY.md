# Security

## skill-claims' own posture

skill-claims is itself an audit tool, and its own attack surface is
deliberately minimal:

- **No network code, no subprocess code.** The source imports
  only `argparse`, `json`, `os`, `re` and `sys` — a test parses
  its imports and pins that set. It cannot phone home because
  it has no way to.
- **It never executes what it scans.** No package file is run,
  imported, compiled, or decoded; everything is read as static
  text. Pointing skill-claims at a hostile package is safe by
  construction, and the test suite proves it (a booby-trapped
  fixture's marker file never appears; fixture trees are
  byte-identical after a run).
- **No dependencies.** Python 3.10+ standard library only —
  there is no supply chain beyond Python itself.

## Reporting a problem

If you find a way to make skill-claims execute package content, write
outside its read-only behaviour, or crash with a traceback on
malformed input, please report it privately through GitHub's
"Report a vulnerability" flow on this repository (Security →
Advisories), rather than a public issue. A minimal fixture package
that reproduces the problem is the most helpful thing you can
include — keep any dishonest fixture fictional (`.invalid`
endpoints, no real credentials), as the shipped examples do.

If skill-claims *misjudges* a package — a claim it fails to
extract, a verdict the cited evidence does not support — that is
a correctness bug, not a vulnerability: open a regular issue
with the package or a minimal fixture.

## Supported versions

Only the latest release is supported. Fixes land in a new
release, never as silent edits to an existing one.
