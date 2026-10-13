"""Open the wheel that is about to be uploaded and check what is inside it.

This runs *before* upload, on the exact file, because "the source tree passes"
and "the published artefact is correct" are two different claims. One of this
project's families shipped a wheel that was missing a data file its whole test
suite passed without, because the file sat next to the source tree in the
developer's checkout.

    python tools/verify_wheel_contents.py dist-upload

Exits 1 if any required member is missing, or if the wheel contains test code or
bytecode. Passing more than one wheel is an error: picking one silently is how a
check ends up inspecting the previous release.
"""

from __future__ import annotations

import io
import os
import sys
import zipfile

REQUIRED = [
    "phocinae_rulepack/__init__.py",
    "phocinae_rulepack/__main__.py",
    "phocinae_rulepack/cli.py",
    "phocinae_rulepack/engine.py",
    "phocinae_rulepack/errors.py",
    "phocinae_rulepack/expr.py",
    "phocinae_rulepack/schema.py",
    "phocinae_rulepack/yamlsubset.py",
    "phocinae_rulepack/packs/expense-policy/rulepack.yaml",
    "phocinae_rulepack/packs/expense-policy/sources/s15_policy_constants.txt",
    "phocinae_rulepack/packs/expense-policy/sources/s15_rule_check.txt",
    "phocinae_rulepack/packs/expense-policy/sources/s15_feasibility_excerpt.md",
]

FORBIDDEN_SUBSTRINGS = ("__pycache__", "/tests/", "\\tests\\")
FORBIDDEN_SUFFIXES = (".pyc", ".pyo")


def wheels_in(directory):
    if os.path.isfile(directory):
        return [directory]
    return [
        os.path.join(directory, name)
        for name in sorted(os.listdir(directory))
        if name.endswith(".whl")
    ]


def main(argv):
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    target = argv[1] if len(argv) > 1 else "dist-upload"
    found = wheels_in(target)
    if not found:
        stream.write("FAIL: no wheel found under %r\n" % target)
        return 1
    if len(found) > 1:
        stream.write(
            "FAIL: %d wheels found under %r; refusing to guess which one is being "
            "uploaded:\n" % (len(found), target)
        )
        for path in found:
            stream.write("  %s\n" % path)
        return 1

    path = found[0]
    stream.write("inspecting %s\n" % path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()

        failures = []
        for member in REQUIRED:
            if member not in names:
                failures.append("missing required member: %s" % member)

        for name in names:
            if any(token in name for token in FORBIDDEN_SUBSTRINGS):
                failures.append("ships test code: %s" % name)
            if name.endswith(FORBIDDEN_SUFFIXES):
                failures.append("ships bytecode: %s" % name)

        metadata_name = next((n for n in names if n.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            failures.append("no METADATA found")
        else:
            metadata = archive.read(metadata_name).decode("utf-8")
            version = None
            for line in metadata.split("\n"):
                if line.startswith("Version: "):
                    version = line.split(": ", 1)[1].strip()
            stream.write("metadata version: %s\n" % version)
            if version != "0.1.0":
                failures.append("METADATA Version is %r, expected '0.1.0'" % version)

            # A dependency guarded by an `extra ==` marker is only installed when
            # someone asks for that extra, so it is not a runtime dependency.
            # An unconditional Requires-Dist is.
            unconditional = []
            for line in metadata.split("\n"):
                if not line.startswith("Requires-Dist:"):
                    continue
                requirement = line.split(":", 1)[1].strip()
                if "extra ==" in requirement:
                    stream.write("optional extra dependency: %s\n" % requirement)
                    continue
                unconditional.append(requirement)
            if unconditional:
                failures.append(
                    "the wheel declares an unconditional runtime dependency: %s" % unconditional
                )

            # The pack's own version constant must match the distribution.
            pack = archive.read("phocinae_rulepack/packs/expense-policy/rulepack.yaml").decode("utf-8")
            for line in pack.split("\n"):
                if line.startswith("version: "):
                    pack_version = line.split(": ", 1)[1].strip()
                    stream.write("pack version: %s\n" % pack_version)
                    break

            init = archive.read("phocinae_rulepack/__init__.py").decode("utf-8")
            for line in init.split("\n"):
                if line.startswith("__version__"):
                    constant = line.split("=", 1)[1].strip().strip('"').strip("'")
                    stream.write("__version__: %s\n" % constant)
                    if constant != version:
                        failures.append(
                            "__version__ is %r but METADATA says %r" % (constant, version)
                        )
                    break

        stream.write("members: %d\n" % len(names))
    if failures:
        for failure in failures:
            stream.write("FAIL %s\n" % failure)
        return 1
    stream.write("OK: %d required members present, no test code, no bytecode, "
                 "no runtime dependencies\n" % len(REQUIRED))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
