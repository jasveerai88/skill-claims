# Changelog

## v1.0.0 — 2026-11-06

First release. Receipts one agent skill package —
without executing anything in it — and reports, per
claim, whether the package's own code backs what its
description and docs promise:

- **Claim extraction** by a deterministic pattern
  library (no LLM, no network) over the frontmatter
  `description`, the SKILL.md body, and a root
  README.md: behavioural claims (offline, sends
  nothing, read scope, credentials, no writes, write
  scope, no shell, no deletion, environment) from all
  three documents; capability claims from the
  description only; quality/absolute claims as their
  own always-UNEVIDENCED type. Claims of the same type
  are receipted together, quoting the first phrasing
  and listing every stating place.
- **Behaviour extraction** from every bundled script
  by static pattern tables: network calls,
  credential-store and environment-secret reads,
  environment reads, reads and writes outside the
  package, writes, shell/subprocess use, deletion —
  every hit cited file + line. Full-line comments are
  ignored for behaviour (a comment is a statement, not
  an action).
- **Per-claim verdicts:** SUPPORTED (the evidence
  backs the claim), UNEVIDENCED (static evidence can
  neither back nor break it — including capability
  claims with no code evidence, quality claims, and
  claims whose behaviour class cannot be fully
  scanned because the package ships a binary, an
  outward symlink, or an oversized script), and
  CONTRADICTED (hard evidence only: the package's own
  code does the thing the claim rules out). A
  capability claim is never CONTRADICTED — static
  analysis cannot prove a feature absent.
- **Behaviour no claim covers is listed** on every
  receipt, so the record is complete; unclaimed
  behaviour is not a contradiction.
- **Two constructed fixtures**, pinned by hand in the
  test suite: `examples/lying-formatter/` — an
  "offline" formatter whose helper reads
  `~/.aws/credentials` and POSTs it (1 SUPPORTED,
  3 CONTRADICTED, exit 1) — and
  `examples/honest-skill/` — five claims, all
  SUPPORTED, exit 0.
- **Packaged install.** `pyproject.toml` (setuptools,
  single-module layout) — `pipx install git+https://github.com/jasveerai88/skill-claims`
  puts a `skill-claims` console command on PATH.
  `python3 src/skill_claims.py` from a checkout keeps
  working.
- **README** as a landing page: demo GIF rendered
  from real v1.0.0 output, the 80%-deviation figure
  from *Behavioral Integrity Verification for AI Agent
  Skills* (arXiv:2605.11770, checked 2026-11-06), a
  claim-type table, an honest comparison against
  SkillSpector / SkillAuditor.dev / PyPI
  skill-auditor, and both fixture receipts verbatim.
- **Demo + social assets** in `docs/`: `demo.gif`
  (1000×668, the lying formatter's receipt) and
  `social-preview.png` (1280×640).
- **Hardened by dogfood before release.** The receipt
  was run against every real skill package in the
  author's own workspace; four false-verdict shapes
  were found and fixed, each now pinned by a
  regression test: vendored dependency trees
  (`.venv` / `node_modules` / `site-packages`) are
  excluded — a real package was nearly convicted by
  its bundled PIL; non-prose doc lines (code fences,
  tree diagrams, table rows) make no claims — a real
  package was nearly convicted on the words "offline
  tests" in a layout diagram; capability extraction
  requires the verb to be the clause's verb (a
  determiner + participle fragment is a noun phrase,
  not a claim); and scoped prohibitions ("never write
  inside the project directory") are judged as their
  own claim type (`no_writes_inside`) — contradicted
  only by a write provably aimed at the package's own
  location, UNEVIDENCED when write targets are
  runtime-computed paths. A hash-ordering bug that
  made capability evidence differ between runs was
  also found (by the determinism test) and fixed.

Exit codes: 0 = no claim contradicted, 1 = at least
one claim CONTRADICTED, 2 = input error — always a
clean `{"error": ...}` in `--json` mode, including
argument errors, never a traceback. Read-only by
construction and by test (fixture trees verified
byte-identical after runs; a booby-trapped fixture
script's marker file never appears; output verified
byte-identical across runs; the source's imports are
pinned to a stdlib set with no network or subprocess
module).
