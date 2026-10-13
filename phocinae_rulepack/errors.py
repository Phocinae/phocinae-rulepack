"""Error types, exit codes, and the reason-code taxonomy.

Exit codes (design contract section 2.2, adjudication OQ-6):

    0  every result is `pass`
    1  at least one `fail`
    2  no `fail`, but at least one `review`  (grey zone -> human)
    3  usage / configuration error, OR an empty scan

Internal priority is fixed and total: 3 > 1 > 2 > 0. It is implemented in exactly
one place (:func:`exit_code`) so it is testable rather than described.
"""

from __future__ import annotations

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_REVIEW = 2
EXIT_USAGE = 3

EXIT_CODES = (EXIT_PASS, EXIT_FAIL, EXIT_REVIEW, EXIT_USAGE)


class PackError(Exception):
    """A pack-level or input-level error.

    ``args[0]`` is always the machine-readable reason code, so callers can map
    failures without parsing prose. ``args[1]`` is a human message.
    """

    def __init__(self, reason_code, message):
        self.reason_code = reason_code
        self.message = message
        super(PackError, self).__init__(reason_code, message)

    def __str__(self):
        return "%s: %s" % (self.reason_code, self.message)


# --------------------------------------------------------------------------
# Reason codes. Grouped by the stage that can raise them.
# --------------------------------------------------------------------------

# -- loading / schema (all exit 3) -----------------------------------------
E_YAML = "E_YAML"                                  # not parseable as YAML subset
E_SCHEMA = "E_SCHEMA"                              # shape/type violation
E_RULE = "E_RULE"                                  # rule is malformed
E_NO_RULES = "E_NO_RULES"                          # empty scan: rules == []
E_NO_CITATIONS = "E_NO_CITATIONS"                  # empty scan: citations == []
E_CITATION_NOT_FOUND = "E_CITATION_NOT_FOUND"      # quote absent from corpus
E_CITATION_NO_SOURCE_TEXT = "E_CITATION_NO_SOURCE_TEXT"
E_CORPUS_HASH_MISMATCH = "E_CORPUS_HASH_MISMATCH"
E_CORPUS_MISSING = "E_CORPUS_MISSING"
E_RULE_ON_MISSING = "E_RULE_ON_MISSING"            # on_missing: fail on a non-fail rule
E_EXPR = "E_EXPR"                                  # expression outside the subset
E_DERIVED_FIELDS = "E_DERIVED_FIELDS"              # reserved key seen in v0.1.0

# -- input (exit 3 for the whole-scan cases) --------------------------------
E_EMPTY_SCAN = "E_EMPTY_SCAN"                      # empty document / no records
E_NO_RULE_REACHES_INPUT = "E_NO_RULE_REACHES_INPUT"
E_INPUT_RECORD = "E_INPUT_RECORD"                  # one record failed to parse
E_INPUT_NOT_FOUND = "E_INPUT_NOT_FOUND"

# -- per-document verdict reasons (do NOT abort the run) --------------------
MISSING_FIELD = "MISSING_FIELD"
TYPE_ERROR = "TYPE_ERROR"
REF_UNRESOLVED = "REF_UNRESOLVED"
DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
NO_RULE_MATCHED = "NO_RULE_MATCHED"
CAPPED_UNAVAILABLE_CITATION = "CAPPED_UNAVAILABLE_CITATION"

#: Reason codes that mean "the tool is misconfigured or has nothing to check".
#: They abort the whole run with exit 3 instead of producing a verdict.
ABORT_CODES = frozenset(
    [
        E_YAML,
        E_SCHEMA,
        E_RULE,
        E_NO_RULES,
        E_NO_CITATIONS,
        E_CITATION_NOT_FOUND,
        E_CITATION_NO_SOURCE_TEXT,
        E_CORPUS_HASH_MISMATCH,
        E_CORPUS_MISSING,
        E_RULE_ON_MISSING,
        E_EXPR,
        E_DERIVED_FIELDS,
        E_EMPTY_SCAN,
        E_NO_RULE_REACHES_INPUT,
        E_INPUT_RECORD,
        E_INPUT_NOT_FOUND,
    ]
)

#: Reason codes that mark a grey zone (verdict `review`).
REVIEW_CODES = frozenset(
    [
        MISSING_FIELD,
        TYPE_ERROR,
        REF_UNRESOLVED,
        DIVISION_BY_ZERO,
        NO_RULE_MATCHED,
        CAPPED_UNAVAILABLE_CITATION,
    ]
)


def exit_code_for_verdict(verdict):
    """Map a single verdict to its exit code."""
    if verdict == "pass":
        return EXIT_PASS
    if verdict == "fail":
        return EXIT_FAIL
    if verdict == "review":
        return EXIT_REVIEW
    raise PackError(E_SCHEMA, "unknown verdict %r" % (verdict,))


def exit_code(payload):
    """Exit code for a check payload (single document or batch envelope).

    Priority is *fixed*: 3 > 1 > 2 > 0. Abort conditions are raised as
    :class:`PackError` before this is reached, so here we only combine
    per-result verdicts.
    """
    results = payload.get("results")
    if results is None:
        results = [payload]
    if not results:
        raise PackError(E_EMPTY_SCAN, "no results to score")
    codes = [exit_code_for_verdict(r["verdict"]) for r in results]
    for candidate in (EXIT_FAIL, EXIT_REVIEW, EXIT_PASS):
        if candidate in codes:
            return candidate
    raise PackError(E_SCHEMA, "no verdict mapped to an exit code")


def exit_code_for_reason(reason_code):
    """Exit code implied by an abort reason code (always 3 in v1)."""
    if reason_code in ABORT_CODES:
        return EXIT_USAGE
    return EXIT_USAGE
