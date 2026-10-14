# -*- coding: utf-8 -*-
"""Behavioural tests for the two packs added after 0.1.0.

`expense-policy` is covered by the existing suite (and its 14/14 battery).
These check the two new packs against realistic records, and pin the two things
that are easy to get wrong:

  * `filing-requirements` r12 uses a field-to-field comparison (`{"ref": ...}`),
    which is the only place in any shipped pack where a rule compares two input
    fields. If that stops working, copies-vs-defendants silently stops failing.
  * `eu-label` reads nested fields (`fields.name`, `vision.name`) and compares
    them to a `{"ref": ...}`. A typo in a path becomes MISSING_FIELD/review,
    which looks like caution rather than a bug -- so the happy path is asserted
    explicitly.
"""

from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from phocinae_rulepack import check, exit_code, load_pack  # noqa: E402

PASSED = 0
FAILED = []


def ok(label, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        return True
    FAILED.append((label, detail))
    return False


def eq(label, actual, expected):
    return ok(label, actual == expected, "expected %r, got %r" % (expected, actual))


def reasons(result):
    return sorted(r["reason_code"] for r in result["reasons"])


# ---------------------------------------------------------------------------
# filing-requirements
# ---------------------------------------------------------------------------


def _compliant_filing():
    return {
        "case": {"type": "civil_first_instance", "court": "某区人民法院"},
        "complaint": {
            "present": True,
            "plaintiff_identity_complete": True,
            "defendant_identity_complete": True,
            "claims_and_facts": True,
            "evidence_and_sources": True,
            "witness_details_required": False,
            "witness_details_present": False,
            "copies_submitted": 3,
            "defendants_count": 2,
            "attachments": {
                "identity_proof": True,
                "authority_of_agent": True,
                "service_address_for_defendant": True,
                "evidence_materials": True,
            },
        },
    }


def test_filing_requirements():
    pack = load_pack("filing-requirements")

    good = check(pack, _compliant_filing())
    eq("F1 a compliant filing passes", good["verdict"], "pass")
    eq("F2 and says so with NO_REQUIREMENT_GAP", reasons(good), ["NO_REQUIREMENT_GAP"])
    eq("F3 exit code 0", exit_code(good), 0)

    # The field-to-field comparison: copies must be >= defendant count.
    short = _compliant_filing()
    short["complaint"]["copies_submitted"] = 1
    result = check(pack, short)
    eq("F4 too few copies fails", result["verdict"], "fail")
    eq("F5 with the copies reason code", reasons(result),
       ["COPIES_FEWER_THAN_DEFENDANTS"])
    eq("F6 exit code 1", exit_code(result), 1)

    # Exactly equal is enough ("与...人数相符").
    equal = _compliant_filing()
    equal["complaint"]["copies_submitted"] = 2
    eq("F7 copies == defendants passes", check(pack, equal)["verdict"], "pass")
    one_more = _compliant_filing()
    one_more["complaint"]["copies_submitted"] = 3
    eq("F8 one spare copy still passes", check(pack, one_more)["verdict"], "pass")

    # A missing required item escalates; it does not fail. Article 7 makes the
    # remedy a notice to supplement, not a refusal.
    missing = _compliant_filing()
    missing["complaint"]["attachments"]["identity_proof"] = False
    result = check(pack, missing)
    eq("F9 a missing attachment is review, not fail", result["verdict"], "review")
    eq("F10 with MISSING_REQUIRED_ITEM", reasons(result), ["MISSING_REQUIRED_ITEM"])
    eq("F11 exit code 2", exit_code(result), 2)

    # Both at once: the deterministic breach outranks the escalation.
    both = _compliant_filing()
    both["complaint"]["copies_submitted"] = 1
    both["complaint"]["attachments"]["evidence_materials"] = False
    result = check(pack, both)
    eq("F12 a real breach outranks a missing item", result["verdict"], "fail")
    eq("F13 and both are reported", reasons(result),
       ["COPIES_FEWER_THAN_DEFENDANTS", "MISSING_REQUIRED_ITEM"])

    # Witness required but details absent.
    witness = _compliant_filing()
    witness["complaint"]["witness_details_required"] = True
    result = check(pack, witness)
    eq("F14 a named witness without details is review", result["verdict"], "review")

    # Out of scope case type.
    other = _compliant_filing()
    other["case"]["type"] = "other"
    result = check(pack, other)
    eq("F15 an out-of-scope case type is review", result["verdict"], "review")
    ok("F16 and it names OUT_OF_SCOPE_CASE_TYPE",
       "OUT_OF_SCOPE_CASE_TYPE" in reasons(result), repr(reasons(result)))

    # The ref must resolve; a missing side is review, not a silent pass.
    unresolved = _compliant_filing()
    del unresolved["complaint"]["defendants_count"]
    result = check(pack, unresolved)
    eq("F17 an unresolvable ref does not pass", result["verdict"], "review")

    # copies_submitted as a string must not silently compare as a number.
    typed = _compliant_filing()
    typed["complaint"]["copies_submitted"] = "3"
    result = check(pack, typed)
    eq("F18 a string copy count does not pass", result["verdict"], "review")
    ok("F19 and it is a type error", "TYPE_ERROR" in reasons(result), repr(reasons(result)))


# ---------------------------------------------------------------------------
# eu-label
# ---------------------------------------------------------------------------


def _compliant_label():
    return {
        "sku": "SKU-1",
        "fields": {
            "name": True,
            "ingredients_list": True,
            "quantity_of_ingredients": True,
            "net_quantity": True,
            "date_mark": True,
            "storage_conditions": True,
            "fbo_name_address": True,
            "country_of_origin": True,
            "instructions_for_use": True,
            "nutrition_declaration": True,
            # A non-alcoholic product: the strength declaration is not required, and
            # the field is recorded as absent rather than left out. Leaving it out
            # makes r6 report MISSING_FIELD, which is correct engine behaviour and
            # would mask every other assertion in this suite.
            "alcohol_strength": False,
        },
        "allergens_declared": ["milk", "nuts"],
        "allergens_emphasised": True,
        # Non-alcoholic, so r6 evaluates to "not applicable" rather than reporting
        # a missing field. The field is part of the pack's required set, so leaving
        # it out would add a MISSING_FIELD/review to every case in this suite and
        # mask what each case is actually testing.
        "alcohol_by_volume_pct": 0.0,
        "net_quantity": {"value": 500, "unit": "g"},
        "x_height_mm": 1.4,
        "package_area_cm2": 250,
        "vision": {"name": "A", "net_quantity": "A", "alcohol_strength": "A"},
    }


def test_eu_label():
    pack = load_pack("eu-label")

    good = check(pack, _compliant_label())
    eq("E1 a compliant label passes", good["verdict"], "pass")
    eq("E2 exit code 0", exit_code(good), 0)

    # r1 / r2: the x-height thresholds, and the 80 cm2 boundary between them.
    small = _compliant_label()
    small["x_height_mm"] = 1.0
    result = check(pack, small)
    eq("E3 x-height 1.0 on a large pack fails", result["verdict"], "fail")
    eq("E4 with XHEIGHT_BELOW_1_2MM", reasons(result), ["XHEIGHT_BELOW_1_2MM"])

    small_pack = _compliant_label()
    small_pack["package_area_cm2"] = 60
    small_pack["x_height_mm"] = 1.0
    eq("E5 the same x-height on a small pack passes",
       check(pack, small_pack)["verdict"], "pass")

    tiny = _compliant_label()
    tiny["package_area_cm2"] = 60
    tiny["x_height_mm"] = 0.8
    result = check(pack, tiny)
    eq("E6 x-height 0.8 on a small pack fails", result["verdict"], "fail")
    eq("E7 with the small-pack reason code", reasons(result),
       ["XHEIGHT_BELOW_0_9MM_SMALL_PACK"])

    boundary = _compliant_label()
    boundary["package_area_cm2"] = 80
    boundary["x_height_mm"] = 1.0
    result = check(pack, boundary)
    eq("E8 exactly 80 cm2 is a large pack (>= 80)", result["verdict"], "fail")

    # r3: a missing mandatory particular.
    missing = _compliant_label()
    missing["fields"]["nutrition_declaration"] = False
    result = check(pack, missing)
    eq("E9 a missing mandatory particular fails", result["verdict"], "fail")
    eq("E10 with MANDATORY_PARTICULAR_MISSING", reasons(result),
       ["MANDATORY_PARTICULAR_MISSING"])

    # r4: allergens not emphasised.
    plain = _compliant_label()
    plain["allergens_emphasised"] = False
    result = check(pack, plain)
    eq("E11 unemphasised allergens fail", result["verdict"], "fail")
    eq("E12 with ALLERGENS_NOT_EMPHASISED", reasons(result), ["ALLERGENS_NOT_EMPHASISED"])

    # r5: an allergen key outside the vocabulary escalates rather than fails.
    odd = _compliant_label()
    odd["allergens_declared"] = ["milk", "mystery_substance"]
    result = check(pack, odd)
    eq("E13 an unmappable allergen key is review", result["verdict"], "review")
    ok("E14 with ALLERGEN_KEY_NOT_MAPPABLE",
       "ALLERGEN_KEY_NOT_MAPPABLE" in reasons(result), repr(reasons(result)))

    # r6: alcohol above 1.2% needs the strength declared.
    booze = _compliant_label()
    booze["alcohol_by_volume_pct"] = 5.0
    booze["fields"]["alcohol_strength"] = False
    result = check(pack, booze)
    eq("E15 an alcoholic drink without a strength declaration fails",
       result["verdict"], "fail")
    booze_ok = _compliant_label()
    booze_ok["alcohol_by_volume_pct"] = 5.0
    booze_ok["fields"]["alcohol_strength"] = True
    eq("E16 and passes when declared", check(pack, booze_ok)["verdict"], "pass")
    low = _compliant_label()
    low["alcohol_by_volume_pct"] = 1.0
    low["fields"]["alcohol_strength"] = False
    eq("E17 at or below 1.2% the declaration is not required",
       check(pack, low)["verdict"], "pass")

    # r7: the field-of-vision grouping, which compares three fields to each other.
    split = _compliant_label()
    split["vision"]["net_quantity"] = "B"
    result = check(pack, split)
    eq("E18 a split field of vision fails", result["verdict"], "fail")
    eq("E19 with NOT_SAME_FIELD_OF_VISION", reasons(result),
       ["NOT_SAME_FIELD_OF_VISION"])

    # Nested-path typos must surface as review, never as a silent pass.
    typo = _compliant_label()
    typo["x_height"] = typo.pop("x_height_mm")
    result = check(pack, typo)
    eq("E20 a misnamed nested field is review, not pass", result["verdict"], "review")
    ok("E21 and it names MISSING_FIELD", "MISSING_FIELD" in reasons(result),
       repr(reasons(result)))


def main():
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    stream.write("phocinae-rulepack pack behaviour tests\n\n")
    for test in (test_filing_requirements, test_eu_label):
        before = len(FAILED)
        try:
            test()
        except Exception:  # noqa: BLE001
            import traceback
            FAILED.append(("%s raised" % test.__name__, traceback.format_exc()))
        stream.write("%-30s %s\n" % (test.__name__, "OK" if len(FAILED) == before else "FAIL"))
    stream.write("\n")
    for label, detail in FAILED:
        stream.write("  FAIL %s\n" % label)
        if detail:
            for line in str(detail).rstrip().splitlines():
                stream.write("       %s\n" % line)
    stream.write("-" * 60 + "\n")
    stream.write("PASS=%d FAIL=%d\n" % (PASSED, len(FAILED)))
    if PASSED == 0:
        stream.write("FAIL: nothing was verified\n")
        return 1
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
