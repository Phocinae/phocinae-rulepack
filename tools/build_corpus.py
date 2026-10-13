# -*- coding: utf-8 -*-
"""Generate the shipped packs' corpus files and rulepack.yaml from the real sources.

Corpus text is excerpted byte-exactly from the pinned origin files, and every
sha256 is *computed here* rather than typed by hand. That is the whole point:
a hand-typed hash is a number nobody can check, and a hand-retyped quote is the
classic way a "verbatim" claim silently stops being verbatim.
"""
import hashlib
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO = r"D:\Projects\phociane-project\_work\build\phocinae-rulepack"
SCREEN = r"D:\Projects\phociane-project\_work\staging\dsh-phocinae-screen"

RULEPACK_DIR = os.path.join(REPO, "phocinae_rulepack", "packs", "expense-policy")
SOURCES = os.path.join(RULEPACK_DIR, "sources")
FIXTURES = os.path.join(REPO, "tests", "fixtures")
os.makedirs(SOURCES, exist_ok=True)
os.makedirs(FIXTURES, exist_ok=True)


def sha256_of(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def read_lines(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().split("\n")


def excerpt(path, first, last):
    """1-based inclusive line excerpt, joined with \\n and a trailing newline."""
    lines = read_lines(path)
    return "\n".join(lines[first - 1:last]) + "\n"


mjs = os.path.join(SCREEN, "docs", "measure-expense-approval.mjs")
feas = os.path.join(SCREEN, "docs", "FEASIBILITY-expense.md")
assert os.path.isfile(mjs), mjs
assert os.path.isfile(feas), feas

origin_mjs_sha = sha256_of("\n".join(read_lines(mjs)))
origin_feas_sha = sha256_of("\n".join(read_lines(feas)))

# -- corpus A: the policy constants, lines 26-31 ----------------------------
policy_txt = excerpt(mjs, 26, 31)
# -- corpus B: the original rule function, lines 108-118 --------------------
rule_txt = excerpt(mjs, 108, 118)
# -- corpus C: the measured conclusion table -------------------------------
feas_lines = read_lines(feas)
start = None
for index, line in enumerate(feas_lines):
    if "纯规则" in line and line.strip().startswith("|"):
        start = index + 1
        break
assert start, "could not locate the three-form comparison table in FEASIBILITY-expense.md"
end = start
while end <= len(feas_lines) and feas_lines[end - 1].strip().startswith("|"):
    end += 1
feas_txt = "\n".join(feas_lines[start - 1:end - 1]) + "\n"

for name, text in (
    ("s15_policy_constants.txt", policy_txt),
    ("s15_rule_check.txt", rule_txt),
    ("s15_feasibility_excerpt.md", feas_txt),
):
    with open(os.path.join(SOURCES, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("wrote %-32s sha256=%s" % (name, sha256_of(text)))

# Verify the quotes we are about to declare are actually present, verbatim.
QUOTES = [
    ("c1", policy_txt, "receiptRequiredOver: 500,      // \u8d85\u8fc7 500 \u5fc5\u987b\u6709\u53d1\u7968"),
    ("c2", policy_txt, "caps: { meal: 300, taxi: 200, hotel: 1200, supplies: 800 },"),
    ("c3", policy_txt, "priorApprovalOver: 2000,       // \u8d85\u8fc7 2000 \u9700\u4e8b\u524d\u5ba1\u6279"),
    ("c4", rule_txt, "if (violations.length) return { verdict: 'reject', why: violations.join('; ') }"),
]
for cid, haystack, needle in QUOTES:
    ok = needle in haystack
    print("quote %s present verbatim: %s" % (cid, ok))
    assert ok, "quote %s not found verbatim" % cid

# -- the ledger -------------------------------------------------------------
CLAIMS = [
    ("c01", "meal", 880, False, False, "reject"),
    ("c02", "hotel", 3600, True, False, "reject"),
    ("c03", "supplies", 1450, True, False, "reject"),
    ("c04", "taxi", 640, False, False, "reject"),
    ("c05", "meal", 2400, True, False, "reject"),
    ("c06", "meal", 520, True, False, "reject"),
    ("c07", "meal", 260, False, False, "approve"),
    ("c08", "taxi", 88, False, False, "approve"),
    ("c09", "supplies", 320, False, False, "approve"),
    ("c10", "hotel", 1100, True, False, "approve"),
    ("c11", "meal", 300, False, False, "approve"),
    ("c12", "taxi", 180, False, False, "approve"),
    ("c13", "meal", 290, False, False, "approve"),
    ("c14", "supplies", 210, False, False, "approve"),
]
records = []
for cid, cat, amount, receipt, pre, label in CLAIMS:
    records.append(
        {
            "id": cid,
            "amount": amount,
            "category": cat,
            "receipt_attached": receipt,
            "prior_approval": pre,
            "expect_verdict": "fail" if label == "reject" else "pass",
            "expect_label": label,
        }
    )
with open(os.path.join(FIXTURES, "s15_claims.json"), "w", encoding="utf-8", newline="\n") as handle:
    json.dump(records, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("wrote tests/fixtures/s15_claims.json  (%d records, %d reject / %d approve)"
      % (len(records), sum(1 for r in records if r["expect_label"] == "reject"),
         sum(1 for r in records if r["expect_label"] == "approve")))

# -- emit the pack with computed hashes -------------------------------------
pack = {
    "path": "sources/s15_policy_constants.txt",
    "sha256": sha256_of(policy_txt),
    "role": "authority",
    "title": "S15 measured policy constants (byte-exact excerpt)",
    "origin": "dsh-phocinae-screen/docs/measure-expense-approval.mjs#L26-L31",
    "origin_sha256": origin_mjs_sha,
}
pack2 = {
    "path": "sources/s15_rule_check.txt",
    "sha256": sha256_of(rule_txt),
    "role": "authority",
    "title": "S15 original rule function (byte-exact excerpt)",
    "origin": "dsh-phocinae-screen/docs/measure-expense-approval.mjs#L108-L118",
    "origin_sha256": origin_mjs_sha,
}
pack3 = {
    "path": "sources/s15_feasibility_excerpt.md",
    "sha256": sha256_of(feas_txt),
    "role": "authority",
    "title": "S15 three-form comparison table (byte-exact excerpt)",
    "origin": "dsh-phocinae-screen/docs/FEASIBILITY-expense.md",
    "origin_sha256": origin_feas_sha,
}

meta = {"corpus": [pack, pack2, pack3]}
with open(os.path.join(RULEPACK_DIR, "corpus.json"), "w", encoding="utf-8", newline="\n") as handle:
    json.dump(meta, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("wrote corpus.json (hashes computed, not typed)")
print("origin sha256 mjs  =", origin_mjs_sha)
print("origin sha256 feas =", origin_feas_sha)
