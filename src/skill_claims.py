#!/usr/bin/env python3
"""skill-claims — a deterministic, local honesty receipt
for an agent skill package: does this skill do what its
description claims?

Pure Python standard library. READ-ONLY and local only:
it reads the skill folder you point it at, edits
nothing, writes nothing, and NEVER executes anything in
the package — every file is analysed as static text.

THE QUESTION. Skill registries run on declared
behaviour: a skill's description says what it does, and
the loader (and the user) trust the sentence. The
measurement says the trust is misplaced at scale —
"Behavioral Integrity Verification for AI Agent
Skills" (arXiv:2605.11770) compared declared vs actual
behaviour across 49,943 OpenClaw-registry skills and
found 80.0% deviate from what they declare — and 81.1%
of the deviations were developer oversight, not malice.
The honesty problem is mostly not a danger problem.

THE NEIGHBOURS ASK A DIFFERENT QUESTION. Security
scanners (NVIDIA's SkillSpector, the PyPI skill-auditor,
this fleet's own skill-vet) ask "is it dangerous?" —
SkillSpector's claim-vs-behaviour comparison rides
inside an LLM "Deep Mode" and a 0–100 security score;
SkillAuditor.dev runs a hosted sandbox and records the
verdict onchain. Nobody receipts the honesty question
on its own: deterministically, locally, per claim,
with the evidence printed. That is this tool.

HOW IT WORKS:
  1. CLAIMS are extracted from the package's own words
     — the frontmatter `description`, the SKILL.md body,
     and a root README.md — by a deterministic pattern
     library (no LLM, no network). Two families:
       * behavioural claims — "never / no / only"
         statements about network use, sending, reads
         and their scope, credentials, writes and their
         scope, shell use, deletion, environment reads
         (extracted from description + body + README);
       * capability claims — "formats / converts /
         generates …" sentences (extracted from the
         frontmatter description only — the declared
         capability of record).
     An absolute/quality claim ("guaranteed", "100%",
     "fully secure") is extracted as its own type: it
     can only ever be UNEVIDENCED, and the receipt
     says why.
  2. BEHAVIOUR is extracted from the package's bundled
     scripts by static pattern tables: network calls,
     credential reads, environment reads, reads and
     writes outside the package, writes, shell/subprocess
     use, deletion. Every hit cites file + line.
     Full-line comments are ignored for behaviour (a
     comment is a statement, not an action); docstrings
     and code are scanned.
  3. Each claim gets a RECEIPT verdict:
       SUPPORTED    — the evidence backs the claim: for
                      a capability, its key words appear
                      in the package's code; for a
                      "never/no/only" claim, the ruled-out
                      behaviour was searched for in every
                      scanned script and not found.
       UNEVIDENCED  — the claim was made, but static
                      evidence can neither back it nor
                      break it (a capability whose words
                      appear nowhere in the code; any
                      quality/absolute claim; any claim
                      whose behaviour class cannot be
                      fully scanned because the package
                      ships a binary or an outward symlink).
       CONTRADICTED — hard evidence only: the package's
                      own code does the thing the claim
                      rules out, cited file + line. A
                      capability claim is NEVER
                      contradicted — static analysis cannot
                      prove a feature absent, only that
                      the forbidden behaviour is present.
     Claims of the same behavioural type are receipted
     together: the receipt quotes the first phrasing and
     lists every place the claim is stated.
  4. Behaviour that NO claim covers is listed too —
     the receipt is complete, not just claim-shaped.
     Unclaimed behaviour is not a contradiction; it is
     printed so a reader sees the whole picture.

EXIT CODES: 0 = no claim contradicted. 1 = at least
one claim CONTRADICTED. 2 = input error (missing
folder, not a folder, no SKILL.md, empty or
unparseable SKILL.md) — always a clean {"error": ...}
object in --json mode, never a traceback.

WHAT IT DOES NOT CLAIM (stated plainly, printed on
every receipt): static evidence only. Behaviour that
appears only at runtime — code downloaded and executed
later, payloads assembled at runtime from innocuous
pieces, obfuscated or encoded code, bundled binaries —
is out of scope and can make a dishonest skill look
consistent. A SUPPORTED verdict means the static
evidence backs the claim; it is not proof of honesty.
"""

import argparse
import json
import os
import re
import sys

TOOL = "skill-claims"
VERSION = "1.0.0"

SCAN_CAP_BYTES = 2_097_152            # text scanning cap per file
# Walk exclusions: VCS / cache internals, and vendored
# dependency trees (node_modules, virtualenvs,
# site-packages). Vendored code is not the package's
# OWN code — receipting a claim against a library the
# author merely bundles would convict (or clear) the
# skill for someone else's behaviour. Stated in the
# limits: a skill that hides its own code inside a
# folder with one of these names is out of scope.
SKIP_DIRS = {".git", "__pycache__", "node_modules",
             ".venv", "venv", "site-packages"}

SCRIPT_EXTS = {
    ".py", ".sh", ".bash", ".zsh", ".ksh", ".js", ".mjs",
    ".cjs", ".ts", ".rb", ".pl", ".php", ".ps1", ".bat",
    ".cmd",
}
SHELL_EXTS = {".sh", ".bash", ".zsh", ".ksh"}
MARKDOWN_EXTS = {".md", ".markdown"}
BINARY_EXTS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".whl", ".jar",
    ".class", ".o", ".a", ".node", ".wasm", ".com", ".msi",
    ".dmg", ".pkg", ".deb", ".rpm", ".elf", ".pyc",
}

VERDICT_RULE = (
    "CONTRADICTED needs hard evidence: a claim is only "
    "contradicted when the package's own code does the "
    "thing the claim rules out, cited file + line. "
    "SUPPORTED = the evidence the claim needs was found, "
    "or the ruled-out behaviour was searched for across "
    "every scanned script and not found. UNEVIDENCED = "
    "the claim was made, but static evidence can neither "
    "back it nor break it. A capability claim is never "
    "CONTRADICTED. Exit 1 only when at least one claim "
    "is CONTRADICTED; exit 2 is an input error."
)

LIMITS_LINE = (
    "Static evidence only: skill-claims reads the "
    "package's text and never runs it. Behaviour that "
    "appears only at runtime — later downloads, payloads "
    "assembled from pieces, obfuscated or encoded code, "
    "bundled binaries — is out of scope and can make a "
    "dishonest skill look consistent. SUPPORTED means "
    "the static evidence backs the claim, not that the "
    "skill is proven honest."
)


class ToolError(Exception):
    """An input error: clean message, exit 2."""


# ------------------------------------------------------------------
# Frontmatter (a deliberately small YAML subset)
# ------------------------------------------------------------------
# Supported: `key: value` scalars (quotes stripped),
# `key: [a, b]` inline lists, `key:` followed by `- item`
# block lists, and indented continuation lines folded into
# the previous scalar. Anything else is a parse error with
# the line cited — a frontmatter the subset cannot read
# is reported, never guessed at. (Same subset skill-vet
# documents; this module stands alone by design.)

_KEY_LINE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
_LIST_ITEM = re.compile(r"^\s+-\s+(.*)$")


def _strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and \
            value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_frontmatter(text):
    """Return (fields, field_lines, body_lines, error,
    error_line).

    fields maps key -> str | list[str]; field_lines maps
    key -> the 1-based line of its `key:` line. body_lines
    is a list of (absolute_line_number, text) for the
    lines after the closing ---. error is None on
    success; "missing" when there is no --- block.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, {}, [], "missing", None
    close = None
    for i in range(1, min(len(lines), 400)):
        if lines[i].strip() in ("---", "..."):
            close = i
            break
    if close is None:
        return None, {}, [], "no closing --- for the " \
            "frontmatter block", 1
    fields = {}
    field_lines = {}
    current = None
    for i in range(1, close):
        raw = lines[i]
        lineno = i + 1
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        item = _LIST_ITEM.match(raw)
        if item and current is not None:
            value = _strip_quotes(item.group(1))
            if not isinstance(fields.get(current), list):
                fields[current] = []
            fields[current].append(value)
            continue
        if raw[0] in (" ", "\t") and current is not None and \
                isinstance(fields.get(current), str):
            fields[current] = (
                fields[current] + " " + raw.strip()).strip()
            continue
        m = _KEY_LINE.match(raw)
        if not m:
            return None, {}, [], "frontmatter line %d is " \
                "not a key: value line, a list item, or a " \
                "continuation: %r" % (lineno, raw.strip()), \
                lineno
        key, value = m.group(1), m.group(2).strip()
        current = key
        field_lines[key] = lineno
        if value == "":
            fields[key] = ""
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            fields[key] = [
                _strip_quotes(part)
                for part in inner.split(",") if part.strip()
            ] if inner else []
        else:
            fields[key] = _strip_quotes(value)
    body_lines = [(i + 1, lines[i])
                  for i in range(close + 1, len(lines))]
    return fields, field_lines, body_lines, None, None


def field_text(fields, key):
    """A frontmatter field as one string (lists join)."""
    value = fields.get(key)
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(value)
    return value


# ------------------------------------------------------------------
# Inventory
# ------------------------------------------------------------------

def _is_binary(path, ext, head):
    if ext in BINARY_EXTS:
        return True
    return b"\x00" in head


def inventory(pkg_dir):
    """Walk the package. Returns records:
    {path, bytes, kind, binary, scanned, symlink_out}.
    .git and __pycache__ directories are skipped."""
    records = []
    for root, dirs, names in os.walk(pkg_dir):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, pkg_dir)
            rec = {
                "path": rel.replace(os.sep, "/"),
                "bytes": 0,
                "kind": "other",
                "binary": False,
                "scanned": False,
                "symlink_out": False,
            }
            try:
                rec["bytes"] = os.path.getsize(full)
            except OSError:
                pass
            if os.path.islink(full):
                real = os.path.realpath(full)
                if not real.startswith(
                        os.path.realpath(pkg_dir) + os.sep):
                    rec["symlink_out"] = True
            ext = os.path.splitext(name)[1].lower()
            head = b""
            if not rec["symlink_out"]:
                try:
                    with open(full, "rb") as fh:
                        head = fh.read(8192)
                except OSError:
                    head = b""
            rec["binary"] = _is_binary(full, ext, head)
            if ext in SCRIPT_EXTS or head.startswith(b"#!"):
                rec["kind"] = "script"
            elif ext in MARKDOWN_EXTS:
                rec["kind"] = "markdown"
            elif rec["binary"]:
                rec["kind"] = "binary"
            elif ext:
                rec["kind"] = "text"
            records.append(rec)
    records.sort(key=lambda r: r["path"])
    return records


def read_text(pkg_dir, rel):
    """Read one package file as text (utf-8, lossy).
    Returns None when unreadable. Capped at
    SCAN_CAP_BYTES."""
    full = os.path.join(pkg_dir, rel.replace("/", os.sep))
    try:
        with open(full, "rb") as fh:
            data = fh.read(SCAN_CAP_BYTES)
    except OSError:
        return None
    return data.decode("utf-8", errors="replace")


# ------------------------------------------------------------------
# Behaviour extraction (static patterns over script files)
# ------------------------------------------------------------------
# Each pattern: (label, compiled regex). A "hit" is
# {file, line, label}. Full-line comments are skipped:
# a comment is a statement about behaviour, not the
# behaviour itself — and this tool exists to keep
# statements and behaviour separate.

NETWORK_PATTERNS = [
    ("an HTTP client call (requests)",
     re.compile(r"requests\.(get|post|put|patch|delete"
                r"|request|head)\s*\(")),
    ("an HTTP client call (httpx)",
     re.compile(r"httpx\.(get|post|put|patch|delete"
                r"|request|stream)\s*\(")),
    ("a urllib request call",
     re.compile(r"urlopen\s*\(|urllib\.request\.\w+\s*\(")),
    ("a raw HTTP connection",
     re.compile(r"http\.client\.|HTTPSConnection\s*\("
                r"|HTTPConnection\s*\(")),
    ("a socket connection",
     re.compile(r"socket\.socket\s*\(|create_connection\s*\(")),
    ("a browser-style fetch",
     re.compile(r"\bfetch\s*\(|axios\.(get|post|put|delete"
                r"|request)|XMLHttpRequest")),
    ("a shell network tool (curl/wget)",
     re.compile(r"\bcurl\b|\bwget\b")),
    ("a mail/FTP/WebSocket client",
     re.compile(r"smtplib\.|ftplib\.|telnetlib\.|websocket")),
]

SECRET_PATTERNS = [
    ("an SSH key or .ssh store path",
     re.compile(r"\.ssh[/\\]|id_(rsa|dsa|ecdsa|ed25519)\b")),
    ("an AWS credentials/config path",
     re.compile(r"\.aws[/\\]|\.aws\b")),
    ("a GnuPG store path", re.compile(r"\.gnupg\b")),
    ("a .netrc credentials file",
     re.compile(r"\.netrc\b|_netrc\b")),
    ("a stored-credentials file",
     re.compile(r"\.git-credentials\b|\.docker[/\\]config\.json"
                r"|\.kube[/\\]config\b")),
    ("a browser credential store",
     re.compile(r"Login Data|Local State|logins\.json|key4\.db"
                r"|places\.sqlite|Cookies\.sqlite")),
    ("a browser profile directory",
     re.compile(r"User Data[/\\]|[/\\]Mozilla[/\\]|[/\\]Firefox[/\\]"
                r"|profiles\.ini")),
    ("a .env secrets file",
     re.compile(r"[\"'][^\"']*\.env[\"']|(?:cat|open|read)\b"
                r"[^\n]*\.env\b")),
]

_ENV_ACCESS = re.compile(
    r"os\.environ|os\.getenv|environ\.get|process\.env|ENV\["
    r"|getenv\s*\(")
_ENV_SECRET_NAME = re.compile(
    r"SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY"
    r"|CREDENTIAL|AWS_|GITHUB_|GH_TOKEN|OPENAI_|ANTHROPIC_"
    r"|STRIPE_")
_ENV_WHOLE = re.compile(
    r"dict\(\s*os\.environ|list\(\s*os\.environ"
    r"|json\.dumps\([^)]*os\.environ|\{\*\*os\.environ"
    r"|os\.environ\.items\(\)|os\.environ\.copy\(\)")

OUTSIDE_TOKENS = (
    "~/", "$HOME", "%USERPROFILE%", "/Users/", "/home/",
    "/etc/", "/root/", "/tmp/", "/var/", "C:\\Users",
    "C:/Users",
)
_READ_HINT = re.compile(
    r"\bopen\s*\(|\bread\b|\bcat\s|Path\s*\(|expanduser"
    r"|Path\.home")
_WRITE_HINT = re.compile(
    r"open\s*\([^)]*[\"'][wa][\"']|\.write\s*\(|\.save\s*\("
    r"|>\s*[\"']?(?:/|~|\$)")

WRITE_PATTERNS = [
    ("a file write",
     re.compile(r"open\s*\([^)]*[\"'][wa][\"']|\.write\s*\("
                r"|\.save\s*\(")),
    ("a file write (pathlib)",
     re.compile(r"\.write_text\s*\(|\.write_bytes\s*\(")),
    ("a copy/move that writes a destination",
     re.compile(r"shutil\.(copy|copy2|copyfile|move)\b"
                r"|os\.rename\s*\(")),
]
WRITE_SHELL_PATTERNS = [
    ("a shell write (redirect or tee)",
     re.compile(r">>?\s*[\"']?[~/\w.]|\btee\b")),
]

SHELL_PATTERNS = [
    ("a subprocess call",
     re.compile(r"subprocess\.(run|Popen|call|check_output"
                r"|check_call|getoutput)\b")),
    ("a shell command call",
     re.compile(r"os\.system\s*\(|os\.popen\s*\(")),
    ("a subprocess call with shell=True",
     re.compile(r"shell\s*=\s*True|shell:\s*true")),
    ("a Node child-process call",
     re.compile(r"child_process|execSync\s*\(")),
]

DELETE_PATTERNS = [
    ("a file deletion",
     re.compile(r"os\.remove\s*\(|os\.unlink\s*\("
                r"|os\.rmdir\s*\(")),
    ("a tree deletion",
     re.compile(r"shutil\.rmtree\s*\(")),
    ("a file deletion (pathlib)",
     re.compile(r"\.unlink\s*\(")),
    ("a shell delete command",
     re.compile(r"\brm\s+-[a-z]*[rf]|\brm\s+\S")),
]

BEHAVIOUR_CLASSES = [
    "network", "credential_read", "env_read",
    "read_outside", "write", "write_outside", "shell",
    "delete",
]
_BEHAVIOUR_LABEL = {
    "network": "network calls",
    "credential_read": "credential-store / env-secret reads",
    "env_read": "environment-variable reads",
    "read_outside": "reads of paths outside the package",
    "write": "file writes",
    "write_outside": "writes to paths outside the package",
    "shell": "shell / subprocess use",
    "delete": "deletions",
}


def _is_comment_line(line, rel):
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return True
    ext = os.path.splitext(rel)[1].lower()
    if ext in (".js", ".mjs", ".cjs", ".ts", ".php"):
        return stripped.startswith("//")
    return False


def _outside_token(line):
    return any(tok in line for tok in OUTSIDE_TOKENS)


def _hits(rel, lines, patterns):
    out = []
    for lineno, line in enumerate(lines, 1):
        if _is_comment_line(line, rel):
            continue
        for label, rx in patterns:
            if rx.search(line):
                out.append({"file": rel, "line": lineno,
                            "label": label})
                break
    return out


def scan_script_behaviour(rel, text):
    """Behaviour hits for one script file, by class."""
    lines = text.splitlines()
    behaviour = {cls: [] for cls in BEHAVIOUR_CLASSES}
    behaviour["network"] = _hits(rel, lines, NETWORK_PATTERNS)
    behaviour["credential_read"] = _hits(
        rel, lines, SECRET_PATTERNS)
    is_shell = os.path.splitext(rel)[1].lower() in SHELL_EXTS
    for lineno, line in enumerate(lines, 1):
        if _is_comment_line(line, rel):
            continue
        if _ENV_ACCESS.search(line):
            behaviour["env_read"].append({
                "file": rel, "line": lineno,
                "label": "an environment-variable read"})
            if _ENV_SECRET_NAME.search(line):
                behaviour["credential_read"].append({
                    "file": rel, "line": lineno,
                    "label": "an environment-secret read"})
        if _ENV_WHOLE.search(line):
            behaviour["credential_read"].append({
                "file": rel, "line": lineno,
                "label": "a whole-environment read"})
        if _outside_token(line):
            if _READ_HINT.search(line):
                behaviour["read_outside"].append({
                    "file": rel, "line": lineno,
                    "label": "a read of a path outside "
                             "the package"})
            if _WRITE_HINT.search(line):
                behaviour["write_outside"].append({
                    "file": rel, "line": lineno,
                    "label": "a write to a path outside "
                             "the package"})
    behaviour["write"] = _hits(rel, lines, WRITE_PATTERNS)
    if is_shell:
        behaviour["write"] += _hits(
            rel, lines, WRITE_SHELL_PATTERNS)
        for lineno, line in enumerate(lines, 1):
            if line.strip():
                behaviour["shell"].append({
                    "file": rel, "line": lineno,
                    "label": "a shell script — its lines "
                             "are shell commands by "
                             "construction"})
                break
    behaviour["shell"] += _hits(rel, lines, SHELL_PATTERNS)
    behaviour["delete"] = _hits(rel, lines, DELETE_PATTERNS)
    for cls in BEHAVIOUR_CLASSES:
        behaviour[cls].sort(key=lambda h: (h["file"],
                                           h["line"]))
    return behaviour


# ------------------------------------------------------------------
# Claim extraction (deterministic pattern library)
# ------------------------------------------------------------------
# Patterns run over a normalised (lower-cased) clause.
# Order matters: the first matching type wins for a
# clause, so scope claims are tested before the plain
# prohibitions they resemble ("never writes outside"
# is a scope claim, not a no-writes claim).

CLAIM_PATTERNS = [
    ("no_credentials", [
        r"never (touches|reads|accesses|collects|sees) "
        r"(your |any |the )?(credentials|passwords?|secrets"
        r"|api[- ]keys?|ssh keys?|private keys?)",
        r"no (access to |need for )?(your )?(credentials"
        r"|passwords?|secrets|api[- ]keys?)",
        r"does ?n[o']t (read|access|touch|collect) "
        r"(your |any )?(credentials|passwords?|secrets"
        r"|api[- ]keys?)",
        r"credentials (are )?(never|not) (read|accessed"
        r"|touched|collected)",
        r"never asks for (your )?(credentials|password"
        r"|api key)",
    ]),
    ("writes_scope", [
        r"never writes? (anything )?outside",
        r"writes? only (inside|within|into) (the|your|this)",
        r"nothing (is )?written outside",
        r"stays? (inside|within) (the|your|this) "
        r"(project|folder|directory|workspace)",
        r"never modif\w* (anything )?outside",
        r"only writes? (inside|within|to)",
    ]),
    ("no_writes_inside", [
        # a SCOPED prohibition — "never write inside the
        # project directory" forbids one named place,
        # not writing itself; judged separately below
        r"never writes? (anything )?(inside|into|within)\b",
        r"does ?n[o']t write (anything )?(inside|into"
        r"|within)\b",
        r"no writes? (inside|into|within)\b",
        r"nothing (is )?written (inside|into|within)\b",
    ]),
    ("reads_scope", [
        r"only reads?\b",
        r"reads? only\b",
        r"only (touches|accesses|opens|looks at)\b",
        r"touches only\b",
        r"never reads? (anything )?(outside|else|beyond"
        r"|other)",
        r"reads? nothing (outside|else|beyond)",
    ]),
    ("offline", [
        r"\boffline\b(?!\s+tests?\b)",
        r"no network\b",
        r"no internet\b",
        r"never (connects|goes online|phones home)\b",
        r"local[- ]only\b",
        r"(works|runs|operates) (fully )?locally\b",
        r"fully local\b",
        r"air[- ]gapped\b",
        r"without (an? )?(internet|network)\b",
    ]),
    ("no_send", [
        r"sends? nothing\b",
        r"nothing (is |ever )?(sent|uploaded|shared"
        r"|transmitted|leaves)",
        r"never (sends?|shares?|uploads?|transmits?"
        r"|exfiltrates?)\b",
        r"does ?n[o']t (send|share|upload|transmit)\b",
        r"no (telemetry|tracking)\b",
        r"never phones home\b",
        r"(your )?data (never|does ?n[o']t) (leave|leaves)\b",
        r"nothing leaves (your|the)\b",
    ]),
    ("no_writes", [
        r"writes? nothing\b",
        r"never writes?\b",
        r"nothing is written\b",
        r"does ?n[o']t (write|modify|change|alter)\b",
        r"read[- ]only\b",
        r"no writes?\b",
        r"makes no changes\b",
        r"leaves? (your )?files (unchanged|untouched)\b",
        r"never modif\w*\b",
    ]),
    ("no_shell", [
        r"never (runs?|executes?) (shell |any )?(commands?"
        r"|code|subprocess)",
        r"no (shell|subprocess|command execution)\b",
        r"does ?n[o']t (run|execute) (shell |any )?"
        r"(commands?|code)",
        r"runs? no (shell )?commands?\b",
    ]),
    ("no_deletion", [
        r"never deletes?\b",
        r"does ?n[o']t delete\b",
        r"no (deletion|deleting)\b",
        r"never removes? (any |your )?files?\b",
        r"deletes? nothing\b",
        r"never deletes? anything\b",
    ]),
    ("no_env", [
        r"does ?n[o']t (read|access|use) (your |the )?"
        r"(environment|env)\b",
        r"never reads? (your |the )?(environment|env)\b",
        r"ignores? (your |the )?environment\b",
        r"no environment variables?\b",
    ]),
    ("quality", [
        r"\bguarantee[ds]?\b",
        r"\b100%\b",
        r"\bperfectly\b",
        r"(completely|fully|totally) secure\b",
        r"always accurate\b",
        r"never fails\b",
        r"\bbulletproof\b|\bflawless\b|military-grade\b",
    ]),
]
CLAIM_PATTERNS = [
    (kind, [re.compile(p) for p in pats])
    for kind, pats in CLAIM_PATTERNS
]

_CAPABILITY_STEMS = (
    "format|convert|generat|creat|build|pars|extract"
    "|summari|analys|analyz|count|sort|renam|resiz|crop"
    "|translat|detect|validat|verif|check|audit|merg"
    "|split|tidi|clean|organi|transcri|compress|encrypt"
    "|decrypt|render|download|scan|monitor|search|index"
    "|backup|sync|schedul|send|email|notif|track|measur"
    "|calculat|transform|redact|watermark|compil|lint"
    "|migrat|import|export|fetch|publish|sign|hash")
CAPABILITY_VERB = re.compile(r"\b(?:%s)\w*" % _CAPABILITY_STEMS)
_CAPABILITY_WORD = re.compile(r"^(?:%s)" % _CAPABILITY_STEMS)
_DETERMINERS = {"a", "an", "the", "this", "that"}


def _is_capability_clause(clause_lower):
    """A clause states a capability when a capability
    verb stem starts one of its first three words and
    the word is the clause's verb, not an adjective:
    a participle right after a determiner ("a validated
    template") is a noun phrase, not a claim, and a stem
    buried inside a hyphenated compound ("beat-synced")
    is not the clause's verb either. (Both failure
    shapes were found receipts-ing real packages.)"""
    words = re.findall(r"[a-z][a-z0-9-]*", clause_lower)
    for index, word in enumerate(words[:3]):
        if not _CAPABILITY_WORD.match(word):
            continue
        if index > 0 and words[index - 1] in _DETERMINERS \
                and (word.endswith("ed")
                     or word.endswith("ing")):
            return False
        return True
    return False

_TOKEN_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on",
    "for", "with", "without", "your", "you", "it", "its",
    "is", "are", "be", "by", "at", "as", "from", "into",
    "that", "this", "these", "those", "any", "all", "one",
    "two", "per", "via", "files", "file", "pass", "passed",
    "named", "given", "point", "folder", "folders",
    "directory", "text", "terminal", "command", "line",
    "using", "used", "use", "them", "they", "then", "than",
    "when", "while", "what", "which", "where", "there",
    "their", "our", "my", "his", "her", "each", "every",
    "single", "just", "only", "more", "most", "other",
    "others", "such", "like", "over", "under", "between",
    "across", "through", "out", "up", "down", "off",
    "about", "after", "before", "during", "new", "old",
    "works", "work", "runs", "run", "makes", "make",
    "keeps", "keep", "gets", "get", "takes", "take",
    "well", "way", "ways", "kind", "kinds", "set", "sets",
}


def _clean_doc_line(raw):
    """Strip markdown decoration from one doc line so
    claim patterns see the sentence, not the syntax."""
    text = raw.strip()
    text = re.sub(r"<!--.*?-->", " ", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text)
    text = re.sub(r"^\s*>\s?", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _clauses(sentence):
    parts = re.split(r"[,;]|\s—\s|\s–\s", sentence)
    out = []
    for part in parts:
        part = part.strip().strip(".!?")
        part = re.sub(r"^(and|but|so|then)\s+", "", part,
                      flags=re.IGNORECASE)
        if len(part) >= 3:
            out.append(part)
    return out


def _match_behavioural(clause_lower):
    for kind, patterns in CLAIM_PATTERNS:
        for rx in patterns:
            if rx.search(clause_lower):
                return kind
    return None


_BOX_DRAWING = "─│├└┌┐┬┴┼╰╮╭╯"


def _is_prose_line(raw):
    """Claims live in prose. A doc line that is a fenced
    or indented code line, a markdown table row, or a
    directory-tree diagram is an illustration, not a
    statement of the package's behaviour — receipts-ing
    it convicted a real package on the words "offline
    tests" in a tree diagram."""
    stripped = raw.strip()
    if not stripped:
        return False
    if stripped.startswith("|"):
        return False
    if any(ch in raw for ch in _BOX_DRAWING):
        return False
    if raw.startswith(("    ", "\t")):
        return False
    return True


def extract_claims(sources):
    """sources: list of (file, file_rank, [(line, text)],
    is_description). Returns raw claim records in scan
    order: {type, text, file, line}. Non-description
    sources are read as markdown prose: fenced code
    blocks and non-prose lines yield no claims."""
    raw = []
    for fname, _rank, lines, is_description in sources:
        in_fence = False
        for lineno, text in lines:
            if not is_description:
                if text.strip().startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence or not _is_prose_line(text):
                    continue
            cleaned = text if is_description else \
                _clean_doc_line(text)
            if not cleaned:
                continue
            for sentence in _sentences(cleaned):
                for clause in _clauses(sentence):
                    lower = clause.lower()
                    kind = _match_behavioural(lower)
                    if kind is not None:
                        raw.append({
                            "type": kind, "text": clause,
                            "file": fname, "line": lineno})
                    elif is_description and \
                            _is_capability_clause(lower):
                        raw.append({
                            "type": "capability",
                            "text": clause,
                            "file": fname, "line": lineno})
    return raw


def _token_variants(token):
    """Ordered variants (exact word first, then
    singulars) — a list, not a set, so the evidence the
    receipt cites is identical on every run."""
    variants = [token]
    if token.endswith("ies") and len(token) > 3:
        variants.append(token[:-3] + "y")
    if token.endswith("es") and len(token) > 3:
        variants.append(token[:-2])
    if token.endswith("s") and len(token) > 2:
        variants.append(token[:-1])
    out = []
    for variant in variants:
        if variant not in out:
            out.append(variant)
    return out


def capability_tokens(text, skill_name):
    """The distinctive content words of a capability
    claim, used to look for the feature in the code."""
    words = re.findall(r"[a-z][a-z0-9]+", text.lower())
    name_tokens = set(re.findall(
        r"[a-z]+", (skill_name or "").lower()))
    tokens = []
    for word in words:
        if len(word) < 4 or word in _TOKEN_STOPWORDS:
            continue
        if word in name_tokens:
            continue
        if word not in tokens:
            tokens.append(word)
    return tokens


# ------------------------------------------------------------------
# The receipt: merging claims and judging them
# ------------------------------------------------------------------

_TYPE_LABEL = {
    "capability": "capability",
    "offline": "offline",
    "no_send": "sends nothing",
    "no_credentials": "credentials",
    "reads_scope": "read scope",
    "no_writes": "no writes",
    "no_writes_inside": "no writes (scoped)",
    "writes_scope": "write scope",
    "no_shell": "no shell",
    "no_deletion": "no deletion",
    "no_env": "environment",
    "quality": "quality / absolute",
}

# claim type -> behaviour classes whose presence breaks it
_BREAKS = {
    "offline": ("network",),
    "no_send": ("network",),
    "no_credentials": ("credential_read",),
    "reads_scope": ("credential_read", "read_outside"),
    "no_writes": ("write",),
    "writes_scope": ("write_outside",),
    "no_shell": ("shell",),
    "no_deletion": ("delete",),
    "no_env": ("env_read",),
}
# claim type -> behaviour classes it speaks to (coverage)
_COVERS = dict(_BREAKS)
_COVERS["writes_scope"] = ("write", "write_outside")
_COVERS["no_writes_inside"] = ("write",)

_VIOLATION_PHRASE = {
    "offline": "use the network",
    "no_send": "send anything",
    "no_credentials": "read credentials",
    "reads_scope": "read outside the stated scope",
    "no_writes": "write a file",
    "writes_scope": "write outside the stated scope",
    "no_shell": "run a shell command",
    "no_deletion": "delete anything",
    "no_env": "read the environment",
}

_CONTRADICTED_BASIS = {
    "offline": "the claim rules out network use, but the "
               "package's own code makes network calls — "
               "the claim and the code cannot both be true.",
    "no_send": "the claim says nothing is sent, but the "
               "package's own code opens network "
               "connections — every connection sends at "
               "least a request, so something does leave.",
    "no_credentials": "the claim rules out touching "
                      "credentials, but the package's own "
                      "code reads credential material.",
    "reads_scope": "the claim limits reads to the files "
                   "the user passes (or the package's own "
                   "scope), but the package's own code "
                   "reads beyond that.",
    "no_writes": "the claim says the skill writes "
                 "nothing, but the package's own code "
                 "writes files.",
    "writes_scope": "the claim keeps writes inside the "
                    "stated scope, but the package's own "
                    "code writes outside it.",
    "no_shell": "the claim rules out shell / subprocess "
                "use, but the package's own code uses it.",
    "no_deletion": "the claim rules out deletion, but "
                   "the package's own code deletes.",
    "no_env": "the claim rules out reading the "
              "environment, but the package's own code "
              "reads environment variables.",
}

_CLEAN_BASIS = {
    "offline": "no network call was found in any of "
               "the %d scanned script(s) — the behaviour "
               "the claim rules out is absent from the "
               "static evidence.",
    "no_send": "no network call was found in any of "
               "the %d scanned script(s) — nothing in "
               "the code opens a connection.",
    "no_credentials": "no credential-store or "
                      "environment-secret read was found "
                      "in any of the %d scanned script(s).",
    "reads_scope": "no credential-store read and no "
                   "read of a path outside the package "
                   "was found in any of the %d scanned "
                   "script(s).",
    "no_writes": "no file write was found in any of "
                 "the %d scanned script(s).",
    "no_shell": "no shell or subprocess use was found "
                "in any of the %d scanned script(s).",
    "no_deletion": "no deletion was found in any of "
                   "the %d scanned script(s).",
    "no_env": "no environment-variable read was found "
              "in any of the %d scanned script(s).",
}


def merge_claims(raw):
    """Behavioural/quality claims merge by type (first
    phrasing kept, every stating place listed);
    capability claims merge by normalised text."""
    merged = []
    by_key = {}
    for seq, claim in enumerate(raw):
        if claim["type"] == "capability":
            key = ("capability",
                   re.sub(r"\s+", " ",
                          claim["text"].lower()))
        else:
            key = (claim["type"],)
        stated = {"file": claim["file"],
                  "line": claim["line"]}
        if key in by_key:
            entry = by_key[key]
            if stated not in entry["stated_at"]:
                entry["stated_at"].append(stated)
            continue
        entry = {
            "type": claim["type"],
            "text": claim["text"],
            "stated_at": [stated],
            "_seq": seq,
        }
        by_key[key] = entry
        merged.append(entry)
    rank = {"SKILL.md": 0, "README.md": 1}
    merged.sort(key=lambda c: (
        rank.get(c["stated_at"][0]["file"], 2),
        c["stated_at"][0]["line"], c["_seq"]))
    for entry in merged:
        del entry["_seq"]
    return merged


def _merged_hits(behaviour, classes):
    hits = []
    for cls in classes:
        hits.extend(behaviour[cls])
    hits.sort(key=lambda h: (h["file"], h["line"]))
    return hits


def _capability_evidence(claim_text, skill_name,
                         script_lines):
    """Look for the claim's key words in the scripts —
    one combined scan per claim, not one scan per word
    (a vendored tree made the naive version crawl).
    Returns (tokens, found, missing)."""
    tokens = capability_tokens(claim_text, skill_name)
    found = {}
    if not tokens:
        return tokens, found, []
    variant_owner = {}
    for token in tokens:
        for variant in _token_variants(token):
            variant_owner.setdefault(variant, token)
    combined = re.compile(
        r"(?<![a-z0-9])(%s)"
        % "|".join(sorted((re.escape(v) for v in variant_owner),
                          key=len, reverse=True)))
    for rel in sorted(script_lines):
        if len(found) == len(tokens):
            break
        for lineno, line in enumerate(script_lines[rel], 1):
            if _is_comment_line(line, rel):
                continue
            for m in combined.finditer(line.lower()):
                token = variant_owner[m.group(1)]
                if token not in found:
                    found[token] = {
                        "file": rel, "line": lineno,
                        "label": "'%s' appears here"
                                 % m.group(1)}
            if len(found) == len(tokens):
                break
    missing = [t for t in tokens if t not in found]
    return tokens, found, missing


def judge_claim(claim, behaviour, script_lines,
                scripts_scanned, incomplete_paths,
                skill_name, pkg_dirname=None):
    """Attach verdict / basis / evidence to one merged
    claim. Returns the claim dict (JSON-ready)."""
    kind = claim["type"]
    out = {
        "type": kind,
        "text": claim["text"],
        "stated_at": claim["stated_at"],
        "verdict": None,
        "basis": "",
        "evidence": [],
    }
    if kind == "quality":
        out["verdict"] = "UNEVIDENCED"
        out["basis"] = (
            "an absolute / quality claim — static "
            "evidence can neither confirm nor refute "
            "words like this; only running the skill and "
            "measuring it could, and this tool never "
            "runs the skill.")
        return out
    if kind == "capability":
        if not script_lines:
            out["verdict"] = "UNEVIDENCED"
            out["basis"] = (
                "the package ships no scripts whose code "
                "could evidence this capability — a "
                "prose-only skill's capabilities cannot "
                "be receipted from static code evidence.")
            return out
        tokens, found, missing = _capability_evidence(
            claim["text"], skill_name, script_lines)
        if not tokens:
            out["verdict"] = "UNEVIDENCED"
            out["basis"] = (
                "the claim has no distinctive content "
                "words to look for in the package's code.")
            return out
        need = max(1, -(-len(tokens) // 2))
        if len(found) >= need:
            out["verdict"] = "SUPPORTED"
            out["evidence"] = list(found.values())[:3]
            out["basis"] = (
                "%d of the claim's %d key words (%s) "
                "appear in the package's code — the "
                "vocabulary of the feature the claim "
                "names is present in the implementation "
                "itself, which is the static evidence a "
                "capability claim can be receipted on."
                % (len(found), len(tokens),
                   ", ".join(sorted(found))))
        else:
            out["verdict"] = "UNEVIDENCED"
            out["basis"] = (
                "only %d of the claim's %d key words "
                "(%s) appear in the package's code; %s "
                "appear nowhere in it — not enough static "
                "evidence to receipt the capability. "
                "Static analysis cannot prove a feature "
                "absent, so this is UNEVIDENCED, never "
                "CONTRADICTED."
                % (len(found), len(tokens),
                   ", ".join(sorted(found)) or "none",
                   ", ".join(missing)))
        return out
    if kind == "no_writes_inside":
        # a scoped prohibition: the forbidden zone is a
        # NAMED place. Only a write provably aimed at
        # the package's own location breaks it; writes
        # to runtime-computed paths cannot be placed
        # inside or outside the named scope statically.
        writes = behaviour["write"]
        inside_hits = []
        for hit in writes:
            file_lines = script_lines.get(hit["file"]) or []
            text = file_lines[hit["line"] - 1] \
                if hit["line"] <= len(file_lines) else ""
            if "__file__" in text or \
                    (pkg_dirname and pkg_dirname in text):
                inside_hits.append(hit)
        if inside_hits:
            out["verdict"] = "CONTRADICTED"
            out["evidence"] = inside_hits[:3]
            out["basis"] = (
                "the claim forbids writes inside a named "
                "scope, and this write targets the "
                "package's own location (a __file__-"
                "relative or package-named path) — inside "
                "the forbidden scope by construction.")
        elif not writes and incomplete_paths:
            out["verdict"] = "UNEVIDENCED"
            out["basis"] = (
                "no writes were found in the %d scanned "
                "script(s) — but the package ships "
                "content static analysis cannot read (%s), "
                "so the claim cannot be fully receipted."
                % (scripts_scanned,
                   ", ".join(incomplete_paths[:3])))
        elif not writes:
            out["verdict"] = "SUPPORTED"
            out["basis"] = (
                "no writes of any kind were found in "
                "the %d scanned script(s) — nothing can "
                "land in the forbidden scope."
                % scripts_scanned)
        else:
            first = writes[0]
            out["verdict"] = "UNEVIDENCED"
            out["evidence"] = [first]
            out["basis"] = (
                "the claim forbids writes inside a named "
                "scope, and writes do occur (first at "
                "%s · line %d) — but their targets are "
                "paths computed at runtime, and static "
                "evidence cannot place them inside or "
                "outside the named scope. UNEVIDENCED, "
                "not convicted on scope it cannot see."
                % (first["file"], first["line"]))
        return out
    # behavioural prohibitions and scopes
    hits = _merged_hits(behaviour, _BREAKS[kind])
    if hits:
        out["verdict"] = "CONTRADICTED"
        out["evidence"] = hits[:3]
        out["basis"] = _CONTRADICTED_BASIS[kind]
        return out
    if incomplete_paths:
        out["verdict"] = "UNEVIDENCED"
        out["basis"] = (
            "the behaviour this claim rules out was "
            "searched for in the %d scanned script(s) "
            "and not found — but the package ships "
            "content static analysis cannot read (%s), "
            "so the claim cannot be fully receipted."
            % (scripts_scanned,
               ", ".join(incomplete_paths[:3])))
        return out
    if scripts_scanned == 0:
        out["verdict"] = "SUPPORTED"
        out["basis"] = (
            "the package ships no scripts at all — "
            "there is no code in it that could %s."
            % _VIOLATION_PHRASE[kind])
        return out
    if kind == "writes_scope":
        writes = behaviour["write"]
        if writes:
            first = writes[0]
            out["verdict"] = "SUPPORTED"
            out["evidence"] = [first]
            out["basis"] = (
                "writes were found (first at %s · line "
                "%d) and none of them targets a path "
                "outside the package — the writes stay "
                "inside the scope the claim states."
                % (first["file"], first["line"]))
        else:
            out["verdict"] = "SUPPORTED"
            out["basis"] = (
                "no writes of any kind were found in "
                "the %d scanned script(s) — the scope "
                "claim holds vacuously."
                % scripts_scanned)
        return out
    out["verdict"] = "SUPPORTED"
    out["basis"] = _CLEAN_BASIS[kind] % scripts_scanned
    return out


# ------------------------------------------------------------------
# The audit driver
# ------------------------------------------------------------------

def audit_package(pkg_dir):
    records = inventory(pkg_dir)
    by_path = {r["path"]: r for r in records}

    skill_rel = None
    for rec in records:
        base = rec["path"].rsplit("/", 1)[-1]
        if "/" not in rec["path"] and \
                base.lower() == "skill.md":
            if base == "SKILL.md":
                skill_rel = rec["path"]
                break
            skill_rel = skill_rel or rec["path"]
    if skill_rel is None:
        raise ToolError(
            "no SKILL.md at the root of %s — point audit "
            "at a skill package folder (the one holding "
            "SKILL.md)" % pkg_dir)
    skill_text = read_text(pkg_dir, skill_rel)
    if skill_text is None or not skill_text.strip():
        raise ToolError(
            "the SKILL.md in %s is empty — there are no "
            "claims to receipt" % pkg_dir)
    fields, field_lines, body_lines, parse_error, \
        parse_line = parse_frontmatter(skill_text)
    if parse_error == "missing":
        raise ToolError(
            "SKILL.md in %s has no --- frontmatter block "
            "— skill-claims receipts the frontmatter-"
            "declared format; the declared description "
            "is the claim of record" % pkg_dir)
    if parse_error:
        raise ToolError(
            "SKILL.md frontmatter does not parse "
            "(line %s): %s" % (parse_line, parse_error))
    if skill_rel in by_path:
        by_path[skill_rel]["scanned"] = True

    sources = []
    description = field_text(fields, "description")
    if description and description.strip():
        sources.append((
            skill_rel, 0,
            [(field_lines.get("description", 1),
              description)], True))
    sources.append((skill_rel, 0, body_lines, False))
    for rec in records:
        base = rec["path"].rsplit("/", 1)[-1]
        if "/" not in rec["path"] and \
                base.lower() == "readme.md" and \
                not rec["binary"] and not rec["symlink_out"]:
            text = read_text(pkg_dir, rec["path"]) or ""
            rec["scanned"] = True
            sources.append((
                rec["path"], 1,
                [(i + 1, line) for i, line in
                 enumerate(text.splitlines())], False))
            break

    raw_claims = extract_claims(sources)
    merged = merge_claims(raw_claims)

    behaviour = {cls: [] for cls in BEHAVIOUR_CLASSES}
    script_lines = {}
    scripts_scanned = 0
    for rec in records:
        if rec["kind"] != "script" or rec["binary"] or \
                rec["symlink_out"]:
            continue
        text = read_text(pkg_dir, rec["path"])
        if text is None:
            continue
        rec["scanned"] = True
        scripts_scanned += 1
        script_lines[rec["path"]] = text.splitlines()
        per_file = scan_script_behaviour(rec["path"], text)
        for cls in BEHAVIOUR_CLASSES:
            behaviour[cls].extend(per_file[cls])
    for cls in BEHAVIOUR_CLASSES:
        behaviour[cls].sort(key=lambda h: (h["file"],
                                           h["line"]))

    incomplete_paths = []
    for rec in records:
        ext = os.path.splitext(rec["path"])[1].lower()
        if rec["symlink_out"]:
            incomplete_paths.append(rec["path"])
        elif rec["binary"] and ext in BINARY_EXTS:
            incomplete_paths.append(rec["path"])
        elif rec["kind"] == "script" and \
                rec["bytes"] > SCAN_CAP_BYTES:
            incomplete_paths.append(rec["path"])

    skill_name = field_text(fields, "name")
    pkg_dirname = os.path.basename(os.path.realpath(pkg_dir))
    claims = [
        judge_claim(claim, behaviour, script_lines,
                    scripts_scanned, incomplete_paths,
                    skill_name, pkg_dirname)
        for claim in merged
    ]

    covered = set()
    for claim in claims:
        covered.update(_COVERS.get(claim["type"], ()))
    unclaimed = [cls for cls in BEHAVIOUR_CLASSES
                 if behaviour[cls] and cls not in covered]

    summary = {
        "claims": len(claims),
        "supported": sum(1 for c in claims
                         if c["verdict"] == "SUPPORTED"),
        "unevidenced": sum(1 for c in claims
                           if c["verdict"] == "UNEVIDENCED"),
        "contradicted": sum(1 for c in claims
                            if c["verdict"] == "CONTRADICTED"),
    }
    if not claims:
        verdict = "NO_CLAIMS"
    elif summary["contradicted"]:
        verdict = "CONTRADICTED"
    elif summary["unevidenced"]:
        verdict = "UNEVIDENCED"
    else:
        verdict = "SUPPORTED"
    return {
        "tool": TOOL,
        "version": VERSION,
        "command": "audit",
        "package": {
            "dir": pkg_dir,
            "dirname": os.path.basename(
                os.path.realpath(pkg_dir)),
            "name": skill_name,
            "skill_file": skill_rel,
        },
        "files": records,
        "claims": claims,
        "behaviour": {
            cls: {"count": len(behaviour[cls]),
                  "hits": behaviour[cls]}
            for cls in BEHAVIOUR_CLASSES
        },
        "scripts_scanned": scripts_scanned,
        "unclaimed_behaviour": unclaimed,
        "summary": summary,
        "verdict": verdict,
        "verdict_rule": VERDICT_RULE,
        "limits": LIMITS_LINE,
    }


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------

def _human_size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KiB" % (n / 1024)
    return "%.1f MiB" % (n / (1024 * 1024))


def render_text(result):
    pkg = result["package"]
    files = result["files"]
    claims = result["claims"]
    s = result["summary"]
    lines = []
    lines.append(
        "%s v%s — audit · package %s · %d files · "
        "%d claims"
        % (TOOL, VERSION, pkg["dirname"], len(files),
           len(claims)))
    if pkg["name"]:
        lines.append("Frontmatter name: %s" % pkg["name"])
    lines.append(
        "Read-only: it edits nothing, writes nothing, "
        "and never executes anything in the package — "
        "every file is analysed as static text.")
    lines.append("Verdict rule: " + VERDICT_RULE)
    lines.append("Limits: " + LIMITS_LINE)
    lines.append("")
    if claims:
        lines.append("CLAIMS (%d):" % len(claims))
        for claim in claims:
            stated = claim["stated_at"][0]
            head = "[%s] %s — \"%s\"" % (
                claim["verdict"],
                _TYPE_LABEL[claim["type"]], claim["text"])
            lines.append(head)
            stated_bits = ["%s · line %s" % (st["file"],
                                             st["line"])
                           for st in claim["stated_at"]]
            lines.append("  stated: " + "; ".join(
                stated_bits))
            if claim["evidence"]:
                direction = {
                    "CONTRADICTED": "against",
                    "SUPPORTED": "for",
                }.get(claim["verdict"], "found")
                for hit in claim["evidence"]:
                    lines.append(
                        "  evidence %s: %s · line %d — %s"
                        % (direction, hit["file"],
                           hit["line"], hit["label"]))
            lines.append("  basis: " + claim["basis"])
    else:
        lines.append(
            "CLAIMS (0): the package's description and "
            "docs make no claim the pattern library can "
            "check — no capability sentence in the "
            "description, and no never/no/only statement "
            "about network, reads, writes, credentials, "
            "shell, deletion, or environment.")
    lines.append("")
    lines.append(
        "BEHAVIOUR FOUND (%d script(s) scanned):"
        % result["scripts_scanned"])
    for cls in BEHAVIOUR_CLASSES:
        entry = result["behaviour"][cls]
        if entry["count"] == 0:
            lines.append("  %s — none found"
                         % _BEHAVIOUR_LABEL[cls])
        else:
            first = entry["hits"][0]
            lines.append(
                "  %s — %d hit(s); first: %s · line %d "
                "— %s"
                % (_BEHAVIOUR_LABEL[cls], entry["count"],
                   first["file"], first["line"],
                   first["label"]))
    if result["unclaimed_behaviour"]:
        names = ", ".join(
            _BEHAVIOUR_LABEL[cls]
            for cls in result["unclaimed_behaviour"])
        lines.append(
            "Behaviour no claim covers: %s. (Listed so "
            "the receipt is complete — unclaimed "
            "behaviour is not a contradiction.)" % names)
    lines.append("")
    lines.append(
        "Summary: %d claims · %d supported · %d "
        "unevidenced · %d contradicted"
        % (s["claims"], s["supported"], s["unevidenced"],
           s["contradicted"]))
    verdict = result["verdict"]
    if verdict == "CONTRADICTED":
        lines.append(
            "Verdict: CONTRADICTED — %d claim(s) are "
            "contradicted by the package's own code."
            % s["contradicted"])
    elif verdict == "SUPPORTED":
        lines.append(
            "Verdict: SUPPORTED — every claim the "
            "package makes is backed by the static "
            "evidence.")
    elif verdict == "UNEVIDENCED":
        lines.append(
            "Verdict: UNEVIDENCED — no claim is "
            "contradicted, but %d claim(s) have no "
            "static evidence either way."
            % s["unevidenced"])
    else:
        lines.append(
            "Verdict: NO_CLAIMS — the package makes no "
            "checkable claim.")
    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

class _JsonAwareParser(argparse.ArgumentParser):
    """ArgumentParser that reports usage errors as JSON
    in --json mode ({"error": ...} on stdout, same exit
    code 2), matching the house error contract."""

    json_mode = False

    def error(self, message):
        if self.json_mode:
            print(json.dumps({"error": message}))
            raise SystemExit(2)
        super().error(message)


def cmd_audit(args):
    path = args.path
    if not os.path.exists(path):
        raise ToolError("no such folder: %s" % path)
    if not os.path.isdir(path):
        raise ToolError(
            "not a folder: %s — point audit at the skill "
            "package's root folder" % path)
    result = audit_package(path)
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print(render_text(result))
    if result["verdict"] == "CONTRADICTED":
        return 1
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    _JsonAwareParser.json_mode = "--json" in argv
    ap = _JsonAwareParser(
        prog=TOOL,
        description="Receipt an agent skill package's "
                    "claims against its own code: extract "
                    "what the description and docs claim, "
                    "extract what the bundled scripts "
                    "statically do, and print a per-claim "
                    "verdict — SUPPORTED, UNEVIDENCED, or "
                    "CONTRADICTED with file-and-line "
                    "evidence. Deterministic, local, "
                    "read-only, executes nothing (stdlib "
                    "only).")
    sub = ap.add_subparsers(dest="command", required=True,
                            parser_class=_JsonAwareParser)

    p_audit = sub.add_parser(
        "audit", help="audit one skill package folder: "
                      "exit 1 when any claim is "
                      "CONTRADICTED, 0 when none is, 2 "
                      "for input errors")
    p_audit.add_argument(
        "path",
        help="the skill package's root folder (the one "
             "holding SKILL.md)")
    p_audit.add_argument("--json", action="store_true",
                         help="print one JSON object "
                              "instead of text")
    p_audit.set_defaults(func=cmd_audit)

    a = ap.parse_args(argv)

    def fail(msg):
        if getattr(a, "json", False):
            print(json.dumps({"error": msg}))
        else:
            print("ERROR: %s" % msg)
        return 2

    try:
        return a.func(a)
    except ToolError as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
