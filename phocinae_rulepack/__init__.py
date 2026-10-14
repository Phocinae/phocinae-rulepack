"""phocinae-rulepack — deterministic rule-pack engine.

Read a ledger, apply a versioned rule pack, emit only the differences for human
review. Zero model calls, zero third-party runtime dependencies.

Design contract (see the project's design document, section 2):
  * three-state verdict: pass / fail / review
  * `review` is the grey-zone escalation to a human, not "look again later"
  * a missing field or an unmatched rule NEVER defaults to `pass` (fail-closed)
  * `model_calls` is a real counter and is always 0 here
  * an empty scan is a FAILURE, not a success
  * the same input produces byte-identical output
"""

from __future__ import annotations

from .errors import (
    PackError,
    EXIT_PASS,
    EXIT_FAIL,
    EXIT_REVIEW,
    EXIT_USAGE,
    EXIT_CODES,
    exit_code,
    exit_code_for_reason,
)
from .schema import Citation, Pack, Rule, load_pack, validate_pack, ValidationReport
from .engine import check, check_many, dump_canonical

__version__ = "0.1.2"

#: Verdict vocabulary. Ordered by strictness so aggregation is a max().
VERDICTS = ("pass", "review", "fail")

__all__ = [
    "__version__",
    "VERDICTS",
    # errors / exit codes
    "PackError",
    "EXIT_PASS",
    "EXIT_FAIL",
    "EXIT_REVIEW",
    "EXIT_USAGE",
    "EXIT_CODES",
    "exit_code",
    "exit_code_for_reason",
    # data model
    "Citation",
    "Pack",
    "Rule",
    "ValidationReport",
    "load_pack",
    "validate_pack",
    # engine
    "check",
    "check_many",
    "dump_canonical",
]
