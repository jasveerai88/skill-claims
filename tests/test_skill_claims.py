#!/usr/bin/env python3
"""Tests for skill-claims. Stdlib unittest only.

Run from the pack root:
    python3 -m unittest discover -s tests -v

The bundled fixtures are CONSTRUCTED skill packages
(fictional, labelled as such) whose expected receipts
were worked out by hand from the verdict rules in
SKILL.md — never copied from the tool's own output:

lying-formatter/ (the demo fixture):
    SKILL.md description claims a markdown-table
    capability, full offline working, and reads limited
    to the files the user passes; the body claims it
    never touches credentials. scripts/format.py really
    does format tables and tidy headings.
    scripts/telemetry.py reads ~/.aws/credentials
    (line 11) and POSTs with urllib (lines 20-22).
    => capability SUPPORTED · offline CONTRADICTED
       · reads_scope CONTRADICTED · no_credentials
       CONTRADICTED · overall CONTRADICTED · exit 1

honest-skill/ (the both-directions proof):
    description + body claim a table-formatting
    capability, offline working, no writes, reads
    limited to named files, no deletion — and
    scripts/format.py does exactly that and no more.
    => 5 claims, all SUPPORTED · overall SUPPORTED
       · exit 0

Variant packages built in temp dirs pin every claim
type and every behaviour detector in both directions,
the UNEVIDENCED paths (capability without code
evidence, quality claims, unscannable content), the
error contract (exit 2, {"error": ...}, no
tracebacks), and the safety proofs (nothing in a
package is ever executed; fixture trees are
byte-identical after a run; the source's imports are
pinned to a stdlib set with no network or subprocess
module).
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_ROOT = os.path.dirname(HERE)
SRC = os.path.join(PACK_ROOT, "src", "skill_claims.py")
EXAMPLES = os.path.join(PACK_ROOT, "examples")

sys.path.insert(0, os.path.join(PACK_ROOT, "src"))
import skill_claims  # noqa: E402


def run_cli(*argv):
    proc = subprocess.run(
        [sys.executable, SRC] + list(argv),
        capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def run_json(*argv):
    code, out, err = run_cli(*(list(argv) + ["--json"]))
    return code, json.loads(out), err


def make_package(desc=None, body="", scripts=None,
                 extra=None, name="test-skill"):
    """Build a temp skill package. Returns its dir."""
    root = tempfile.mkdtemp(prefix="skill-claims-test-")
    lines = ["---", "name: %s" % name]
    if desc is not None:
        lines.append("description: %s" % desc)
    lines += ["---", "", "# Test Skill", ""]
    if body:
        lines.append(body)
    with open(os.path.join(root, "SKILL.md"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    for rel, content in (scripts or {}).items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
    for rel, data in (extra or {}).items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(full, mode) as fh:
            fh.write(data)
    return root


def claim_by_type(result, kind):
    for claim in result["claims"]:
        if claim["type"] == kind:
            return claim
    return None


def tree_hashes(root):
    out = {}
    for base, _dirs, names in os.walk(root):
        for name in names:
            full = os.path.join(base, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root)] = \
                    hashlib.sha256(fh.read()).hexdigest()
    return out


CLEAN_READER = '''#!/usr/bin/env python3
"""Read the files it is given and print them."""

import sys


def main():
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as fh:
            print(fh.read())
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class FixtureTests(unittest.TestCase):

    def test_lying_formatter_receipt(self):
        code, result, _ = run_json(
            "audit", os.path.join(EXAMPLES, "lying-formatter"))
        self.assertEqual(code, 1)
        self.assertEqual(result["verdict"], "CONTRADICTED")
        self.assertEqual(result["summary"], {
            "claims": 4, "supported": 1, "unevidenced": 0,
            "contradicted": 3})
        cap = claim_by_type(result, "capability")
        self.assertEqual(cap["verdict"], "SUPPORTED")
        self.assertEqual(
            cap["text"],
            "Formats markdown tables and tidies headings "
            "in the files you pass it")
        off = claim_by_type(result, "offline")
        self.assertEqual(off["verdict"], "CONTRADICTED")
        self.assertEqual(off["evidence"][0]["file"],
                         "scripts/telemetry.py")
        self.assertEqual(off["evidence"][0]["line"], 20)
        scope = claim_by_type(result, "reads_scope")
        self.assertEqual(scope["verdict"], "CONTRADICTED")
        cred = claim_by_type(result, "no_credentials")
        self.assertEqual(cred["verdict"], "CONTRADICTED")
        self.assertEqual(cred["evidence"][0]["line"], 11)
        self.assertEqual(
            result["behaviour"]["network"]["count"], 2)
        self.assertEqual(
            result["behaviour"]["credential_read"]["count"],
            1)
        self.assertEqual(
            result["behaviour"]["read_outside"]["count"], 1)

    def test_honest_skill_receipt(self):
        code, result, _ = run_json(
            "audit", os.path.join(EXAMPLES, "honest-skill"))
        self.assertEqual(code, 0)
        self.assertEqual(result["verdict"], "SUPPORTED")
        self.assertEqual(result["summary"], {
            "claims": 5, "supported": 5, "unevidenced": 0,
            "contradicted": 0})
        for kind in ("capability", "offline", "no_writes",
                     "reads_scope", "no_deletion"):
            claim = claim_by_type(result, kind)
            self.assertIsNotNone(claim, kind)
            self.assertEqual(claim["verdict"], "SUPPORTED",
                             kind)
        offline = claim_by_type(result, "offline")
        # stated in the description (line 3) and again in
        # the body (line 19) — receipted once, both listed
        self.assertEqual(len(offline["stated_at"]), 2)
        for cls in skill_claims.BEHAVIOUR_CLASSES:
            self.assertEqual(
                result["behaviour"][cls]["count"], 0, cls)

    def test_fixtures_byte_identical_after_run(self):
        for name in ("lying-formatter", "honest-skill"):
            root = os.path.join(EXAMPLES, name)
            before = tree_hashes(root)
            run_cli("audit", root)
            self.assertEqual(tree_hashes(root), before)

    def test_text_output_shape(self):
        code, out, _ = run_cli(
            "audit", os.path.join(EXAMPLES, "lying-formatter"))
        self.assertEqual(code, 1)
        self.assertIn("CLAIMS (4):", out)
        self.assertIn("[CONTRADICTED] offline", out)
        self.assertIn("Verdict: CONTRADICTED", out)
        self.assertIn("BEHAVIOUR FOUND", out)

    def test_json_recounts(self):
        _code, result, _ = run_json(
            "audit", os.path.join(EXAMPLES, "lying-formatter"))
        claims = result["claims"]
        s = result["summary"]
        self.assertEqual(s["claims"], len(claims))
        self.assertEqual(
            s["supported"],
            sum(1 for c in claims
                if c["verdict"] == "SUPPORTED"))
        self.assertEqual(
            s["contradicted"],
            sum(1 for c in claims
                if c["verdict"] == "CONTRADICTED"))
        for cls, entry in result["behaviour"].items():
            self.assertEqual(entry["count"],
                             len(entry["hits"]), cls)

    def test_deterministic_output(self):
        target = os.path.join(EXAMPLES, "honest-skill")
        _c1, out1, _ = run_cli("audit", target)
        _c2, out2, _ = run_cli("audit", target)
        self.assertEqual(out1, out2)


class ClaimExtractionTests(unittest.TestCase):

    def audit_desc(self, desc, body="", scripts=None):
        root = make_package(desc=desc, body=body,
                            scripts=scripts)
        _code, result, _ = run_json("audit", root)
        return result

    def test_each_behavioural_type_fires(self):
        phrases = {
            "offline": "Works fully offline.",
            "no_send": "Sends nothing anywhere.",
            "no_credentials":
                "Never touches your credentials.",
            "reads_scope":
                "Reads only the files you pass it.",
            "no_writes": "Writes nothing.",
            "writes_scope":
                "Never writes outside the project.",
            "no_shell": "Never runs shell commands.",
            "no_deletion": "Never deletes anything.",
            "no_env":
                "Does not read environment variables.",
            "quality": "Guaranteed to work.",
        }
        for kind, phrase in phrases.items():
            result = self.audit_desc(phrase)
            claim = claim_by_type(result, kind)
            self.assertIsNotNone(claim, kind)
            self.assertEqual(claim["text"],
                             phrase.rstrip("."), kind)

    def test_no_claims_package(self):
        result = self.audit_desc(
            "A handy helper for your daily notes.")
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["verdict"], "NO_CLAIMS")

    def test_capability_only_from_description(self):
        result = self.audit_desc(
            "A handy helper for your daily notes.",
            body="Converts images to PNG and resizes them.")
        self.assertEqual(
            [c for c in result["claims"]
             if c["type"] == "capability"], [])
        result = self.audit_desc(
            "Converts images to PNG.")
        self.assertIsNotNone(
            claim_by_type(result, "capability"))

    def test_same_type_merges_across_docs(self):
        result = self.audit_desc(
            "Works fully offline.",
            body="- It works offline at all times.")
        offline = [c for c in result["claims"]
                   if c["type"] == "offline"]
        self.assertEqual(len(offline), 1)
        self.assertEqual(len(offline[0]["stated_at"]), 2)

    def test_readme_is_a_claim_source(self):
        root = make_package(
            desc="A handy helper for your daily notes.",
            scripts={"scripts/x.py": CLEAN_READER},
            extra={"README.md":
                   "# Notes\n\nNever deletes anything.\n"})
        _code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "no_deletion")
        self.assertIsNotNone(claim)
        self.assertEqual(claim["stated_at"][0]["file"],
                         "README.md")


class BothDirectionsTests(unittest.TestCase):
    """One claim + one script: the verdict must flip on
    the evidence, in both directions, per claim type."""

    def verdict_of(self, desc, script, kind):
        root = make_package(
            desc=desc, scripts={"scripts/x.py": script})
        _code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, kind)
        self.assertIsNotNone(claim, kind)
        return claim["verdict"], result

    def test_offline(self):
        v, _ = self.verdict_of(
            "Works fully offline.",
            "import requests\nrequests.get('https://x.invalid')\n",
            "offline")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Works fully offline.", CLEAN_READER, "offline")
        self.assertEqual(v, "SUPPORTED")
        v, _ = self.verdict_of(
            "Works fully offline.",
            "import subprocess\nsubprocess.run(['curl', 'https://x.invalid'])\n",
            "offline")
        self.assertEqual(v, "CONTRADICTED")

    def test_no_send(self):
        v, _ = self.verdict_of(
            "Sends nothing anywhere.",
            "import socket\ns = socket.socket()\n",
            "no_send")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Sends nothing anywhere.", CLEAN_READER,
            "no_send")
        self.assertEqual(v, "SUPPORTED")

    def test_no_credentials(self):
        # touching is the claim — no send needed to break it
        v, _ = self.verdict_of(
            "Never touches your credentials.",
            "data = open('~/.ssh/id_rsa').read()\n",
            "no_credentials")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Never touches your credentials.", CLEAN_READER,
            "no_credentials")
        self.assertEqual(v, "SUPPORTED")

    def test_reads_scope(self):
        v, _ = self.verdict_of(
            "Reads only the files you pass it.",
            "data = open('/etc/passwd').read()\n",
            "reads_scope")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Reads only the files you pass it.",
            "import os\nk = os.environ['AWS_SECRET_ACCESS_KEY']\n",
            "reads_scope")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Reads only the files you pass it.", CLEAN_READER,
            "reads_scope")
        self.assertEqual(v, "SUPPORTED")

    def test_no_writes(self):
        v, _ = self.verdict_of(
            "Writes nothing.",
            "open('out.txt', 'w').write('x')\n", "no_writes")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Writes nothing.", CLEAN_READER, "no_writes")
        self.assertEqual(v, "SUPPORTED")

    def test_writes_scope(self):
        v, _ = self.verdict_of(
            "Never writes outside the project.",
            "open('/tmp/out.txt', 'w').write('x')\n",
            "writes_scope")
        self.assertEqual(v, "CONTRADICTED")
        v, result = self.verdict_of(
            "Never writes outside the project.",
            "open('out.txt', 'w').write('x')\n",
            "writes_scope")
        self.assertEqual(v, "SUPPORTED")
        v, _ = self.verdict_of(
            "Never writes outside the project.", CLEAN_READER,
            "writes_scope")
        self.assertEqual(v, "SUPPORTED")

    def test_no_shell(self):
        v, _ = self.verdict_of(
            "Never runs shell commands.",
            "import subprocess\nsubprocess.run(['ls'])\n",
            "no_shell")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Never runs shell commands.", CLEAN_READER,
            "no_shell")
        self.assertEqual(v, "SUPPORTED")

    def test_no_shell_broken_by_shell_script(self):
        root = make_package(
            desc="Never runs shell commands.",
            scripts={"scripts/x.sh": "#!/bin/sh\necho hi\n"})
        _code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "no_shell")
        self.assertEqual(claim["verdict"], "CONTRADICTED")

    def test_no_deletion(self):
        v, _ = self.verdict_of(
            "Never deletes anything.",
            "import os\nos.remove('x.txt')\n", "no_deletion")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Never deletes anything.", CLEAN_READER,
            "no_deletion")
        self.assertEqual(v, "SUPPORTED")

    def test_no_env(self):
        v, result = self.verdict_of(
            "Does not read environment variables.",
            "import os\nprint(os.environ['HOME'])\n",
            "no_env")
        self.assertEqual(v, "CONTRADICTED")
        v, _ = self.verdict_of(
            "Does not read environment variables.",
            CLEAN_READER, "no_env")
        self.assertEqual(v, "SUPPORTED")

    def test_comment_is_a_statement_not_behaviour(self):
        script = ("# requests.get('https://x.invalid') "
                  "would go here\n"
                  "print('hello')\n")
        v, _ = self.verdict_of(
            "Works fully offline.", script, "offline")
        self.assertEqual(v, "SUPPORTED")


class UnevidencedTests(unittest.TestCase):

    def test_capability_without_code_evidence(self):
        root = make_package(
            desc="Translates documents into French.",
            scripts={"scripts/x.py":
                     "print('hello world')\n"})
        code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "capability")
        self.assertEqual(claim["verdict"], "UNEVIDENCED")
        self.assertEqual(result["verdict"], "UNEVIDENCED")
        self.assertEqual(code, 0)

    def test_capability_is_never_contradicted(self):
        # even with network code in the package, a
        # capability claim can only be UNEVIDENCED
        root = make_package(
            desc="Translates documents into French.",
            scripts={"scripts/x.py":
                     "import urllib.request\n"
                     "urllib.request.urlopen('https://x.invalid')\n"})
        _code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "capability")
        self.assertIn(claim["verdict"],
                      ("SUPPORTED", "UNEVIDENCED"))

    def test_quality_claim_is_always_unevidenced(self):
        root = make_package(
            desc="Guaranteed 100% accurate results.",
            scripts={"scripts/x.py": CLEAN_READER})
        code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "quality")
        self.assertEqual(claim["verdict"], "UNEVIDENCED")
        self.assertEqual(code, 0)

    def test_docs_only_package_offline_supported(self):
        root = make_package(desc="Works fully offline.")
        _code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "offline")
        self.assertEqual(claim["verdict"], "SUPPORTED")
        self.assertIn("no scripts", claim["basis"])

    def test_binary_downgrades_supported_to_unevidenced(self):
        root = make_package(
            desc="Works fully offline.",
            scripts={"scripts/x.py": CLEAN_READER},
            extra={"helper.exe": b"\x00\x01\x02binary"})
        code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "offline")
        self.assertEqual(claim["verdict"], "UNEVIDENCED")
        self.assertEqual(code, 0)

    def test_unclaimed_behaviour_is_listed_not_contradicted(self):
        script = ("import urllib.request\n"
                  "data = urllib.request.urlopen("
                  "'https://x.invalid').read()\n"
                  "words = data.split()\n"
                  "print('count', len(words), 'words')\n")
        root = make_package(
            desc="Counts words in text.",
            scripts={"scripts/x.py": script})
        code, result, _ = run_json("audit", root)
        self.assertEqual(code, 0)
        self.assertEqual(result["verdict"], "SUPPORTED")
        self.assertIn("network",
                      result["unclaimed_behaviour"])
        self.assertEqual(
            result["behaviour"]["network"]["count"], 1)


class DogfoodRegressionTests(unittest.TestCase):
    """Pinned from receipts run against real packages in
    this tool's own workspace (2026-11-06): three shapes
    that produced false verdicts before the fixes."""

    def test_tree_diagram_line_is_not_a_claim(self):
        # a directory tree mentioning "offline tests" is
        # an illustration, not an offline claim — and a
        # network call elsewhere must not "contradict" it
        body = ("Project layout:\n\n"
                "    ├── publish/   # social publisher "
                "+ offline tests\n"
                "    └── core/      # the engine\n")
        root = make_package(
            desc="Formats markdown tables.",
            body=body,
            scripts={"scripts/x.py":
                     "import urllib.request\n"
                     "urllib.request.urlopen("
                     "'https://x.invalid')\n"})
        _code, result, _ = run_json("audit", root)
        self.assertIsNone(claim_by_type(result, "offline"))
        self.assertNotEqual(result["verdict"],
                            "CONTRADICTED")

    def test_offline_tests_phrase_is_not_a_claim(self):
        root = make_package(
            desc="Formats markdown tables.",
            body="The offline tests run before release.")
        _code, result, _ = run_json("audit", root)
        self.assertIsNone(claim_by_type(result, "offline"))

    def test_fenced_code_yields_no_claims(self):
        body = ("Example of what not to do:\n\n"
                "```\nNever deletes anything.\n```\n")
        root = make_package(
            desc="Formats markdown tables.", body=body)
        _code, result, _ = run_json("audit", root)
        self.assertIsNone(
            claim_by_type(result, "no_deletion"))

    def test_vendored_code_is_not_the_packages_own(self):
        # a bundled .venv's writes/network must neither
        # contradict the skill's claims nor evidence its
        # capabilities (a real package shipped 7,322
        # vendored files and was convicted by PIL)
        root = make_package(
            desc="Works fully offline.",
            scripts={
                "scripts/x.py": CLEAN_READER,
                ".venv/lib/site-packages/PIL/Image.py":
                    "open('x', 'w').write('y')\n"
                    "import urllib.request\n",
            })
        _code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "offline")
        self.assertEqual(claim["verdict"], "SUPPORTED")
        paths = [f["path"] for f in result["files"]]
        self.assertFalse(
            any(p.startswith(".venv") for p in paths))

    def test_fragment_is_not_a_capability(self):
        # "a validated template" is a noun phrase, not a
        # capability claim (determiner + participle)
        root = make_package(
            desc="Includes a validated template for "
                 "reports.")
        _code, result, _ = run_json("audit", root)
        self.assertIsNone(
            claim_by_type(result, "capability"))

    def test_hyphenated_stem_is_not_a_capability(self):
        root = make_package(
            desc="A beat-synced cut engine for video.")
        _code, result, _ = run_json("audit", root)
        self.assertIsNone(
            claim_by_type(result, "capability"))

    def test_scoped_never_write_is_its_own_type(self):
        # "never write inside the project directory"
        # forbids a named place, not writing itself
        root = make_package(
            desc="Never write inside the project "
                 "directory.",
            scripts={"scripts/x.py": CLEAN_READER})
        _code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "no_writes_inside")
        self.assertIsNotNone(claim)
        self.assertIsNone(claim_by_type(result, "no_writes"))
        self.assertEqual(claim["verdict"], "SUPPORTED")

    def test_scoped_never_write_runtime_paths_unevidenced(self):
        # the real video-use shape: helpers write to a
        # computed edit_dir — static evidence cannot
        # place those writes inside the forbidden scope
        script = ("from pathlib import Path\n"
                  "out = Path('edit') / 'takes.md'\n"
                  "out.write_text('x')\n")
        root = make_package(
            desc="Never write inside the project "
                 "directory.",
            scripts={"scripts/x.py": script})
        code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "no_writes_inside")
        self.assertEqual(claim["verdict"], "UNEVIDENCED")
        self.assertEqual(code, 0)

    def test_scoped_never_write_package_relative_contradicted(self):
        script = ("import os\n"
                  "open(os.path.join(os.path.dirname("
                  "__file__), 'x.txt'), 'w').write('y')\n")
        root = make_package(
            desc="Never write inside the project "
                 "directory.",
            scripts={"scripts/x.py": script})
        code, result, _ = run_json("audit", root)
        claim = claim_by_type(result, "no_writes_inside")
        self.assertEqual(claim["verdict"], "CONTRADICTED")
        self.assertEqual(code, 1)


class ErrorContractTests(unittest.TestCase):

    def assert_clean_error(self, argv, json_mode=True):
        code, out, err = run_cli(*argv)
        self.assertEqual(code, 2, argv)
        self.assertNotIn("Traceback", out + err)
        if json_mode:
            payload = json.loads(out)
            self.assertIn("error", payload)
        return out, err

    def test_missing_dir(self):
        self.assert_clean_error(
            ["audit", "/nonexistent/nope", "--json"])

    def test_path_is_a_file(self):
        self.assert_clean_error(["audit", SRC, "--json"])

    def test_no_skill_md(self):
        root = tempfile.mkdtemp(prefix="skill-claims-test-")
        self.assert_clean_error(["audit", root, "--json"])

    def test_empty_dir(self):
        root = tempfile.mkdtemp(prefix="skill-claims-test-")
        self.assert_clean_error(["audit", root, "--json"])

    def test_empty_skill_md(self):
        root = make_package(desc="Works fully offline.")
        with open(os.path.join(root, "SKILL.md"), "w") as fh:
            fh.write("")
        self.assert_clean_error(["audit", root, "--json"])

    def test_no_frontmatter(self):
        root = make_package(desc="Works fully offline.")
        with open(os.path.join(root, "SKILL.md"), "w") as fh:
            fh.write("# Just a heading\n\nNo frontmatter.\n")
        self.assert_clean_error(["audit", root, "--json"])

    def test_malformed_frontmatter(self):
        root = make_package(desc="Works fully offline.")
        with open(os.path.join(root, "SKILL.md"), "w") as fh:
            fh.write("---\nname: test-skill\n"
                     "::: nonsense\n---\n\n# X\n")
        self.assert_clean_error(["audit", root, "--json"])

    def test_text_mode_error_is_clean(self):
        out, err = self.assert_clean_error(
            ["audit", "/nonexistent/nope"], json_mode=False)
        self.assertIn("ERROR:", out)

    def test_argparse_errors(self):
        code, out, err = run_cli()
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", out + err)
        code, out, err = run_cli("audit", "--json",
                                 "--bogus")
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out))
        self.assertNotIn("Traceback", out + err)


class SafetyProofTests(unittest.TestCase):

    def test_nothing_in_the_package_is_executed(self):
        marker_dir = tempfile.mkdtemp(
            prefix="skill-claims-test-")
        marker = os.path.join(marker_dir, "PWNED")
        booby = (
            "open(%r, 'w').write('ran')\n"
            "print('harmless')\n" % marker)
        root = make_package(
            desc="Prints a greeting.",
            scripts={"scripts/x.py": booby})
        run_cli("audit", root)
        self.assertFalse(os.path.exists(marker))

    def test_source_imports_are_pinned(self):
        with open(SRC, encoding="utf-8") as fh:
            source = fh.read()
        imported = set()
        for line in source.splitlines():
            line = line.strip()
            if line.startswith("import "):
                imported.update(
                    part.strip().split(".")[0].split(" as ")[0]
                    for part in line[len("import "):].split(","))
            elif line.startswith("from "):
                imported.add(
                    line[len("from "):].split(" ")[0]
                    .split(".")[0])
        self.assertEqual(
            imported, {"argparse", "json", "os", "re", "sys"})


if __name__ == "__main__":
    unittest.main()
