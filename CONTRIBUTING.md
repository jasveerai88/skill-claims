# Contributing

Thanks for looking. skill-claims has a small scope on
purpose: it reads one skill package as static text,
extracts what the package claims and what its scripts
do, and prints a per-claim receipt. Contributions
that keep that scope sharp are welcome.

## Ground rules

- **Standard library only.** No third-party
  dependencies, no network calls, ever. If a change
  seems to need one, it is probably out of scope.
- **Deterministic, always.** No LLM, no randomness,
  no timestamps in the receipt: the same package must
  produce a byte-identical report on every run, on
  every machine. (A past bug — set-ordered token
  variants — was caught by exactly this rule's test.)
- **Read-only, and it executes nothing — always.**
  The audit must never write to a package, and never
  run, import, compile, or decode anything in one.
  Tests prove fixture trees are byte-identical after
  runs and that a booby-trapped script never runs;
  keep them passing.
- **The evidence discipline is the product.** A claim
  is CONTRADICTED only on hard evidence: the
  package's own code doing the ruled-out thing, cited
  file + line. A capability claim is never
  CONTRADICTED, and a quality claim is never anything
  but UNEVIDENCED. A change that flips a claim on
  suspicion or similarity will not be merged.
- **The claim table is the contract.** Every claim
  type and behaviour class lives in SKILL.md's tables
  with its exact evidence basis. A new claim type or
  detector needs: the phrasing patterns, the behaviour
  evidence it rests on, and both directions tested
  (evidence present flips the verdict; absent, it
  does not).
- **Honesty in both directions.** Receipts must say
  what the evidence shows and no more; the limits
  section must keep saying what static analysis
  cannot prove. Never soften a CONTRADICTED verdict's
  wording, and never let a SUPPORTED verdict read as
  "proven honest".
- **Fixtures stay fictional.** Example packages are
  constructed for this repo. Endpoints in dishonest
  fixtures use `.invalid` names — never a real
  domain, never a real credential shape.
- **No tracebacks, ever.** Bad input is a clean
  `{"error": ...}` with exit 2 — including argument
  errors in `--json` mode.

## Running the tests

```bash
python3 -m unittest discover -s tests
```

All tests must pass on a clean checkout with nothing
but Python 3.10+.

## Changing the output

The text receipt and the `--json` schema are both
public surface: scripts and agents consume them.
Keep summary counts recounting exactly against the
claims list, keep claim order deterministic, and
note any schema change in CHANGELOG.md.
