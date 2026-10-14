"""The restricted expression language.

There is no ``eval``, no ``exec``, no attribute access and no callable values.
A condition is either a *leaf* (``field OP value``) or a boolean combination of
conditions.

Three-valued logic (Kleene). A leaf evaluates to ``True``, ``False`` or
``None`` (unknown). Unknown is produced by:

  * ``exists`` / ``missing`` on an absent field   -> NOT unknown (they answer it)
  * any other operator on an absent field         -> unknown (``MISSING_FIELD``)
  * an operator applied to a value of the wrong type -> unknown (``TYPE_ERROR``)
  * ``{"ref": "..."}`` pointing at an absent field   -> unknown (``REF_UNRESOLVED``)

A rule fires only when its condition is definitely ``True``. Unknown never
fires a rule, and — because the engine turns "no rule fired" into ``review`` —
unknown can never become a silent allow.

Operators
    ==  !=  <  <=  >  >=      comparison (numbers, strings, booleans, null)
    in  not_in                value membership in a list
    matches                   re.search of a pattern against a string
    exists  missing           key presence (always definite)
"""

from __future__ import annotations

import re

from .errors import PackError, E_EXPR

LEAF_OPS = ("==", "!=", "<", "<=", ">", ">=", "in", "not_in", "matches", "exists",
            "missing", "subset_of")
COMBINATORS = ("all_of", "any_of", "not")

#: Numeric-vs-numeric comparison is fine; bool is an int subclass in Python, so
#: it is excluded explicitly to stop `receipt_attached: 1` from satisfying a
#: boolean comparison (design section 4.5 / test C10).
_NUMERIC = (int, float)


class Leaf(object):
    __slots__ = ("field", "op", "value", "path")

    def __init__(self, field, op, value, path):
        self.field = field
        self.op = op
        self.value = value
        self.path = path

    def fields(self):
        return (self.field,)


class AllOf(object):
    __slots__ = ("items",)

    def __init__(self, items):
        self.items = items

    def fields(self):
        out = []
        for item in self.items:
            out.extend(item.fields())
        return tuple(out)


class AnyOf(AllOf):
    """Disjunction.

    NOTE: this subclasses AllOf, so any ``isinstance`` test must check AnyOf
    *first*. Getting that order wrong silently evaluates every ``any_of`` as a
    conjunction, which turns "within any category cap" into "within every
    category cap" and is invisible until a rule fails to fire.
    """

    pass


class Not(object):
    __slots__ = ("item",)

    def __init__(self, item):
        self.item = item

    def fields(self):
        return self.item.fields()


def _is_number(value):
    return isinstance(value, _NUMERIC) and not isinstance(value, bool)


def _same_kind(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool)
    if _is_number(left) and _is_number(right):
        return True
    if isinstance(left, str) and isinstance(right, str):
        return True
    if left is None or right is None:
        return left is None and right is None
    return False


def compile_condition(node, where):
    """Compile a condition tree, validating it against the subset."""
    if not isinstance(node, dict):
        raise PackError(E_EXPR, "%s: condition must be a mapping, got %r" % (where, node))
    keys = list(node.keys())

    for combinator in COMBINATORS:
        if combinator in node:
            if len(keys) != 1:
                raise PackError(
                    E_EXPR,
                    "%s: %r cannot be combined with sibling keys %r"
                    % (where, combinator, [k for k in keys if k != combinator]),
                )
            body = node[combinator]
            if combinator == "not":
                return Not(compile_condition(body, where + ".not"))
            if not isinstance(body, list) or not body:
                raise PackError(E_EXPR, "%s: %r must be a non-empty list" % (where, combinator))
            items = [
                compile_condition(item, "%s.%s[%d]" % (where, combinator, index))
                for index, item in enumerate(body)
            ]
            return AllOf(items) if combinator == "all_of" else AnyOf(items)

    if "field" not in node:
        raise PackError(
            E_EXPR,
            "%s: condition needs 'field' plus 'op', or one of %s"
            % (where, "/".join(COMBINATORS)),
        )
    unknown = [k for k in keys if k not in ("field", "op", "value")]
    if unknown:
        raise PackError(E_EXPR, "%s: unknown keys %r" % (where, unknown))
    field = node["field"]
    if not isinstance(field, str) or not field:
        raise PackError(E_EXPR, "%s: 'field' must be a non-empty string" % where)
    op = node.get("op")
    if op not in LEAF_OPS:
        raise PackError(
            E_EXPR, "%s: 'op' must be one of %s, got %r" % (where, ", ".join(LEAF_OPS), op)
        )
    if op in ("exists", "missing"):
        if "value" in node:
            raise PackError(E_EXPR, "%s: %r takes no 'value'" % (where, op))
        return Leaf(field, op, None, where)
    if "value" not in node:
        raise PackError(E_EXPR, "%s: %r needs a 'value'" % (where, op))
    value = node["value"]
    if isinstance(value, dict):
        if list(value.keys()) != ["ref"]:
            raise PackError(
                E_EXPR, "%s: a mapping value must be exactly {\"ref\": \"<path>\"}" % where
            )
        ref = value["ref"]
        if not isinstance(ref, str) or not ref:
            raise PackError(E_EXPR, "%s: 'ref' must be a non-empty string" % where)
    elif op in ("in", "not_in", "subset_of"):
        if not isinstance(value, list):
            raise PackError(E_EXPR, "%s: %r needs a list value" % (where, op))
    elif isinstance(value, (list, tuple)):
        raise PackError(E_EXPR, "%s: unexpected list value for %r" % (where, op))
    if op == "matches" and not isinstance(value, str) and not isinstance(value, dict):
        raise PackError(E_EXPR, "%s: 'matches' needs a string pattern or {\"ref\": ...}" % where)
    return Leaf(field, op, value, where)


def referenced_fields(condition):
    """Every field path mentioned anywhere in the tree, in document order."""
    return list(condition.fields())


def resolve(document, path):
    """Resolve a dotted path. Returns ``(found, value)``."""
    current = document
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
            continue
        if isinstance(current, list):
            if not part.isdigit():
                return False, None
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
            continue
        return False, None
    return True, current


class Evaluation(object):
    """Result of evaluating one condition against one document."""

    __slots__ = ("value", "reason_code", "detail")

    def __init__(self, value, reason_code=None, detail=None):
        self.value = value
        self.reason_code = reason_code
        self.detail = detail

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Evaluation(%r, %r)" % (self.value, self.reason_code)


_TRUE = Evaluation(True)
_FALSE = Evaluation(False)


def _unknown(code, detail):
    return Evaluation(None, code, detail)


def _compare(op, left, right):
    """Apply a comparison that is known to be same-kind. Returns bool."""
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "matches":
        try:
            return re.search(right, left) is not None
        except re.error:
            return False
    # Ordering comparisons are only defined for numbers and strings.
    return {
        "<": lambda: left < right,
        "<=": lambda: left <= right,
        ">": lambda: left > right,
        ">=": lambda: left >= right,
    }[op]()


def evaluate(condition, document):
    """Evaluate a compiled condition. Returns :class:`Evaluation`."""
    if isinstance(condition, (AllOf, AnyOf)):
        # AnyOf first: it is a subclass of AllOf.
        conjuction = not isinstance(condition, AnyOf)
        saw_unknown = None
        for item in condition.items:
            result = evaluate(item, document)
            if conjuction:
                if result.value is False:
                    return _FALSE
                if result.value is None and saw_unknown is None:
                    saw_unknown = result
            else:
                if result.value is True:
                    return _TRUE
                if result.value is None and saw_unknown is None:
                    saw_unknown = result
        if saw_unknown is not None:
            return saw_unknown
        return _TRUE if conjuction else _FALSE

    if isinstance(condition, Not):
        result = evaluate(condition.item, document)
        if result.value is None:
            return result
        return _FALSE if result.value else _TRUE

    # Leaf
    found, actual = resolve(document, condition.field)
    if condition.op == "exists":
        return _TRUE if found else _FALSE
    if condition.op == "missing":
        return _FALSE if found else _TRUE
    if not found:
        return _unknown(
            "MISSING_FIELD", "field %r is not present in the document" % condition.field
        )

    expected = condition.value
    if isinstance(expected, dict):
        ref_found, ref_value = resolve(document, expected["ref"])
        if not ref_found:
            return _unknown(
                "REF_UNRESOLVED",
                "%s: referenced field %r is not present" % (condition.path, expected["ref"]),
            )
        expected = ref_value

    if condition.op == "subset_of":
        # Every element of the field's array must appear in the given list.
        # `in` / `not_in` take a scalar on the left, so they cannot express this:
        # passing the array itself is a TYPE_ERROR, which is exactly how a rule
        # ends up never firing while looking cautious.
        if not isinstance(expected, list):
            return _unknown(
                "TYPE_ERROR",
                "%s: 'subset_of' needs a list to compare against" % condition.path,
            )
        if not isinstance(actual, list):
            return _unknown(
                "TYPE_ERROR",
                "%s: field %r is %s, not a list, so it cannot be a subset"
                % (condition.path, condition.field, _kind_name(actual)),
            )
        for element in actual:
            if isinstance(element, (list, dict)):
                return _unknown(
                    "TYPE_ERROR",
                    "%s: field %r contains a %s, which cannot be compared"
                    % (condition.path, condition.field, _kind_name(element)),
                )
            if not any(_same_kind(element, candidate) and element == candidate
                       for candidate in expected):
                return _FALSE
        # An empty array is a subset of everything. That is the mathematically
        # correct reading, and it is also the safe one here: "no allergens
        # declared" should not be reported as "an allergen outside the list".
        return _TRUE

    if condition.op in ("in", "not_in"):
        if not isinstance(expected, list):
            return _unknown(
                "TYPE_ERROR",
                "%s: %r needs a list to test membership against" % (condition.path, condition.op),
            )
        if isinstance(actual, (list, dict)):
            return _unknown(
                "TYPE_ERROR",
                "%s: field %r is a %s; use 'subset_of' to test an array against a list"
                % (condition.path, condition.field, _kind_name(actual)),
            )
        hit = any(_same_kind(actual, candidate) and actual == candidate for candidate in expected)
        return _TRUE if (hit if condition.op == "in" else not hit) else _FALSE

    if condition.op == "matches":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return _unknown(
                "TYPE_ERROR",
                "%s: 'matches' needs strings, got %s and %s"
                % (condition.path, type(actual).__name__, type(expected).__name__),
            )
        return _TRUE if _compare("matches", actual, expected) else _FALSE

    if not _same_kind(actual, expected):
        return _unknown(
            "TYPE_ERROR",
            "%s: field %r is %s but the rule expects %s"
            % (
                condition.path,
                condition.field,
                _kind_name(actual),
                _kind_name(expected),
            ),
        )
    if condition.op in ("<", "<=", ">", ">=") and not (
        _is_number(actual) or isinstance(actual, str)
    ):
        return _unknown(
            "TYPE_ERROR",
            "%s: %r is not defined for %s" % (condition.path, condition.op, _kind_name(actual)),
        )
    return _TRUE if _compare(condition.op, actual, expected) else _FALSE


def _kind_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if _is_number(value):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "mapping"
    return type(value).__name__


# ---------------------------------------------------------------------------
# Derived fields: the only arithmetic in the language (adjudication OQ-2).
# ---------------------------------------------------------------------------

DERIVED_OPS = ("add", "sub", "mul", "div", "min", "max", "round")
MAX_DERIVED_DEPTH = 3


def compile_derived(name, spec, where, depth=0):
    """Compile one ``derived_fields`` entry into a callable.

    Returns a function ``(document) -> (ok, value, reason_code, detail)``.
    """
    if depth >= MAX_DERIVED_DEPTH:
        raise PackError(
            E_EXPR,
            "%s: derived field %r nests deeper than %d levels" % (where, name, MAX_DERIVED_DEPTH),
        )
    if not isinstance(spec, dict):
        raise PackError(E_EXPR, "%s: derived field %r must be a mapping" % (where, name))
    unknown = [k for k in spec if k not in ("op", "args")]
    if unknown:
        raise PackError(E_EXPR, "%s: derived field %r has unknown keys %r" % (where, name, unknown))
    op = spec.get("op")
    if op not in DERIVED_OPS:
        raise PackError(
            E_EXPR,
            "%s: derived field %r: 'op' must be one of %s" % (where, name, ", ".join(DERIVED_OPS)),
        )
    args = spec.get("args")
    if not isinstance(args, list) or not args:
        raise PackError(E_EXPR, "%s: derived field %r needs a non-empty 'args' list" % (where, name))
    if op == "round" and len(args) != 2:
        raise PackError(E_EXPR, "%s: derived field %r: 'round' takes (value, digits)" % (where, name))
    if op in ("add", "sub", "div") and len(args) != 2:
        raise PackError(E_EXPR, "%s: derived field %r: %r takes exactly 2 args" % (where, name, op))
    if op in ("min", "max") and len(args) < 2:
        raise PackError(E_EXPR, "%s: derived field %r: %r needs at least 2 args" % (where, name, op))

    compiled = []
    for index, arg in enumerate(args):
        where_arg = "%s.args[%d]" % (where, index)
        if isinstance(arg, dict):
            if list(arg.keys()) != ["field"]:
                raise PackError(
                    E_EXPR, "%s: a mapping arg must be exactly {\"field\": \"<path>\"}" % where_arg
                )
            compiled.append(("field", arg["field"]))
        elif isinstance(arg, bool) or not _is_number(arg):
            raise PackError(
                E_EXPR, "%s: arg must be a number or {\"field\": ...}, got %r" % (where_arg, arg)
            )
        else:
            compiled.append(("literal", arg))

    def resolve_arg(kind, payload, document):
        if kind == "literal":
            return True, payload, None, None
        found, value = resolve(document, payload)
        if not found:
            return False, None, "MISSING_FIELD", "derived %r: field %r is absent" % (name, payload)
        if not _is_number(value):
            return (
                False,
                None,
                "TYPE_ERROR",
                "derived %r: field %r is %s, not a number"
                % (name, payload, _kind_name(value)),
            )
        return True, float(value), None, None

    if op == "round":
        digits_arg = compiled[1]
        if digits_arg[0] != "literal" or int(digits_arg[1]) != digits_arg[1]:
            raise PackError(E_EXPR, "%s: 'round' second arg must be an integer literal" % where)
        digits = int(digits_arg[1])

        def compute(document):
            ok, value, code, detail = resolve_arg(*compiled[0], document=document)
            if not ok:
                return False, None, code, detail
            return True, round(value, digits), None, None

        return compute

    def compute(document):
        values = []
        for kind, payload in compiled:
            ok, value, code, detail = resolve_arg(kind, payload, document)
            if not ok:
                return False, None, code, detail
            values.append(value)
        if op == "add":
            result = values[0] + values[1]
        elif op == "sub":
            result = values[0] - values[1]
        elif op == "mul":
            result = values[0] * values[1]
        elif op == "div":
            if values[1] == 0:
                return (
                    False,
                    None,
                    "DIVISION_BY_ZERO",
                    "derived %r: division by zero" % name,
                )
            result = values[0] / values[1]
        elif op == "min":
            result = min(values)
        else:
            result = max(values)
        return True, result, None, None

    return compute
