# -*- coding: utf-8 -*-
"""Test harness.

Two rules this project learned the hard way:

1. **Never use ``tempfile``.** On this machine the system TEMP directory's
   writability has been reported both ways, and ``tempfile.gettempdir()`` falls
   back to the *current working directory* when it is not writable -- which
   scatters scratch directories through the repository. Scratch goes to an
   explicit directory outside the tree.

2. **A suite that ran nothing is a failure, not a pass.** The runner exits
   non-zero when zero assertions ran.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import traceback

# ---------------------------------------------------------------------------
# Scratch directory: explicit, outside the repository.
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)


def scratch_root():
    override = os.environ.get("PHOCINAE_RULEPACK_TMP")
    if override:
        return override
    parent = os.path.dirname(_REPO)
    return os.path.join(parent, ".phocinae-rulepack-tmp")


def scratch_dir(name):
    path = os.path.join(scratch_root(), name)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Assertion collection
# ---------------------------------------------------------------------------


class Suite(object):
    def __init__(self, name):
        self.name = name
        self.passed = 0
        self.failed = []
        self.skipped = []

    # -- assertions --------------------------------------------------------
    def check(self, label, condition, detail=""):
        if condition:
            self.passed += 1
            return True
        self.failed.append((label, detail))
        return False

    def equal(self, label, actual, expected):
        return self.check(
            label, actual == expected, "expected %r, got %r" % (expected, actual)
        )

    def is_true(self, label, value, detail=""):
        return self.check(label, bool(value), detail or "value was %r" % (value,))

    def raises(self, label, reason_code, func, *fargs, **fkwargs):
        """Assert that ``func`` raises PackError with exactly ``reason_code``."""
        from phocinae_rulepack import PackError

        try:
            func(*fargs, **fkwargs)
        except PackError as exc:
            return self.equal(label + " [reason_code]", exc.reason_code, reason_code)
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected
            return self.check(
                label, False, "raised %s instead of PackError: %s" % (type(exc).__name__, exc)
            )
        return self.check(label, False, "did not raise; expected %s" % reason_code)

    def skip(self, label, reason):
        self.skipped.append((label, reason))

    # -- reporting ---------------------------------------------------------
    def report(self, stream):
        total = self.passed + len(self.failed)
        for label, detail in self.failed:
            stream.write("  FAIL %s\n" % label)
            if detail:
                stream.write("       %s\n" % detail)
        for label, reason in self.skipped:
            stream.write("  SKIP %s (%s)\n" % (label, reason))
        stream.write(
            "%-28s PASS=%d FAIL=%d SKIP=%d\n"
            % (self.name, self.passed, len(self.failed), len(self.skipped))
        )
        return len(self.failed) == 0 and total > 0


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def read_json(path):
    import json

    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def utf8_stream():
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    return stream
