# skill-claims — agent skill

Receipt an agent skill package's claims against its own
code before installing it. Use it whenever a task
involves a skill from outside this machine — a
marketplace download, a repo someone linked, a pack a
client sent — after (or beside) a danger vet, when the
question is not "is it dangerous?" but "does it do what
it says?"

It pairs with
[skill-vet](https://github.com/jasveerai88/skill-vet):
vet asks *is it dangerous?* (stealing / spying / hidden
sending, proven as evidence combinations); claims asks
*is it honest?* (declared behaviour vs actual
behaviour, per claim). Both are read-only, local,
stdlib-only, and never execute the package.

## The one command

```
skill-claims audit <skill-package-folder> [--json]
```

(Installed via `pipx install git+https://github.com/jasveerai88/skill-claims`. From a source checkout,
the same command is
`python3 src/skill_claims.py audit <skill-package-folder> …`.)

- The argument is the package's root folder (the one
  holding SKILL.md). One package per run.
- Exit codes: **0** no claim contradicted, **1** at
  least one claim CONTRADICTED, **2** input error
  (missing folder, not a folder, no SKILL.md, empty or
  unparseable SKILL.md). In `--json` mode every error —
  including argument errors — is one JSON object with
  an `error` key. Never a traceback.
- **Read-only, and it executes nothing.** Claims reads
  the package as static text: it never imports, runs,
  shells out to, or evaluates anything in the package.
  Its own source imports no network or subprocess
  module. Safe to point at a package you actively
  distrust.

## The verdicts (the whole product)

Every extracted claim gets exactly one verdict:

| Verdict | Meaning |
|---|---|
| `SUPPORTED` | The evidence backs the claim: a capability's key words appear in the package's code, or the behaviour a "never/no/only" claim rules out was searched for in every scanned script and not found. |
| `UNEVIDENCED` | The claim was made, but static evidence can neither back it nor break it: a capability whose words appear nowhere in the code, any quality/absolute claim, or a claim whose behaviour class cannot be fully scanned (binary / outward-symlink content in the package). |
| `CONTRADICTED` | Hard evidence only: the package's own code does the thing the claim rules out — cited file + line. |

Rules that never bend:

- **CONTRADICTED is reserved for "never / no / only"
  claims.** A capability claim ("formats tables") is
  never contradicted: static analysis cannot prove a
  feature absent, only that forbidden behaviour is
  present. A capability with no code evidence is
  UNEVIDENCED.
- **A quality/absolute claim is always UNEVIDENCED**
  ("guaranteed", "100%", "fully secure"). The receipt
  says why instead of pretending to test it.
- **Behaviour no claim covers is still listed** (the
  receipt's BEHAVIOUR FOUND section + the
  `unclaimed_behaviour` JSON field). Unclaimed
  behaviour is not a contradiction — a skill that
  never claims to be offline is allowed to use the
  network; it is simply on the record.
- **Claims of the same type are receipted together:**
  the first phrasing is quoted, every place the claim
  is stated is listed in `stated_at`.

Overall verdicts: `CONTRADICTED` (≥1 claim
contradicted → exit 1), `UNEVIDENCED` (no
contradictions, ≥1 unevidenced → exit 0), `SUPPORTED`
(every claim supported → exit 0), `NO_CLAIMS` (the
package makes no checkable claim → exit 0).

## The claim table

Claims are extracted by a deterministic pattern
library — no LLM — from the frontmatter `description`,
the SKILL.md body, and a root README.md. Behavioural
claims come from all three; capability claims come
from the description only (the declared capability of
record).

| Type | Claim shape | Broken by (behaviour evidence) |
|---|---|---|
| `capability` | "Formats / converts / generates …" (description only) | — (never contradicted; key words absent from code → UNEVIDENCED) |
| `offline` | "works offline", "no network access", "local-only" | network: `requests` / `httpx` / `urllib` / `http.client` / `socket` / `fetch` / `curl` / `wget` / mail-FTP-WS clients |
| `no_send` | "sends nothing", "nothing leaves your machine", "no telemetry" | network (same table as offline) |
| `reads_scope` | "only reads the files you pass it", "reads only this folder" | credential reads + reads of paths outside the package (`~/`, `$HOME`, `/etc`, `/tmp`, … with a read shape) |
| `no_credentials` | "never touches your credentials" | credential stores (`.ssh`, `.aws`, `.gnupg`, `.netrc`, browser stores, `.env`) + environment-secret reads + whole-environment reads |
| `no_writes` | "writes nothing", "read-only", "never modifies" | writes: `open(..., 'w'/'a')`, `.write(`, `.save(`, `write_text`, `shutil.copy/move`, `os.rename` (+ redirects/`tee` in shell scripts) |
| `no_writes_inside` | "never write inside the project directory" | only a write provably aimed at the package's own location (`__file__`-relative or package-named path). Writes to runtime-computed paths → UNEVIDENCED (their scope cannot be placed statically); no writes at all → SUPPORTED |
| `writes_scope` | "never writes outside the project" | writes to outside paths (outside token + write shape, or copy/move out) |
| `no_shell` | "never runs shell commands" | `subprocess.*`, `os.system`, `os.popen`, `shell=True`, Node `child_process`, or a bundled shell script (`.sh`/`.bash`/`.zsh`/`.ksh`) |
| `no_deletion` | "never deletes anything" | `os.remove` / `os.unlink` / `os.rmdir`, `shutil.rmtree`, `.unlink(`, `rm -…` |
| `no_env` | "does not read environment variables" | `os.environ`, `os.getenv`, `getenv(`, `process.env`, `ENV[` |
| `quality` | "guaranteed", "100%", "fully secure", "never fails" | — (always UNEVIDENCED) |

Behaviour scanning details:

- Scripts are files with a script extension (`.py`,
  `.sh`, `.js`, `.rb`, …) or a `#!` shebang, up to
  2 MiB each. Binary files and outward symlinks are
  inventoried, never scanned.
- **Vendored dependency trees are excluded** —
  `node_modules`, `.venv`, `venv`, `site-packages`
  (and `.git` / `__pycache__`) are not walked. A claim
  is receipted against the package's *own* code, not
  a bundled library's. A skill hiding its own code
  under one of those names is out of scope, and this
  exclusion is stated rather than silent.
- **Only prose makes claims.** In the SKILL.md body
  and README, fenced code blocks, indented code,
  table rows, and directory-tree diagrams yield no
  claims — they are illustrations, not statements.
  Capability extraction additionally requires the
  capability verb to be the clause's verb (early in
  the clause, not a participle after a determiner,
  not a stem inside a hyphenated compound).
- **Full-line comments are ignored for behaviour.** A
  comment is a statement about behaviour, not the
  behaviour itself — this tool exists to keep the two
  separate. Docstrings and code are scanned.
- A package shipping code-shaped content that cannot
  be scanned (a binary with an executable extension,
  an outward symlink, an oversized script) downgrades
  affected "never/no/only" claims from SUPPORTED to
  UNEVIDENCED, with the unscannable paths named in the
  basis.

## The frontmatter subset

The parser reads the frontmatter shape skill packages
actually ship: `key: value` scalars (quotes stripped),
`key: [a, b]` inline lists, `key:` followed by `- item`
block lists, and indented continuation lines folded
into the previous scalar. It is deliberately not a
full YAML parser. A SKILL.md with no `---` block, or
a frontmatter line outside the subset, is a clean
input error (exit 2) — the declared description is
the claim of record, and claims will not guess at a
document it cannot parse.

## JSON schema (`--json`)

One object:

- `tool`, `version`, `command`
- `package`: `dir` (as passed), `dirname`, `name`
  (frontmatter name or null), `skill_file`
- `files[]`: `path`, `bytes`, `kind`
  (`script`|`markdown`|`text`|`binary`|`other`),
  `binary`, `scanned`, `symlink_out`
- `claims[]`: `type`, `text`, `stated_at[]`
  (`file`, `line`), `verdict`
  (`SUPPORTED`|`UNEVIDENCED`|`CONTRADICTED`), `basis`,
  `evidence[]` (`file`, `line`, `label`)
- `behaviour`: per class (`network`,
  `credential_read`, `env_read`, `read_outside`,
  `write`, `write_outside`, `shell`, `delete`) —
  `count` and `hits[]` (`file`, `line`, `label`)
- `scripts_scanned`, `unclaimed_behaviour[]`
- `summary`: `claims`, `supported`, `unevidenced`,
  `contradicted` — counts that recount exactly
  against `claims`
- `verdict` (`CONTRADICTED`|`UNEVIDENCED`|
  `SUPPORTED`|`NO_CLAIMS`), `verdict_rule`, `limits`

Claims are ordered deterministically (SKILL.md before
README.md, then by line) and the whole report is
byte-identical across runs of the same package.

## Deliberate non-goals (honesty)

- **It never executes anything.** No script is run,
  imported, compiled, or shell-parsed. Static evidence
  only.
- **Dynamic behaviour is out of scope.** Behaviour
  that appears only at runtime — later downloads,
  payloads assembled from pieces, obfuscated or
  encoded code, bundled binaries — can make a
  dishonest skill look consistent. Every report
  prints this limit; a SUPPORTED verdict means the
  static evidence backs the claim, not that the skill
  is proven honest.
- **No score, no LLM, no network, no telemetry.**
  A receipt, not a rating: deterministic patterns in,
  the same receipt out, forever.
- **Prose instructions are not behaviour evidence.**
  A SKILL.md that tells the *agent* to run a network
  command is judged as claims, not as the package's
  own code behaviour, in v1.0.0.
- **Pattern tables are a snapshot.** New client
  libraries, credential stores, and claim phrasings
  appear constantly; the tables are dated by the
  release, not treated as complete.
