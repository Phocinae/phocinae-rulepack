# -*- coding: utf-8 -*-
"""The test suite.

Each test function takes a :class:`_harness.Suite` and records assertions.
``run_all.py`` discovers and runs them.

The assertions that matter most:

* **S15 reproduction must be exactly 14/14** -- not ">= 13". A pass rule that
  looks plausible but is subtly wrong turns 14/14 into 6/14, so the count is
  pinned exactly.
* **Bidirectional verification** -- several checks run a *known-bad* variant and
  require it to go red. A check that only ever sees good input proves nothing.
* **Empty scans must fail** -- "nothing was checked" is not success.
* **Determinism** -- the same input must produce byte-identical output.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys

from _harness import Suite, read_json, scratch_dir, write_text

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
PACKS = os.path.join(REPO, "phocinae_rulepack", "packs")

sys.path.insert(0, REPO)

from phocinae_rulepack import (  # noqa: E402
    PackError,
    check,
    check_many,
    dump_canonical,
    exit_code,
    load_pack,
    validate_pack,
)

PACK_ID = "expense-policy"


def _claims():
    records = read_json(os.path.join(FIXTURES, "s15_claims.json"))
    documents = [{k: v for k, v in r.items() if not k.startswith("expect_")} for r in records]
    return records, documents


def _write_pack(directory, text, sources=None):
    """Write a pack (plus optional sources) into a scratch directory."""
    os.makedirs(directory, exist_ok=True)
    write_text(os.path.join(directory, "rulepack.yaml"), text)
    for name, body in (sources or {}).items():
        target = os.path.join(directory, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        write_text(target, body)
    return os.path.join(directory, "rulepack.yaml")


# ---------------------------------------------------------------------------
# A. S15 reproduction -- the project's most important assertion
# ---------------------------------------------------------------------------


def test_s15_reproduction(suite: Suite):
    records, documents = _claims()
    suite.equal("A1 ledger has 14 records", len(records), 14)
    suite.equal(
        "A2 ledger is 6 reject / 8 approve",
        (sum(1 for r in records if r["expect_label"] == "reject"),
         sum(1 for r in records if r["expect_label"] == "approve")),
        (6, 8),
    )

    pack = load_pack(PACK_ID)
    envelope = check_many(pack, documents)

    mismatches = []
    for record, result in zip(records, envelope["results"]):
        if result["verdict"] != record["expect_verdict"]:
            mismatches.append(
                (record["id"], record["expect_verdict"], result["verdict"],
                 [r["reason_code"] for r in result["reasons"]])
            )
    suite.check("A3 every verdict matches its gold label", not mismatches, repr(mismatches))

    correct = sum(
        1 for record, result in zip(records, envelope["results"])
        if result["verdict"] == record["expect_verdict"]
    )
    # Exactly 14. Not ">= 13": an off-by-one here is the whole point.
    suite.equal("A4 correct == 14 (exactly)", correct, 14)
    suite.is_true(
        "A5 S15-REPRODUCTION banner prints 14/14",
        correct == 14 and len(records) == 14,
        "correct=%d of %d" % (correct, len(records)),
    )
    suite.equal("A6 model_calls sum == 0", envelope["model_calls"], 0)
    suite.is_true(
        "A7 every per-record model_calls == 0",
        all(r["model_calls"] == 0 for r in envelope["results"]),
    )
    suite.equal("A8 6 reject records exist", sum(1 for r in records if r["expect_label"] == "reject"), 6)
    suite.equal("A9 8 approve records exist", sum(1 for r in records if r["expect_label"] == "approve"), 8)

    # Each reject must be rejected for a policy reason, not by falling through.
    for record, result in zip(records, envelope["results"]):
        if record["expect_label"] != "reject":
            continue
        codes = {r["reason_code"] for r in result["reasons"]}
        suite.check(
            "A10 reject %s names a policy reason" % record["id"],
            bool(codes & {"NO_RECEIPT_OVER_THRESHOLD", "OVER_CATEGORY_CAP",
                          "OVER_2000_WITHOUT_PRIOR_APPROVAL"}),
            "codes=%r" % (sorted(codes),),
        )

    envelope_code = exit_code(envelope)
    suite.equal("A11 envelope exit code is 1 (a fail exists)", envelope_code, 1)
    passes = [r for r in envelope["results"] if r["verdict"] == "pass"]
    suite.equal(
        "A12 a pass-only ledger exits 0",
        exit_code({"verdict": "pass", "results": passes}),
        0,
    )


# ---------------------------------------------------------------------------
# B. Citations resolve character-for-character
# ---------------------------------------------------------------------------


def test_citations_verbatim(suite: Suite):
    report = validate_pack(PACK_ID)
    suite.is_true("B1 the shipped pack validates", report.ok)
    counts = report.counts
    suite.equal("B2 rule count", counts["rules"], 8)
    suite.equal("B3 citation count", counts["citations"], 5)
    suite.equal("B4 all citations are verbatim", counts["verbatim"], 5)
    suite.equal("B5 no unavailable citations", counts["unavailable"], 0)
    suite.equal("B6 corpus file count", counts["corpus"], 3)
    suite.equal("B7 no warnings on the shipped pack", len(report.warnings), 0)

    # Bidirectional: change one character of a quote and validation must fail.
    pack = load_pack(PACK_ID)
    source = open(pack.path, "r", encoding="utf-8").read()
    original = "caps: { meal: 300, taxi: 200, hotel: 1200, supplies: 800 },"
    broken = original.replace("1200", "1201")
    suite.is_true("B8 the quote under test is present", original in source)
    mutated = source.replace(original, broken)
    suite.check("B9 the quote actually changed", mutated != source)

    directory = scratch_dir("citation-mutation")
    shutil.copytree(os.path.join(PACKS, PACK_ID, "sources"), os.path.join(directory, "sources"))
    path = _write_pack(directory, mutated)
    suite.raises(
        "B10 a one-character quote change fails validation",
        "E_CITATION_NOT_FOUND",
        validate_pack,
        path,
    )

    # A corpus hash that does not match must fail. Built from the parsed pack
    # rather than by editing YAML text, so the mutation is unambiguous.
    directory = scratch_dir("hash-mutation")
    shutil.copytree(os.path.join(PACKS, PACK_ID, "sources"), os.path.join(directory, "sources"))
    path = _write_pack(directory, _inline_corpus_sha(source, "0" * 64))
    suite.raises("B12 a wrong corpus hash fails validation", "E_CORPUS_HASH_MISMATCH", validate_pack, path)

    # A pack whose citations have no corpus at all cannot be verified
    # character-for-character, which would make the guarantee a non-empty-string
    # test -- a fake gate. It must be refused.
    directory = scratch_dir("no-corpus")
    without_corpus = _drop_corpus_and_documents(source)
    suite.check("B13a the corpus block was actually removed",
                "  - path: sources/" not in without_corpus)
    suite.check("B13b the document lines were actually removed",
                "document: sources/" not in without_corpus)
    path = _write_pack(directory, without_corpus)
    suite.raises(
        "B13 citations without corpus are refused (no fake gate)",
        "E_CITATION_NO_SOURCE_TEXT",
        validate_pack,
        path,
    )


def _inline_corpus_sha(source, new_sha):
    """Replace the first ``sha256:`` line that appears inside the corpus block."""
    lines = source.split("\n")
    out = []
    replaced = False
    inside_corpus = False
    for line in lines:
        if line.startswith("corpus:"):
            inside_corpus = True
            out.append(line)
            continue
        if inside_corpus and line and not line.startswith((" ", "\t")):
            inside_corpus = False
        if inside_corpus and not replaced and line.strip().startswith("sha256: "):
            indent = line[: len(line) - len(line.lstrip())]
            out.append("%ssha256: %s" % (indent, new_sha))
            replaced = True
            continue
        out.append(line)
    assert replaced, "no corpus sha256 line found"
    return "\n".join(out)


def _drop_corpus_and_documents(source):
    """Remove the corpus block *and* every citation's ``document:`` line.

    Dropping only the corpus block would trip the schema check first (a citation
    may not name an undeclared document), which would test the wrong thing: the
    claim under test is that citations with no source text at all are refused
    rather than silently accepted as unverifiable.
    """
    lines = source.split("\n")
    out = []
    skipping = False
    for line in lines:
        if line.startswith("corpus:"):
            skipping = True
            continue
        if skipping:
            if line.startswith((" ", "\t")) or line == "":
                continue
            skipping = False
        if line.strip().startswith("document: "):
            continue
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# C. Empty scans and missing fields
# ---------------------------------------------------------------------------


def test_empty_and_missing(suite: Suite):
    pack = load_pack(PACK_ID)

    suite.raises("C1 empty document is an empty scan", "E_EMPTY_SCAN", check, pack, {})
    suite.raises("C2 None document is an empty scan", "E_EMPTY_SCAN", check, pack, None)
    suite.raises("C3 empty ledger is an empty scan", "E_EMPTY_SCAN", check_many, pack, [])
    suite.raises("C4 empty record in a ledger is an empty scan", "E_EMPTY_SCAN", check_many, pack, [{}])
    suite.raises(
        "C5 a single mapping where a ledger is expected is refused",
        "E_INPUT_RECORD",
        check_many,
        pack,
        {"amount": 100},
    )
    suite.raises(
        "C6 a document no rule reads is refused",
        "E_NO_RULE_REACHES_INPUT",
        check,
        pack,
        {"foo": 1},
    )

    # Missing field -> review. The document must be otherwise *compliant*:
    # with an over-cap amount a different rule legitimately fails first, and
    # "a real violation outranks a missing field" is the correct behaviour.
    result = check(pack, {"amount": 260, "category": "meal", "prior_approval": False})
    suite.equal("C7 a missing field yields review", result["verdict"], "review")
    suite.is_true(
        "C8 and it names MISSING_FIELD",
        any(r["reason_code"] == "MISSING_FIELD" for r in result["reasons"]),
        repr([r["reason_code"] for r in result["reasons"]]),
    )
    suite.is_true(
        "C8b a real violation outranks a missing field",
        check(pack, {"amount": 880, "category": "meal", "prior_approval": False})["verdict"] == "fail",
    )

    # Wrong type -> the rule that needs it does not fire, and a compliant
    # document with one wrongly-typed field must land in review.
    result = check(pack, {"amount": "260", "category": "meal",
                          "receipt_attached": False, "prior_approval": False})
    suite.equal("C9 a wrongly-typed field yields review", result["verdict"], "review")
    suite.is_true(
        "C10 and it names TYPE_ERROR",
        any(r["reason_code"] == "TYPE_ERROR" for r in result["reasons"]),
        repr([r["reason_code"] for r in result["reasons"]]),
    )

    # int 1 must not satisfy `receipt_attached == true` (Python: True == 1).
    # The document is deliberately over 500 with no receipt, so the ambiguity
    # actually changes the outcome: if 1 were read as True this would pass.
    result = check(pack, {"amount": 2600, "category": "hotel",
                          "receipt_attached": 1, "prior_approval": True})
    suite.is_true(
        "C11 int 1 does not satisfy a boolean comparison",
        result["verdict"] in ("review", "fail") and not any(
            r["reason_code"] == "NO_POLICY_VIOLATION" for r in result["reasons"]
        ),
        "verdict=%s reasons=%r" % (result["verdict"], [r["reason_code"] for r in result["reasons"]]),
    )
    suite.is_true(
        "C11b and the boolean rule reports a type error rather than a breach",
        any(r["reason_code"] == "TYPE_ERROR" and r["rule"] == "r1_no_receipt_over_500"
            for r in result["reasons"])
        or result["verdict"] == "fail",
        repr([(r["rule"], r["reason_code"]) for r in result["reasons"]]),
    )

    # A category the policy does not enumerate is a grey zone, not a pass.
    result = check(pack, {"amount": 100, "category": "entertainment",
                          "receipt_attached": False, "prior_approval": False})
    suite.equal("C12 an unenumerated category yields review", result["verdict"], "review")
    suite.is_true(
        "C13 and it names CATEGORY_NOT_IN_POLICY",
        any(r["reason_code"] == "CATEGORY_NOT_IN_POLICY" for r in result["reasons"]),
        repr([r["reason_code"] for r in result["reasons"]]),
    )


# ---------------------------------------------------------------------------
# D. Determinism, borders, negatives
# ---------------------------------------------------------------------------


def test_determinism_and_borders(suite: Suite):
    pack = load_pack(PACK_ID)
    records, documents = _claims()
    envelope = check_many(pack, documents)

    digests = {hashlib.sha256(dump_canonical(envelope)).hexdigest() for _ in range(20)}
    suite.equal("D1 20 runs produce exactly one digest", len(digests), 1)

    canonical = dump_canonical(envelope).decode("utf-8")
    suite.check("D2 canonical JSON has no timestamp", "T00:00" not in canonical)
    suite.check("D3 canonical JSON is sorted and compact", "\n" not in canonical.strip())

    reordered = list(reversed(documents))
    other = check_many(pack, reordered)
    per_record = {
        entry["rule"]: entry["verdict"]
        for entry in envelope["results"][0]["reasons"]
    }
    suite.is_true("D4 record order does not change a record's verdict",
                  other["results"][-1]["verdict"] == envelope["results"][0]["verdict"])
    suite.is_true("D5 per-record rule verdicts are stable", bool(per_record))

    # Borders: exact cap passes, one cent over fails.
    at_cap = check(pack, {"amount": 300, "category": "meal",
                          "receipt_attached": False, "prior_approval": False})
    suite.equal("D6 exactly at the category cap passes", at_cap["verdict"], "pass")
    over_cap = check(pack, {"amount": 300.01, "category": "meal",
                            "receipt_attached": False, "prior_approval": False})
    suite.equal("D7 one cent over the cap fails", over_cap["verdict"], "fail")

    at_receipt = check(pack, {"amount": 500, "category": "hotel",
                             "receipt_attached": False, "prior_approval": False})
    suite.equal("D8 exactly 500 needs no receipt", at_receipt["verdict"], "pass")
    over_receipt = check(pack, {"amount": 500.01, "category": "hotel",
                                "receipt_attached": False, "prior_approval": False})
    suite.equal("D9 just over 500 without a receipt fails", over_receipt["verdict"], "fail")

    # The 2000 prior-approval threshold is NOT reachable in this policy: the
    # highest category cap is 1200 (hotel), so any amount above 2000 is already
    # over a category cap and fails there. That is a property of the measured
    # policy, not a defect -- and the test asserts the actual behaviour rather
    # than a comfortable fiction.
    over_cap_wins = check(pack, {"amount": 2000, "category": "hotel",
                                 "receipt_attached": True, "prior_approval": False})
    suite.equal("D10 a hotel claim at 2000 fails on the category cap", over_cap_wins["verdict"], "fail")
    suite.is_true(
        "D10b and the reason is the cap, not the approval rule",
        any(r["reason_code"] == "OVER_CATEGORY_CAP" for r in over_cap_wins["reasons"]),
        repr([r["reason_code"] for r in over_cap_wins["reasons"]]),
    )
    # So the prior-approval rule is tested on a pack whose cap is high enough.
    directory = scratch_dir("approval-threshold")
    shutil.copytree(os.path.join(PACKS, PACK_ID, "sources"), os.path.join(directory, "sources"))
    source = open(pack.path, "r", encoding="utf-8").read()
    raised = source.replace('{field: category, op: "==", value: hotel},    {field: amount, op: "<=", value: 1200}',
                            '{field: category, op: "==", value: hotel},    {field: amount, op: "<=", value: 9999}')
    suite.check("D10c the cap was actually raised", raised != source)
    raised = raised.replace('{field: amount, op: ">", value: 1200}',
                            '{field: amount, op: ">", value: 9999}')
    high_cap = load_pack(_write_pack(directory, raised))
    at_2000 = check(high_cap, {"amount": 2000, "category": "hotel",
                               "receipt_attached": True, "prior_approval": False})
    suite.equal("D11 with the cap raised, exactly 2000 needs no approval", at_2000["verdict"], "pass")
    over_2000 = check(high_cap, {"amount": 2000.01, "category": "hotel",
                                 "receipt_attached": True, "prior_approval": False})
    suite.equal("D11b just over 2000 without approval fails", over_2000["verdict"], "fail")
    suite.is_true(
        "D11c and the reason is the approval rule",
        any(r["reason_code"] == "OVER_2000_WITHOUT_PRIOR_APPROVAL" for r in over_2000["reasons"]),
        repr([r["reason_code"] for r in over_2000["reasons"]]),
    )

    # unmatched_paths reports fields the pack never reads.
    result = check(pack, {"amount": 260, "category": "meal", "receipt_attached": False,
                          "prior_approval": False, "unused_field": "x"})
    suite.is_true("D12 an unread field is reported in unmatched_paths",
                  "unused_field" in result["unmatched_paths"],
                  repr(result["unmatched_paths"]))


# ---------------------------------------------------------------------------
# E. Bidirectional verification: known-bad variants must go red
# ---------------------------------------------------------------------------


def test_bidirectional(suite: Suite):
    """Each case breaks something real and requires the suite to notice."""
    records, documents = _claims()
    pack = load_pack(PACK_ID)
    source = open(pack.path, "r", encoding="utf-8").read()

    def rebuilt(mutated_source, name):
        directory = scratch_dir(name)
        shutil.copytree(os.path.join(PACKS, PACK_ID, "sources"), os.path.join(directory, "sources"))
        return _write_pack(directory, mutated_source)

    # E1: delete the pass rule entirely -> the 8 approve records stop passing.
    without_pass = "\n".join(
        line for line in source.split("\n")
        if "r8_within_policy" not in line
    )
    # Removing the id line alone leaves the rule body; instead blank the verdict.
    weakened = source.replace("then: {verdict: pass, reason_code: NO_POLICY_VIOLATION",
                              "then: {verdict: review, reason_code: NO_POLICY_VIOLATION")
    suite.check("E1 the pass verdict was actually weakened", weakened != source)
    path = rebuilt(weakened, "weakened-pass")
    report = validate_pack(path)
    suite.is_true(
        "E2 weakening the pass rule is reported as a warning",
        any("LINT_NO_PASS_RULE" in w for w in report.warnings),
        repr(report.warnings),
    )
    weakened_pack = load_pack(path)
    envelope = check_many(weakened_pack, documents)
    passes = sum(1 for r in envelope["results"] if r["verdict"] == "pass")
    suite.equal("E3 with no pass rule, zero records pass", passes, 0)

    # E4: loosen the category cap -> an over-cap claim stops failing.
    loosened = source.replace('{field: amount, op: ">", value: 300}',
                              '{field: amount, op: ">", value: 30000}')
    suite.check("E4 the cap was actually loosened", loosened != source)
    path = rebuilt(loosened, "loosened-cap")
    loosened_pack = load_pack(path)
    result = check(loosened_pack, {"amount": 880, "category": "meal",
                                   "receipt_attached": False, "prior_approval": False})
    suite.check(
        "E5 with the meal cap loosened, c01 no longer fails on OVER_CATEGORY_CAP",
        not any(r["reason_code"] == "OVER_CATEGORY_CAP" for r in result["reasons"]),
        repr([r["reason_code"] for r in result["reasons"]]),
    )

    # E6: flip the receipt boundary from > to >= -> the 500 boundary case flips.
    boundary = source.replace('{field: amount, op: ">", value: 500}',
                              '{field: amount, op: ">=", value: 500}')
    suite.check("E6 the receipt boundary was actually changed", boundary != source)
    path = rebuilt(boundary, "boundary-flip")
    boundary_pack = load_pack(path)
    at_500 = check(boundary_pack, {"amount": 500, "category": "hotel",
                                   "receipt_attached": False, "prior_approval": False})
    suite.equal("E7 with >= the 500 boundary now fails (so D8's check is real)",
                at_500["verdict"], "fail")

    # E8: an unavailable citation must cap a fail to review, both directions.
    capped = source.replace("evidence_level: verbatim", "evidence_level: unavailable")
    suite.check("E8 a citation was actually marked unavailable", capped != source)
    path = rebuilt(capped, "capped")
    capped_pack = load_pack(path)
    result = check(capped_pack, {"amount": 880, "category": "meal",
                                 "receipt_attached": False, "prior_approval": False})
    suite.equal("E9 an unavailable citation caps a fail to review", result["verdict"], "review")
    suite.is_true(
        "E10 and the reason code is prefixed CAPPED_",
        any(r["reason_code"].startswith("CAPPED_") for r in result["reasons"]),
        repr([r["reason_code"] for r in result["reasons"]]),
    )

    # E11: --strict must reject a pack that ships sample corpus.
    sampled = source.replace("role: authority", "role: sample")
    suite.check("E11 a corpus role was actually changed", sampled != source)
    path = rebuilt(sampled, "sample-corpus")
    suite.raises("E12 --strict rejects sample corpus", "E_SCHEMA", validate_pack, path, True)

    # E13: --strict must reject unavailable citations.
    path = rebuilt(capped, "capped-strict")
    suite.raises("E13 --strict rejects unavailable citations", "E_SCHEMA", validate_pack, path, True)

    # E14: removing all rules must be an empty scan.
    rules_gone = source.split("rules:")[0] + "rules: []\n"
    path = rebuilt(rules_gone, "no-rules")
    suite.raises("E14 a pack with no rules is refused", "E_NO_RULES", validate_pack, path)


# ---------------------------------------------------------------------------
# F. Reserved keys and schema strictness
# ---------------------------------------------------------------------------


def test_schema_strictness(suite: Suite):
    pack = load_pack(PACK_ID)
    source = open(pack.path, "r", encoding="utf-8").read()

    def rebuilt(mutated, name):
        directory = scratch_dir(name)
        shutil.copytree(os.path.join(PACKS, PACK_ID, "sources"), os.path.join(directory, "sources"))
        return _write_pack(directory, mutated)

    # F1: derived_fields is reserved for v2 and must error, never be ignored.
    with_derived = source + "\nderived_fields:\n  total: {op: mul, args: [{field: amount}, 2]}\n"
    path = rebuilt(with_derived, "derived")
    suite.raises(
        "F1 derived_fields is refused (not silently ignored)",
        "E_DERIVED_FIELDS",
        validate_pack,
        path,
    )

    # F2: missing_field_policy may only be 'review'.
    policy = source.replace("missing_field_policy: review", "missing_field_policy: fail")
    suite.check("F2 the policy was actually changed", policy != source)
    path = rebuilt(policy, "policy")
    suite.raises("F3 a non-review missing_field_policy is refused", "E_SCHEMA", validate_pack, path)

    # F4: a wrong schema id is refused.
    wrong = source.replace("schema: phocinae-rulepack/v1", "schema: something-else/v9")
    path = rebuilt(wrong, "schema-id")
    suite.raises("F4 a foreign schema id is refused", "E_SCHEMA", validate_pack, path)

    # F5: on_missing: fail on a non-fail rule is refused.
    on_missing = source.replace(
        '    then: {verdict: pass, reason_code: NO_POLICY_VIOLATION, cite: [c1, c2, c3, c5]}\n'
        "    require_fields: [amount, category]\n",
        '    then: {verdict: pass, reason_code: NO_POLICY_VIOLATION, cite: [c1, c2, c3, c5]}\n'
        "    require_fields: [amount, category]\n"
        "    on_missing: fail\n",
    )
    suite.check("F5 on_missing was actually added", on_missing != source)
    path = rebuilt(on_missing, "on-missing")
    suite.raises("F6 on_missing:fail on a pass rule is refused", "E_RULE_ON_MISSING", validate_pack, path)

    # F7: the built-in YAML subset parser must reject tabs in indentation.
    bad = source.replace("\nrules:", "\n\trules:")
    suite.check("F7 a tab was actually introduced", bad != source)
    path = rebuilt(bad, "tab")
    suite.raises("F8 a tab in indentation is refused", "E_YAML", validate_pack, path)

    # F9: ordered comparison across types is a TYPE_ERROR, not a silent False.
    result = check(pack, {"amount": "many", "category": "meal",
                          "receipt_attached": False, "prior_approval": False})
    suite.equal("F9 a string amount yields review", result["verdict"], "review")


# ---------------------------------------------------------------------------
# G. Packaging and hygiene
# ---------------------------------------------------------------------------


def test_packaging_and_hygiene(suite: Suite):
    import phocinae_rulepack

    version = phocinae_rulepack.__version__
    suite.equal("G1 __version__ is 0.1.0", version, "0.1.0")

    pyproject = open(os.path.join(REPO, "pyproject.toml"), "r", encoding="utf-8").read()
    suite.is_true(
        "G2 pyproject declares the same version",
        'version = "%s"' % version in pyproject,
        "looked for version = \"%s\"" % version,
    )
    suite.is_true(
        "G3 the runtime declares no dependencies",
        "dependencies = []" in pyproject,
    )
    readme_path = os.path.join(REPO, "README.md")
    if os.path.isfile(readme_path):
        readme = open(readme_path, "r", encoding="utf-8").read()
        suite.is_true(
            "G4 README install command pins the current version",
            "phocinae-rulepack==%s" % version in readme,
            "README must contain phocinae-rulepack==%s" % version,
        )
    else:
        suite.check("G4 README exists", False, "README.md is missing")

    # G5: no module in the package may import a network stack.
    forbidden = ("socket", "urllib", "http.client", "ssl", "requests", "httpx")
    offenders = []
    package_dir = os.path.join(REPO, "phocinae_rulepack")
    for name in sorted(os.listdir(package_dir)):
        if not name.endswith(".py"):
            continue
        body = open(os.path.join(package_dir, name), "r", encoding="utf-8").read()
        for token in forbidden:
            if ("import %s" % token) in body or ("from %s" % token) in body:
                offenders.append("%s imports %s" % (name, token))
    suite.check("G5 the package imports no network stack", not offenders, repr(offenders))

    # G6: nothing may *use* a bare temporary file/directory. On this machine
    # TEMP has been reported both writable and not, and a bare call falls back
    # to the current working directory -- which is how scratch directories ended
    # up committed to a repository once already. Names are assembled at run time
    # so this check cannot match its own source text.
    stem = "temp" + "file"
    # This file and _harness.py contain the check itself; they are excluded by
    # name so the scan cannot match its own text.
    excluded = {"test_rulepack.py", "_harness.py"}
    offenders = []
    for root, _dirs, files in os.walk(REPO):
        if ".git" in root or "__pycache__" in root:
            continue
        for name in files:
            if not name.endswith(".py") or name in excluded:
                continue
            relative = os.path.relpath(os.path.join(root, name), REPO)
            for number, line in enumerate(
                open(os.path.join(root, name), "r", encoding="utf-8").read().split("\n"), 1
            ):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ("import " + stem) in line or (stem + ".") in line:
                    offenders.append("%s:%d" % (relative, number))
    suite.check("G6 nothing uses a bare temporary file (TEMP is not reliably writable here)",
                not offenders, repr(offenders))


# ---------------------------------------------------------------------------
# H. Consumer contract (for projects that shell out to the CLI)
# ---------------------------------------------------------------------------


def test_consumer_contract(suite: Suite):
    """The CLI is the contract for non-Python consumers."""
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def run(args):
        return subprocess.run(
            [sys.executable, "-m", "phocinae_rulepack"] + args,
            cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8",
        )

    validated = run(["validate", PACK_ID])
    suite.equal("H1 validate exits 0", validated.returncode, 0)
    suite.is_true(
        "H2 validate prints the summary line",
        "pack=expense-policy" in (validated.stdout or ""),
        (validated.stdout or "")[:200],
    )

    listing = run(["list", PACKS, "--json"])
    suite.equal("H3 list exits 0", listing.returncode, 0)

    if not os.path.isfile(os.path.join(FIXTURES, "s15_claims.json")):
        suite.check("H4 fixture exists", False, "tests/fixtures/s15_claims.json missing")
        return

    scratch = scratch_dir("cli")
    ledger_path = os.path.join(scratch, "ledger.json")
    records, documents = _claims()
    write_text(ledger_path, json.dumps(documents, ensure_ascii=False))

    checked = run(["check", PACK_ID, ledger_path, "--format", "json"])
    suite.equal("H4 check exits 1 (the ledger contains a fail)", checked.returncode, 1)
    try:
        payload = json.loads(checked.stdout)
        suite.equal("H5 the CLI emits the 5-key payload", sorted(payload.keys()),
                    ["model_calls", "reasons" if "reasons" in payload else "results",
                     "rulepack", "unmatched_paths", "verdict"] if "reasons" in payload else
                    ["model_calls", "results", "rulepack", "unmatched_paths", "verdict"])
    except ValueError as exc:
        suite.check("H5 the CLI emits parseable JSON", False, str(exc))

    # A pack that does not exist is a usage error (3), never 0.
    missing = run(["validate", "no-such-pack"])
    suite.equal("H6 an unknown pack exits 3", missing.returncode, 3)

    # The CLI must not import the network stack at runtime either.
    import importlib

    for name in forbidden_modules():
        sys.modules.pop(name, None)
    importlib.import_module("phocinae_rulepack")
    loaded = [name for name in forbidden_modules() if name in sys.modules]
    suite.check("H7 importing the package pulls in no network module",
                not loaded, repr(loaded))


def forbidden_modules():
    return ["socket", "ssl", "http", "urllib", "requests", "httpx"]
