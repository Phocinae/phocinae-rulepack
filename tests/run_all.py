# -*- coding: utf-8 -*-
"""Zero-dependency test runner.

    python tests/run_all.py

Exits 0 only when every assertion passed **and** at least one assertion ran.
Zero assertions is a failure, not a pass -- the same rule the engine applies to
an empty scan.
"""

from __future__ import annotations

import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from _harness import Suite  # noqa: E402


def discover():
    """Every ``test_*`` callable defined in test_rulepack."""
    import test_rulepack

    found = []
    for name in sorted(dir(test_rulepack)):
        if not name.startswith("test_"):
            continue
        func = getattr(test_rulepack, name)
        if callable(func):
            found.append((name, func))
    return found


def main():
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    tests = discover()
    if not tests:
        stream.write("no tests discovered -- refusing to report success\n")
        return 1

    total_passed = 0
    total_failed = 0
    total_skipped = 0
    failures = 0

    stream.write("phocinae-rulepack test suite (%d groups)\n\n" % len(tests))
    for name, func in tests:
        suite = Suite(name)
        try:
            func(suite)
        except Exception:  # noqa: BLE001 - a crashing test is a failing test
            suite.check("%s did not raise" % name, False, traceback.format_exc())
        ok = suite.report(stream)
        total_passed += suite.passed
        total_failed += len(suite.failed)
        total_skipped += len(suite.skipped)
        if not ok:
            failures += 1
        stream.write("\n")

    stream.write("-" * 64 + "\n")
    stream.write(
        "TOTAL PASS=%d FAIL=%d SKIP=%d  groups=%d/%d ok\n"
        % (total_passed, total_failed, total_skipped, len(tests) - failures, len(tests))
    )
    stream.write("SKIP is not PASS: a skipped check verified nothing.\n")

    if total_passed == 0:
        stream.write("FAIL: nothing was verified\n")
        return 1
    if total_failed:
        stream.write("FAIL: %d assertion(s) failed\n" % total_failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
