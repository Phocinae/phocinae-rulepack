"""Pack loading, validation and the corpus/citation evidence model.

The evidence model is the point of this module. A citation may be:

``verbatim``     the quote appears character-for-character in the corpus.
``derived``      the wording comes from an authority's restatement, not the
                 instrument's own text. Allowed, but warned about.
``unavailable``  the instrument text could not be obtained. Any rule citing it
                 is **capped to ``review``** and can never produce ``fail``.

That cap is the difference between an honest tool and a fake gate: a rule whose
basis nobody has read must not be able to reject a customer's paperwork. The cap
is verified in both directions by the test suite (flip the citation to
``derived`` and the same input must move from ``review`` to ``fail``).
"""

from __future__ import annotations

import hashlib
import os
import re

from . import yamlsubset
from .errors import (
    PackError,
    E_CITATION_NOT_FOUND,
    E_CITATION_NO_SOURCE_TEXT,
    E_CORPUS_HASH_MISMATCH,
    E_CORPUS_MISSING,
    E_DERIVED_FIELDS,
    E_NO_CITATIONS,
    E_NO_RULES,
    E_RULE,
    E_RULE_ON_MISSING,
    E_SCHEMA,
)
from .expr import compile_condition, compile_derived, referenced_fields

SCHEMA_ID = "phocinae-rulepack/v1"

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
CITATION_ID_RE = re.compile(r"^c[0-9A-Za-z_-]+$")
RULE_ID_RE = re.compile(r"^r[0-9A-Za-z_-]+$")
REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")

EVIDENCE_LEVELS = ("verbatim", "derived", "unavailable")
CORPUS_ROLES = ("authority", "production", "sample")
MATCH_MODES = ("exact", "whitespace_folded")
VERDICTS = ("pass", "fail", "review")

#: corpus role values that make ``--strict`` fail (a shipped sample is not a basis).
STRICT_FORBIDDEN_ROLES = ("sample",)


class Citation(object):
    __slots__ = ("id", "source", "locator", "quote", "document", "evidence_level", "match", "line")

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))

    @property
    def capped(self):
        """True when this citation cannot support a ``fail`` verdict."""
        return self.evidence_level == "unavailable"


class CorpusFile(object):
    __slots__ = ("path", "sha256", "role", "title", "url", "retrieved", "origin", "origin_sha256", "text")

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))


class Rule(object):
    __slots__ = (
        "id",
        "condition",
        "verdict",
        "reason_code",
        "cite",
        "require_fields",
        "on_missing",
        "note",
        "line",
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))

    def fields(self):
        out = list(referenced_fields(self.condition))
        for path in self.require_fields or ():
            if path not in out:
                out.append(path)
        return out


class Pack(object):
    __slots__ = (
        "schema",
        "id",
        "title",
        "version",
        "description",
        "scenario",
        "citations",
        "corpus",
        "rules",
        "missing_field_policy",
        "input_schema",
        "enum_domains",
        "notes",
        "derived_fields",
        "path",
        "directory",
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))

    def citation(self, citation_id):
        for item in self.citations:
            if item.id == citation_id:
                return item
        return None

    def fields(self):
        out = []
        for rule in self.rules:
            for path in rule.fields():
                if path not in out:
                    out.append(path)
        return out


class ValidationReport(object):
    __slots__ = ("pack", "warnings", "counts", "checks")

    def __init__(self, pack, warnings, counts, checks):
        self.pack = pack
        self.warnings = warnings
        self.counts = counts
        self.checks = checks

    @property
    def ok(self):
        return True

    def summary_line(self):
        c = self.counts
        return (
            "pack=%(id)s rules=%(rules)d citations=%(citations)d "
            "(verbatim=%(verbatim)d derived=%(derived)d unavailable=%(unavailable)d) "
            "corpus=%(corpus)d (authority=%(authority)d production=%(production)d "
            "sample=%(sample)d) warnings=%(warnings)d"
            % {
                "id": self.pack.id,
                "rules": c["rules"],
                "citations": c["citations"],
                "verbatim": c["verbatim"],
                "derived": c["derived"],
                "unavailable": c["unavailable"],
                "corpus": c["corpus"],
                "authority": c["authority"],
                "production": c["production"],
                "sample": c["sample"],
                "warnings": len(self.warnings),
            }
        )


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _require_mapping(value, where):
    if not isinstance(value, dict):
        raise PackError(E_SCHEMA, "%s: expected a mapping, got %s" % (where, _type_name(value)))
    return value


def _require_str(value, where, pattern=None, allow_empty=False):
    if not isinstance(value, str):
        raise PackError(E_SCHEMA, "%s: expected a string, got %s" % (where, _type_name(value)))
    if not allow_empty and value == "":
        raise PackError(E_SCHEMA, "%s: must not be empty" % where)
    if pattern is not None and not pattern.match(value):
        raise PackError(E_SCHEMA, "%s: %r does not match %s" % (where, value, pattern.pattern))
    return value


def _type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "mapping"
    return type(value).__name__


def _normalise(text, mode):
    if mode == "whitespace_folded":
        return re.sub(r"\s+", " ", text).strip()
    return text


def _find_pack_file(target, packs_dir):
    """Return (path, is_draft) for a pack reference (path or built-in id)."""
    if os.path.isfile(target):
        return target, target.endswith(".draft")
    if os.path.isdir(target):
        for name in ("rulepack.yaml", "rulepack.yaml.draft"):
            candidate = os.path.join(target, name)
            if os.path.isfile(candidate):
                return candidate, name.endswith(".draft")
        raise PackError(E_SCHEMA, "%s: no rulepack.yaml in directory" % target)
    base = packs_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs")
    if os.path.isdir(base):
        pack_dir = os.path.join(base, target)
        if os.path.isdir(pack_dir):
            for name in ("rulepack.yaml", "rulepack.yaml.draft"):
                candidate = os.path.join(pack_dir, name)
                if os.path.isfile(candidate):
                    return candidate, name.endswith(".draft")
    raise PackError(E_SCHEMA, "cannot resolve pack %r (not a file, directory, or built-in id)" % target)


def load_pack(target, packs_dir=None):
    """Load and fully validate a pack. Raises :class:`PackError` on any problem."""
    path, _is_draft = _find_pack_file(target, packs_dir)
    document = yamlsubset.load_file(path)
    pack = _parse_pack(document, path)
    _validate_pack(pack, strict=False)
    return pack


def validate_pack(pack_or_target, strict=False, packs_dir=None):
    """Validate a pack (or a reference to one) and return a :class:`ValidationReport`."""
    if isinstance(pack_or_target, Pack):
        pack = pack_or_target
    else:
        path, _is_draft = _find_pack_file(pack_or_target, packs_dir)
        document = yamlsubset.load_file(path)
        pack = _parse_pack(document, path)
    return _validate_pack(pack, strict=strict)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_pack(document, path):
    document = _require_mapping(document, "pack")
    allowed = {
        "schema",
        "id",
        "title",
        "version",
        "description",
        "scenario",
        "citations",
        "corpus",
        "rules",
        "missing_field_policy",
        "input_schema",
        "enum_domains",
        "notes",
        "derived_fields",
    }
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise PackError(E_SCHEMA, "pack: unknown top-level keys %r" % (unknown,))

    schema = document.get("schema")
    if schema != SCHEMA_ID:
        raise PackError(
            E_SCHEMA,
            "pack: 'schema' must be %r, got %r (a different schema is not this tool's "
            "document)" % (SCHEMA_ID, schema),
        )

    # `derived_fields` is reserved for v2. Seeing it in v0.1.0 must be an error:
    # silently ignoring it would leave a pack author believing the arithmetic ran.
    if "derived_fields" in document and document["derived_fields"] is not None:
        raise PackError(
            E_DERIVED_FIELDS,
            "pack: 'derived_fields' is reserved for schema v2 and is NOT implemented in "
            "this version; remove it or compute the value in your input adapter "
            "(it is never ignored silently)",
        )

    missing_field_policy = document.get("missing_field_policy", "review")
    if missing_field_policy != "review":
        raise PackError(
            E_SCHEMA,
            "pack: 'missing_field_policy' may only be 'review' in v1 (got %r); a missing "
            "field must never be treated as compliance" % (missing_field_policy,),
        )

    pack_dir = os.path.dirname(os.path.abspath(path))
    corpus = _parse_corpus(document.get("corpus"), pack_dir)
    citations = _parse_citations(document.get("citations"), corpus)
    rules = _parse_rules(document.get("rules"))

    input_schema = document.get("input_schema")
    if input_schema is not None:
        input_schema = _require_mapping(input_schema, "pack.input_schema")
    enum_domains = document.get("enum_domains")
    if enum_domains is not None:
        enum_domains = _require_mapping(enum_domains, "pack.enum_domains")

    notes = document.get("notes")
    if notes is not None and not isinstance(notes, list):
        raise PackError(E_SCHEMA, "pack.notes: expected a list")

    return Pack(
        schema=schema,
        id=_require_str(document.get("id"), "pack.id", ID_RE),
        title=_require_str(document.get("title"), "pack.title"),
        version=_require_str(document.get("version"), "pack.version"),
        description=document.get("description"),
        scenario=document.get("scenario"),
        citations=citations,
        corpus=corpus,
        rules=rules,
        missing_field_policy=missing_field_policy,
        input_schema=input_schema,
        enum_domains=enum_domains,
        notes=notes,
        derived_fields=None,
        path=path,
        directory=pack_dir,
    )


def _normalise_sha256(raw, where):
    """Accept a sha256 written as a string, or as an all-digit integer.

    YAML turns an unquoted run of digits into a number, so a hash that happens
    to be all digits would otherwise be rejected by a *type* error -- a
    legitimate pack failing for a reason that has nothing to do with its
    content. Left-padding to 64 digits restores it exactly.
    """
    if isinstance(raw, bool):
        raise PackError(E_SCHEMA, "%s: must be 64 hex characters" % where)
    if isinstance(raw, int):
        raw = str(raw).rjust(64, "0")
    if not isinstance(raw, str) or not SHA256_RE.match(raw):
        raise PackError(E_SCHEMA, "%s: must be 64 hex characters" % where)
    return raw.upper()


def _parse_corpus(raw, pack_dir):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PackError(E_SCHEMA, "pack.corpus: expected a list")
    out = []
    seen = set()
    for index, entry in enumerate(raw):
        where = "pack.corpus[%d]" % index
        entry = _require_mapping(entry, where)
        unknown = sorted(set(entry) - {"path", "sha256", "role", "title", "url", "retrieved", "origin", "origin_sha256"})
        if unknown:
            raise PackError(E_SCHEMA, "%s: unknown keys %r" % (where, unknown))
        rel = _require_str(entry.get("path"), where + ".path")
        if os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
            raise PackError(E_SCHEMA, "%s.path: must be a relative path without '..'" % where)
        if rel in seen:
            raise PackError(E_SCHEMA, "%s.path: duplicate corpus path %r" % (where, rel))
        seen.add(rel)
        role = entry.get("role")
        if role not in CORPUS_ROLES:
            raise PackError(
                E_SCHEMA, "%s.role: must be one of %s" % (where, ", ".join(CORPUS_ROLES))
            )
        digest = _normalise_sha256(entry.get("sha256"), where + ".sha256")
        absolute = os.path.join(pack_dir, rel)
        text = None
        if os.path.isfile(absolute):
            with open(absolute, "rb") as handle:
                payload = handle.read()
            text = payload.decode("utf-8")
        out.append(
            CorpusFile(
                path=rel,
                sha256=digest.upper(),
                role=role,
                title=entry.get("title"),
                url=entry.get("url"),
                retrieved=entry.get("retrieved"),
                origin=entry.get("origin"),
                origin_sha256=entry.get("origin_sha256"),
                text=text,
            )
        )
    return out


def _parse_citations(raw, corpus):
    if raw is None:
        raise PackError(E_NO_CITATIONS, "pack.citations is missing")
    if not isinstance(raw, list):
        raise PackError(E_SCHEMA, "pack.citations: expected a list")
    by_path = {item.path: item for item in corpus}
    out = []
    seen = set()
    for index, entry in enumerate(raw):
        where = "pack.citations[%d]" % index
        entry = _require_mapping(entry, where)
        unknown = sorted(
            set(entry) - {"id", "source", "locator", "quote", "document", "evidence_level", "match"}
        )
        if unknown:
            raise PackError(E_SCHEMA, "%s: unknown keys %r" % (where, unknown))
        citation_id = _require_str(entry.get("id"), where + ".id", CITATION_ID_RE)
        if citation_id in seen:
            raise PackError(E_SCHEMA, "%s.id: duplicate citation id %r" % (where, citation_id))
        seen.add(citation_id)
        document = entry.get("document")
        if document is not None:
            document = _require_str(document, where + ".document")
            if document not in by_path:
                raise PackError(
                    E_SCHEMA,
                    "%s.document: %r is not declared in pack.corpus" % (where, document),
                )
        level = entry.get("evidence_level", "derived")
        if level not in EVIDENCE_LEVELS:
            raise PackError(
                E_SCHEMA, "%s.evidence_level: must be one of %s" % (where, ", ".join(EVIDENCE_LEVELS))
            )
        mode = entry.get("match", "exact")
        if mode not in MATCH_MODES:
            raise PackError(E_SCHEMA, "%s.match: must be one of %s" % (where, ", ".join(MATCH_MODES)))
        out.append(
            Citation(
                id=citation_id,
                source=_require_str(entry.get("source"), where + ".source"),
                locator=_require_str(entry.get("locator"), where + ".locator"),
                quote=_require_str(entry.get("quote"), where + ".quote"),
                document=document,
                evidence_level=level,
                match=mode,
                line=None,
            )
        )
    return out


def _parse_rules(raw):
    if raw is None:
        raise PackError(E_NO_RULES, "pack.rules is missing")
    if not isinstance(raw, list):
        raise PackError(E_SCHEMA, "pack.rules: expected a list")
    out = []
    seen = set()
    for index, entry in enumerate(raw):
        where = "pack.rules[%d]" % index
        entry = _require_mapping(entry, where)
        unknown = sorted(set(entry) - {"id", "when", "then", "require_fields", "on_missing", "note"})
        if unknown:
            raise PackError(E_SCHEMA, "%s: unknown keys %r" % (where, unknown))
        rule_id = _require_str(entry.get("id"), where + ".id", RULE_ID_RE)
        if rule_id in seen:
            raise PackError(E_SCHEMA, "%s.id: duplicate rule id %r" % (where, rule_id))
        seen.add(rule_id)

        then = _require_mapping(entry.get("then"), where + ".then")
        unknown_then = sorted(set(then) - {"verdict", "reason_code", "cite"})
        if unknown_then:
            raise PackError(E_SCHEMA, "%s.then: unknown keys %r" % (where, unknown_then))
        verdict = then.get("verdict")
        if verdict not in VERDICTS:
            raise PackError(E_SCHEMA, "%s.then.verdict: must be one of %s" % (where, ", ".join(VERDICTS)))
        reason_code = _require_str(then.get("reason_code"), where + ".then.reason_code", REASON_CODE_RE)
        cite = then.get("cite")
        if not isinstance(cite, list) or not cite:
            raise PackError(E_RULE, "%s.then.cite: must be a non-empty list" % where)
        for item in cite:
            if not isinstance(item, str) or not CITATION_ID_RE.match(item):
                raise PackError(E_RULE, "%s.then.cite: %r is not a citation id" % (where, item))

        require_fields = entry.get("require_fields")
        if require_fields is not None:
            if not isinstance(require_fields, list) or not require_fields:
                raise PackError(E_RULE, "%s.require_fields: must be a non-empty list" % where)
            for item in require_fields:
                if not isinstance(item, str) or not item or "." in item and item.split(".")[-1] == "":
                    raise PackError(E_RULE, "%s.require_fields: %r is not a field path" % (where, item))
        on_missing = entry.get("on_missing", "review")
        if on_missing not in ("review", "fail"):
            raise PackError(E_RULE, "%s.on_missing: must be 'review' or 'fail'" % where)
        if on_missing == "fail" and verdict != "fail":
            raise PackError(
                E_RULE_ON_MISSING,
                "%s: on_missing: fail is only allowed when then.verdict is 'fail' "
                "(a missing field must not be turned into a pass, and turning it into a "
                "different verdict is ambiguous)" % where,
            )

        condition = compile_condition(entry.get("when"), where + ".when")
        out.append(
            Rule(
                id=rule_id,
                condition=condition,
                verdict=verdict,
                reason_code=reason_code,
                cite=list(cite),
                require_fields=list(require_fields) if require_fields else [],
                on_missing=on_missing,
                note=entry.get("note"),
                line=None,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_pack(pack, strict=False):
    warnings = []
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return ok

    # -- empty scans -------------------------------------------------------
    if not pack.rules:
        raise PackError(E_NO_RULES, "pack %r has no rules: a check with nothing to check "
                                    "must not report success" % pack.id)
    if not pack.citations:
        raise PackError(E_NO_CITATIONS, "pack %r has no citations: every rule must be "
                                        "traceable to a source" % pack.id)
    check("rules present", True, "%d rules" % len(pack.rules))
    check("citations present", True, "%d citations" % len(pack.citations))

    # -- citation ids referenced by rules ---------------------------------
    known = {item.id for item in pack.citations}
    for rule in pack.rules:
        unknown = [c for c in rule.cite if c not in known]
        if unknown:
            raise PackError(
                E_RULE,
                "rule %r cites %r which is not declared in citations" % (rule.id, unknown),
            )
    check("every cited id is declared", True)

    # -- corpus integrity --------------------------------------------------
    for item in pack.corpus:
        if item.text is None:
            raise PackError(
                E_CORPUS_MISSING,
                "corpus file %r is declared but not present next to the pack" % item.path,
            )
        actual = hashlib.sha256(item.text.encode("utf-8")).hexdigest().upper()
        if actual != item.sha256:
            raise PackError(
                E_CORPUS_HASH_MISMATCH,
                "corpus file %r: sha256 is %s but the pack declares %s"
                % (item.path, actual, item.sha256),
            )
    check("corpus hashes match", True, "%d files" % len(pack.corpus))

    # -- verbatim citation resolution --------------------------------------
    # A citation with no corpus at all cannot be checked character-for-character,
    # which would make the whole guarantee a non-empty-string test -- a fake gate.
    for citation in pack.citations:
        candidates = (
            [c for c in pack.corpus if c.path == citation.document]
            if citation.document
            else pack.corpus
        )
        if not candidates:
            raise PackError(
                E_CITATION_NO_SOURCE_TEXT,
                "citation %r has no corpus text to verify against (declare pack.corpus[] "
                "and citation.document so the quote can be checked character-for-character)"
                % citation.id,
            )
        if citation.evidence_level == "unavailable":
            warnings.append(
                "LINT_UNAVAILABLE_CITATION %s (%s): instrument text not obtained; any rule "
                "citing it is capped to 'review' and can never fail"
                % (citation.id, citation.locator)
            )
            continue
        needle = _normalise(citation.quote, citation.match)
        found = False
        for item in candidates:
            haystack = _normalise(item.text, citation.match)
            if needle in haystack:
                found = True
                break
        if not found:
            raise PackError(
                E_CITATION_NOT_FOUND,
                "citation %r: quote not found character-for-character in %s\n  quote: %r\n"
                "  locator: %s"
                % (
                    citation.id,
                    citation.document or "any corpus file",
                    citation.quote[:120],
                    citation.locator,
                ),
            )
        if citation.evidence_level == "derived":
            warnings.append(
                "LINT_DERIVED_CITATION %s (%s): wording is an authority's restatement, not "
                "the instrument's own text" % (citation.id, citation.locator)
            )
    check("citations resolve verbatim", True)

    # -- verdict-reachability: a pack that can never pass is a trap --------
    has_pass = any(rule.verdict == "pass" for rule in pack.rules)
    if not has_pass:
        warnings.append(
            "LINT_NO_PASS_RULE: no rule has then.verdict 'pass', so a fully compliant input "
            "can only ever come back as 'review' (nothing matched)"
        )
    check("at least one pass rule exists", has_pass)

    # -- strict-only rejections -------------------------------------------
    if strict:
        for item in pack.corpus:
            if item.role in STRICT_FORBIDDEN_ROLES:
                raise PackError(
                    E_SCHEMA,
                    "--strict: corpus file %r has role 'sample'; a shipped sample is not a "
                    "basis for a verdict" % item.path,
                )
        for citation in pack.citations:
            if citation.evidence_level == "unavailable":
                raise PackError(
                    E_SCHEMA,
                    "--strict: citation %r is 'unavailable' (instrument text not obtained)"
                    % citation.id,
                )
        check("strict: no sample corpus and no unavailable citations", True)

    counts = {
        "rules": len(pack.rules),
        "citations": len(pack.citations),
        "verbatim": sum(1 for c in pack.citations if c.evidence_level == "verbatim"),
        "derived": sum(1 for c in pack.citations if c.evidence_level == "derived"),
        "unavailable": sum(1 for c in pack.citations if c.evidence_level == "unavailable"),
        "corpus": len(pack.corpus),
        "authority": sum(1 for c in pack.corpus if c.role == "authority"),
        "production": sum(1 for c in pack.corpus if c.role == "production"),
        "sample": sum(1 for c in pack.corpus if c.role == "sample"),
    }
    return ValidationReport(pack=pack, warnings=warnings, counts=counts, checks=checks)
