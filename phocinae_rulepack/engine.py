"""The decision engine.

`check` is a pure function: no I/O, no network, no clock, no randomness. Given
the same pack and document it returns byte-identical output, which is what makes
`dump_canonical` usable as a regression hash.

Aggregation (design section 4.1):

  * every rule that fires contributes an entry to ``reasons``
  * the document verdict is the **strictest** entry: fail > review > pass
  * a rule capped by an ``unavailable`` citation is downgraded to ``review``
    *before* aggregation and its reason code is prefixed ``CAPPED_``
  * ``pass`` requires at least one fired ``pass`` rule and no fired
    ``fail``/``review`` rule; a document where nothing fired is ``review``
    (``NO_RULE_MATCHED``). Nothing can fall through to a silent pass.
"""

from __future__ import annotations

import json

from .errors import (
    PackError,
    E_EMPTY_SCAN,
    E_INPUT_RECORD,
    E_NO_RULE_REACHES_INPUT,
    MISSING_FIELD,
    NO_RULE_MATCHED,
    CAPPED_UNAVAILABLE_CITATION,
)
from .expr import evaluate, resolve

_STRICTNESS = {"pass": 0, "review": 1, "fail": 2}

#: Fields the corpus can legitimately contain without any rule reading them.
#: `unmatched_paths` is an adapter-drift detector, so these would be noise.
_SILENT_PREFIXES = ("derived.",)


def _leaf_paths(value, prefix=""):
    """All scalar leaf paths of a document, in document order."""
    out = []
    if isinstance(value, dict):
        for key in value:
            out.extend(_leaf_paths(value[key], "%s%s." % (prefix, key) if prefix else "%s." % key))
        return out
    if isinstance(value, list):
        # Arrays are leaves: no rule addresses individual elements.
        return [prefix.rstrip(".")] if prefix else []
    return [prefix.rstrip(".")] if prefix else []


def _strictest(verdicts):
    return max(verdicts, key=lambda item: _STRICTNESS[item])


def _evidence_for(rule, document, outcome):
    """A short, stable, human-readable evidence string."""
    if outcome == "missing":
        return "missing:%s" % ",".join(
            path for path in rule.require_fields if not resolve(document, path)[0]
        )
    if outcome == "type_error":
        return "type:%s" % rule.id
    if outcome == "unknown":
        return "unknown:%s" % rule.id
    return "matched:%s" % rule.id


def check(pack, document):
    """Run one document through one pack. Returns the 5-key payload dict."""
    if document is None or (isinstance(document, dict) and not document):
        raise PackError(
            E_EMPTY_SCAN,
            "the input document is empty; an empty scan must not report success",
        )

    touched = set(pack.fields())
    present = [
        path
        for path in _leaf_paths(document)
        if not path.startswith(_SILENT_PREFIXES)
    ]
    if present and not any(path in touched for path in present):
        raise PackError(
            E_NO_RULE_REACHES_INPUT,
            "no rule in pack %r reads any field present in this document; the input and the "
            "pack do not talk about the same thing (fields present: %s)"
            % (pack.id, ", ".join(sorted(present)[:8]) or "none"),
        )

    reasons = []
    fired = []

    for rule in pack.rules:
        missing = [path for path in rule.require_fields if not resolve(document, path)[0]]
        if missing:
            if rule.on_missing == "fail":
                reasons.append(
                    _reason(rule, "fail", rule.reason_code, "missing:%s" % ",".join(missing), pack)
                )
                fired.append("fail")
            else:
                reasons.append(
                    _reason(rule, "review", MISSING_FIELD, "missing:%s" % ",".join(missing), pack)
                )
                fired.append("review")
            continue

        result = evaluate(rule.condition, document)
        if result.value is None:
            code = result.reason_code or MISSING_FIELD
            reasons.append(_reason(rule, "review", code, result.detail or _evidence_for(rule, document, "unknown"), pack))
            fired.append("review")
            continue
        if result.value is False:
            continue

        verdict = rule.verdict
        reason_code = rule.reason_code
        # An `unavailable` citation caps the rule at `review`, before aggregation.
        if verdict == "fail":
            capping = [cid for cid in rule.cite if pack.citation(cid) and pack.citation(cid).capped]
            if capping:
                verdict = "review"
                reason_code = "CAPPED_" + reason_code
                reasons.append(
                    _reason(
                        rule,
                        verdict,
                        reason_code,
                        "%s [citation %s is unavailable]"
                        % (_evidence_for(rule, document, "matched"), ",".join(capping)),
                        pack,
                    )
                )
                fired.append(verdict)
                continue
        reasons.append(_reason(rule, verdict, reason_code, _evidence_for(rule, document, "matched"), pack))
        fired.append(verdict)

    if not reasons:
        verdict = "review"
        reasons.append(
            {
                "rule": None,
                "verdict": "review",
                "reason_code": NO_RULE_MATCHED,
                "cite": [],
                "evidence": "no rule matched this document; a document that reached no rule "
                            "is not a compliant document",
            }
        )
    else:
        verdict = _strictest([entry["verdict"] for entry in reasons])

        # A `pass` reason beside a `fail` or `review` reason is a contradiction:
        # the pack reports both "no departure found" and a departure. Drop the
        # pass entries whenever something stricter fired.
        #
        # This is the engine's job, not the pack author's. Expressing it as an
        # extra condition on every pass rule would have to be repeated in every
        # pack and would be wrong the first time someone forgot; and a pack cannot
        # reliably express "no other rule fired" in the first place. Doing it here
        # also makes the invariant hold for packs written before this change.
        if verdict != "pass":
            filtered = [entry for entry in reasons if entry["verdict"] != "pass"]
            if filtered:
                reasons = filtered

    unmatched = sorted(
        path for path in present if path not in touched and not path.startswith(_SILENT_PREFIXES)
    )

    return {
        "rulepack": pack.id,
        "verdict": verdict,
        "reasons": reasons,
        "unmatched_paths": unmatched,
        "model_calls": 0,
    }


def _reason(rule, verdict, reason_code, evidence, pack):
    return {
        "rule": rule.id,
        "verdict": verdict,
        "reason_code": reason_code,
        "cite": list(rule.cite),
        "evidence": evidence,
    }


def check_many(pack, documents):
    """Run a ledger (sequence of documents) through one pack.

    Envelope semantics (adjudication OQ-3):
      * ``results[i]`` is exactly what ``check`` returns for record ``i``
      * ``unmatched_paths`` is the **intersection** across records (a path that
        appears in every record and is read by no rule is real adapter drift;
        a path that appears in one record is just an optional field)
      * ``model_calls`` is the sum
      * a record that cannot be parsed aborts the whole batch (``E_INPUT_RECORD``)
      * ``verdict`` is the strictest of the records
    """
    if documents is None:
        raise PackError(E_EMPTY_SCAN, "no records supplied")
    if isinstance(documents, dict):
        raise PackError(
            E_INPUT_RECORD,
            "expected a list of records (a ledger), got a single mapping; pass a list even "
            "for one record",
        )
    if len(documents) == 0:
        raise PackError(E_EMPTY_SCAN, "the ledger has 0 records")

    results = []
    for index, record in enumerate(documents):
        if not isinstance(record, dict):
            raise PackError(
                E_INPUT_RECORD,
                "record %d is %s, not a mapping" % (index, type(record).__name__),
            )
        if not record:
            raise PackError(E_EMPTY_SCAN, "record %d is empty" % index)
        results.append(check(pack, record))

    common = set(results[0]["unmatched_paths"])
    for entry in results[1:]:
        common &= set(entry["unmatched_paths"])

    return {
        "rulepack": pack.id,
        "verdict": _strictest([entry["verdict"] for entry in results]),
        "results": results,
        "unmatched_paths": sorted(common),
        "model_calls": 0,
    }


def dump_canonical(payload):
    """Canonical JSON bytes: sorted keys, UTF-8, no timestamps, trailing newline."""
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
