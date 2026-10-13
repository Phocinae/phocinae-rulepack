"""Command-line interface.

    phocinae-rulepack validate <pack.yaml|pack-id|dir> [--json] [--strict]
    phocinae-rulepack check    <pack.yaml|pack-id> <input> [--json|--yaml]
    phocinae-rulepack list     <pack.yaml|pack-id|dir> [--json] [--rules]

Exit codes: 0 = all pass, 1 = a fail exists, 2 = a review exists (grey zone),
3 = usage/configuration error or empty scan. Priority is fixed: 3 > 1 > 2 > 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .engine import check, check_many, dump_canonical
from .errors import (
    PackError,
    EXIT_PASS,
    EXIT_USAGE,
    exit_code,
)
from .schema import load_pack, validate_pack


def _emit(text):
    """Write text as UTF-8 regardless of the console's default encoding."""
    stream = sys.stdout
    try:
        stream.reconfigure(encoding="utf-8", newline="\n")
    except (AttributeError, ValueError):  # pragma: no cover - very old/odd stdout
        pass
    stream.write(text)


def _load_input(path):
    if path == "-":
        raw = sys.stdin.read()
    else:
        if not os.path.isfile(path):
            raise PackError("E_INPUT_NOT_FOUND", "input file %r does not exist" % path)
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    if raw.strip() == "":
        raise PackError("E_EMPTY_SCAN", "input %r is empty" % path)
    stripped = raw.lstrip()
    if stripped[0] in "[{":
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise PackError("E_INPUT_RECORD", "input %r is not valid JSON: %s" % (path, exc))
    from . import yamlsubset

    document = yamlsubset.load(raw)
    if isinstance(document, list):
        return [entry for entry in document]
    if isinstance(document, dict) and "records" in document and len(document) == 1:
        return document["records"]
    return document


def _cmd_validate(args):
    report = validate_pack(args.pack, strict=args.strict, packs_dir=args.packs_dir)
    if args.json:
        _emit(
            json.dumps(
                {
                    "ok": True,
                    "pack": report.pack.id,
                    "version": report.pack.version,
                    "counts": report.counts,
                    "warnings": report.warnings,
                    "checks": report.checks,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
    else:
        for warning in report.warnings:
            _emit("WARN %s\n" % warning)
        _emit("%s\n" % report.summary_line())
        _emit("OK %s\n" % report.pack.title)
    return EXIT_PASS


def _cmd_list(args):
    target = args.pack
    candidates = []
    if os.path.isdir(target):
        for name in sorted(os.listdir(target)):
            child = os.path.join(target, name)
            if os.path.isdir(child) and (
                os.path.isfile(os.path.join(child, "rulepack.yaml"))
                or os.path.isfile(os.path.join(child, "rulepack.yaml.draft"))
            ):
                candidates.append(child)
    else:
        candidates.append(target)

    entries = []
    for candidate in candidates:
        try:
            pack = load_pack(candidate, packs_dir=args.packs_dir)
        except PackError as exc:
            entries.append({"pack": candidate, "ok": False, "error": str(exc)})
            continue
        entry = {
            "pack": pack.id,
            "title": pack.title,
            "version": pack.version,
            "scenario": pack.scenario,
            "rules": len(pack.rules),
            "citations": len(pack.citations),
            "ok": True,
        }
        if args.rules:
            entry["rule_ids"] = [rule.id for rule in pack.rules]
        entries.append(entry)

    if args.json:
        _emit(json.dumps(entries, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    else:
        for entry in entries:
            if not entry["ok"]:
                _emit("BROKEN %s: %s\n" % (entry["pack"], entry["error"]))
                continue
            _emit(
                "%-22s %-10s rules=%-3d citations=%-3d scenario=%s\n"
                % (
                    entry["pack"],
                    entry["version"],
                    entry["rules"],
                    entry["citations"],
                    entry.get("scenario") or "-",
                )
            )
    return EXIT_PASS


def _cmd_check(args):
    pack = load_pack(args.pack, packs_dir=args.packs_dir)
    document = _load_input(args.input)

    if isinstance(document, list):
        payload = check_many(pack, document)
    else:
        payload = check(pack, document)

    if args.out:
        with open(args.out, "wb") as handle:
            handle.write(dump_canonical(payload))
        return exit_code(payload)

    if args.format == "json":
        _emit(dump_canonical(payload).decode("utf-8"))
        return exit_code(payload)

    _render_text(payload)
    return exit_code(payload)


def _render_text(payload):
    results = payload.get("results")
    if results is None:
        _render_one(payload, "")
    else:
        for index, entry in enumerate(results):
            _render_one(entry, "record %d: " % index)
    codes = exit_code(payload)
    _emit(
        "\nVERDICT %s  (exit %d)  model_calls=%d\n"
        % (payload["verdict"], codes, payload["model_calls"])
    )


def _render_one(entry, prefix):
    _emit("%s%s  rulepack=%s\n" % (prefix, entry["verdict"].upper(), entry["rulepack"]))
    for reason in entry["reasons"]:
        cite = ",".join(reason["cite"]) or "-"
        _emit(
            "    [%s] %-34s rule=%-28s cite=%s\n"
            "        %s\n"
            % (
                reason["verdict"],
                reason["reason_code"],
                reason["rule"] or "-",
                cite,
                reason["evidence"],
            )
        )
    if entry.get("unmatched_paths"):
        _emit("    unmatched_paths: %s\n" % ", ".join(entry["unmatched_paths"]))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="phocinae-rulepack",
        description="Deterministic rule-pack engine: read a ledger, apply a versioned rule "
                    "pack, emit only the differences for human review. No model calls.",
    )
    parser.add_argument("--version", action="version", version="phocinae_rulepack %s" % __version__)
    parser.add_argument(
        "--packs-dir",
        default=os.environ.get("PHOCINAE_RULEPACK_PACKS"),
        help="directory of built-in packs (default: the packs shipped with the package)",
    )
    subparsers = parser.add_subparsers(dest="command")

    validate = subparsers.add_parser("validate", help="check a pack's schema, citations and corpus")
    validate.add_argument("pack")
    validate.add_argument("--json", action="store_true")
    validate.add_argument(
        "--strict",
        action="store_true",
        help="also fail on sample corpus and on citations whose instrument text was not obtained",
    )
    validate.set_defaults(handler=_cmd_validate)

    listing = subparsers.add_parser("list", help="list packs in a directory or one pack summary")
    listing.add_argument("pack")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--rules", action="store_true", help="also list rule ids")
    listing.set_defaults(handler=_cmd_list)

    check = subparsers.add_parser("check", help="run a document (or a ledger) through a pack")
    check.add_argument("pack")
    check.add_argument("input", help="JSON or YAML document; '-' reads stdin")
    check.add_argument("--format", choices=("json", "text"), default="text")
    check.add_argument("--out", help="write canonical JSON to this path instead of stdout")
    check.set_defaults(handler=_cmd_check)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return args.handler(args)
    except PackError as exc:
        sys.stderr.write("ERROR %s\n" % exc)
        return EXIT_USAGE
    except BrokenPipeError:  # pragma: no cover - piping into `head` and friends
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
