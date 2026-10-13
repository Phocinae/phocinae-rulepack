"""A YAML-subset parser, so the runtime needs no third-party dependency.

This is deliberately small. It supports exactly the constructs the rule-pack
format uses, and it **raises on anything else** rather than guessing — an
unsupported construct must fail loudly (``E_YAML``), never be silently dropped.

Supported
    * nested block mappings and block sequences, 2-space indentation
    * flow collections: ``[a, b]`` and ``{a: 1, b: 2}`` (one line)
    * plain, single-quoted and double-quoted scalars (with ``\\n`` escapes)
    * block scalars: ``|`` (literal) and ``>`` (folded), with ``-``/``+`` chomping
    * comments (``#`` at line start or after whitespace, outside quotes)
    * ``true``/``false``/``null``/``~``, integers, floats
    * an optional leading ``---`` document marker

Not supported (raises)
    * anchors/aliases (``&``/``*``), tags (``!!``), multiple documents
    * multi-line flow collections, tabs used for indentation
    * merge keys (``<<``)

When PyYAML is importable, :func:`load` uses it instead and cross-checks the
result against the built-in parser. ``$PHOCINAE_RULEPACK_PYYAML=1`` forces this
on and turns a cross-check disagreement into a hard error.
"""

from __future__ import annotations

import os
import re

from .errors import PackError

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
# YAML separates a key from its value at a colon that is followed by a space or
# by the end of the line. Requiring that is what keeps `http://x/y#L1-L2` and
# `12:30` from being read as mappings with the keys `http` and `12`.
_KEY_RE = re.compile(r"^([^:#]+?):(?:[ \t]+(.*))?$")


def _fail(message, lineno=None):
    where = "" if lineno is None else " (line %d)" % lineno
    raise PackError("E_YAML", "%s%s" % (message, where))


def _strip_comment(text):
    """Remove an unquoted ``#`` comment from a scalar tail."""
    out = []
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#" and (i == 0 or text[i - 1] in " \t"):
            break
        out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _scalar(token, lineno):
    """Convert one scalar token into a Python value."""
    if token == "":
        return None
    if token[0] == '"':
        if len(token) < 2 or token[-1] != '"':
            _fail("unterminated double-quoted scalar", lineno)
        body = token[1:-1]
        try:
            return _unescape_double(body)
        except ValueError as exc:
            _fail("bad escape in %r: %s" % (token, exc), lineno)
    if token[0] == "'":
        if len(token) < 2 or token[-1] != "'":
            _fail("unterminated single-quoted scalar", lineno)
        return token[1:-1].replace("''", "'")
    lowered = token.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if lowered in ("null", "~"):
        return None
    if _INT_RE.match(token):
        return int(token)
    if _FLOAT_RE.match(token) and any(c in token for c in ".eE"):
        return float(token)
    return token


def _unescape_double(body):
    out = []
    i = 0
    simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "0": "\0"}
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(body):
            raise ValueError("trailing backslash")
        esc = body[i]
        if esc in simple:
            out.append(simple[esc])
            i += 1
            continue
        if esc == "u":
            hexpart = body[i + 1 : i + 5]
            if len(hexpart) != 4:
                raise ValueError("short \\u escape")
            out.append(chr(int(hexpart, 16)))
            i += 5
            continue
        raise ValueError("unsupported escape \\%s" % esc)
    return "".join(out)


def _split_flow(body, lineno):
    """Split a flow collection body on top-level commas."""
    parts = []
    depth = 0
    quote = None
    current = []
    i = 0
    while i < len(body):
        ch = body[i]
        if quote:
            current.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(body):
                current.append(body[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            current.append(ch)
            i += 1
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail or parts:
        parts.append(tail)
    return parts


def _flow_value(token, lineno):
    """Parse a value that may be a flow collection or a scalar."""
    token = token.strip()
    if token.startswith("[") or token.startswith("{"):
        closing = "]" if token[0] == "[" else "}"
        if not token.endswith(closing):
            _fail("multi-line flow collections are not supported", lineno)
        body = token[1:-1].strip()
        if body == "":
            return [] if closing == "]" else {}
        items = _split_flow(body, lineno)
        if closing == "]":
            return [_flow_value(item, lineno) for item in items]
        result = {}
        for item in items:
            match = _KEY_RE.match(item)
            if not match:
                _fail("bad flow mapping entry %r" % item, lineno)
            key = _scalar(match.group(1).strip(), lineno)
            result[key] = _flow_value(match.group(2) or "", lineno)
        return result
    return _scalar(token, lineno)


class _Lines(object):
    def __init__(self, text):
        self.raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.i = 0
        self.n = len(self.raw)

    def peek(self):
        """Return (indent, content, lineno) of the next significant line."""
        while self.i < self.n:
            line = self.raw[self.i]
            if "\t" in line[: len(line) - len(line.lstrip())]:
                _fail("tab used for indentation", self.i + 1)
            stripped = line.lstrip(" ")
            if stripped.strip() == "" or stripped.lstrip().startswith("#"):
                self.i += 1
                continue
            if stripped.rstrip() == "---":
                self.i += 1
                continue
            return len(line) - len(stripped), stripped, self.i + 1
        return None


def _read_block_scalar(lines, indent, header):
    """Read a ``|``/``>`` block scalar body starting after the header line."""
    style = header[0]
    chomp = ""
    for ch in header[1:]:
        if ch in "+-":
            chomp = ch
        else:
            _fail("unsupported block scalar header %r" % header)
    body = []
    body_indent = None
    while lines.i < lines.n:
        raw = lines.raw[lines.i]
        if raw.strip() == "":
            body.append("")
            lines.i += 1
            continue
        current = len(raw) - len(raw.lstrip(" "))
        if current <= indent:
            break
        if body_indent is None:
            body_indent = current
        body.append(raw[body_indent:])
        lines.i += 1
    while body and body[-1] == "":
        body.pop()
    if style == "|":
        text = "\n".join(body)
    else:
        folded = []
        for entry in body:
            if entry == "":
                folded.append("\n")
            elif folded and not folded[-1].endswith("\n"):
                folded.append(" " + entry)
            else:
                folded.append(entry)
        text = "".join(folded)
    if chomp == "-":
        return text
    if chomp == "+":
        return text + "\n"
    return text + "\n" if body else text


def _parse_node(lines, indent):
    """Parse the node introduced by an empty value.

    YAML has no fixed indent step: the block that belongs to a key starts at
    whatever column the next more-indented line uses. So we parse at *that*
    column rather than at ``indent + 1`` -- otherwise a sequence nested under an
    inline sequence item (``- any_of:`` followed by items indented 4 deeper)
    gets swallowed into the wrong parent, which silently rewrites the condition.
    """
    head = lines.peek()
    if head is None:
        return None
    current_indent, content, _lineno = head
    if current_indent < indent:
        return None
    if content.startswith("- ") or content == "-":
        return _parse_sequence(lines, current_indent)
    return _parse_mapping(lines, current_indent)


def _parse_sequence(lines, indent):
    items = []
    while True:
        head = lines.peek()
        if head is None:
            break
        current_indent, content, lineno = head
        if current_indent != indent or not (content == "-" or content.startswith("- ")):
            break
        lines.i += 1
        # Column at which this item's own content starts. For "- foo: bar" the
        # scalar keys of that mapping continue at this column, not at indent+2.
        item_indent = indent + 1
        if content.startswith("- "):
            offset = len(content) - len(content[1:].lstrip())
            item_indent = indent + offset
        rest = content[1:].strip()
        if rest == "":
            child = _parse_node(lines, indent + 1)
            items.append(child if child is not None else None)
            continue
        if rest in ("|", "|-", "|+", ">", ">-", ">+"):
            items.append(_read_block_scalar(lines, indent, rest))
            continue
        if rest.startswith("&") or rest.startswith("*") or rest.startswith("!"):
            _fail("anchors, aliases and tags are not supported", lineno)
        match = _KEY_RE.match(rest)
        if (
            match
            and not rest.startswith("[")
            and not rest.startswith("{")
            and not _scalar_is_collection_indicator(rest)
        ):
            entry = {}
            _consume_mapping_entry(lines, entry, match, item_indent, lineno)
            deeper = _parse_mapping(lines, item_indent)
            if deeper:
                entry.update(deeper)
            items.append(entry)
            continue
        items.append(_flow_value(rest, lineno))
        # A bare scalar sequence item must not be followed by a deeper block.
        nxt = lines.peek()
        if nxt is not None and nxt[0] > indent:
            _fail("unexpected indented block after scalar sequence item", nxt[2])
    return items


def _scalar_is_collection_indicator(text):
    """True when a 'key: value' match is really a flow collection or URL-ish text."""
    if "://" in text:
        return True
    return False


def _consume_mapping_entry(lines, target, match, indent, lineno):
    """Store one 'key: value' pair, recursing for empty values and block scalars."""
    key = _scalar(match.group(1).strip(), lineno)
    if key == "<<":
        _fail("merge keys are not supported", lineno)
    value_token = (match.group(2) or "").strip()
    if value_token in ("|", "|-", "|+", ">", ">-", ">+"):
        target[key] = _read_block_scalar(lines, indent, value_token)
        return
    if value_token == "":
        target[key] = _parse_node(lines, indent + 1)
        return
    if value_token.startswith("&") or value_token.startswith("*") or value_token.startswith("!!"):
        _fail("tags, anchors and aliases are not supported", lineno)
    if value_token in ("&", "*"):
        _fail("anchors and aliases are not supported", lineno)
    target[key] = _flow_value(value_token, lineno)


def _parse_mapping(lines, indent, allow_less=True):
    result = {}
    while True:
        head = lines.peek()
        if head is None:
            break
        current_indent, content, lineno = head
        if current_indent < indent:
            break
        if current_indent > indent:
            _fail("unexpected indentation", lineno)
        if content.startswith("- ") or content == "-":
            break
        match = _KEY_RE.match(content)
        if not match:
            _fail("expected 'key: value' but found %r" % content, lineno)
        lines.i += 1
        _consume_mapping_entry(lines, result, match, indent, lineno)
    return result


def loads_subset(text):
    """Parse with the built-in subset parser only."""
    if not isinstance(text, str):
        raise PackError("E_YAML", "expected text, got %s" % type(text).__name__)
    if "\t" in text:
        for offset, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
            prefix = line[: len(line) - len(line.lstrip())]
            if "\t" in prefix:
                _fail("tab used for indentation", offset)
    lines = _Lines(text)
    head = lines.peek()
    if head is None:
        raise PackError("E_YAML", "document is empty")
    value = _parse_node(lines, head[0])
    leftover = lines.peek()
    if leftover is not None:
        _fail("trailing content after document: %r" % leftover[1], leftover[2])
    return value


def _pyyaml_available():
    try:
        import yaml  # noqa: F401
    except Exception:
        return False
    return True


def load(text):
    """Parse YAML text.

    Uses PyYAML when available (it is a test-only optional dependency) and
    cross-checks the built-in parser against it; otherwise uses the subset
    parser alone. Set ``$PHOCINAE_RULEPACK_PYYAML=1`` to make the cross-check
    mandatory — a disagreement then becomes a hard error rather than a
    silent preference for one parser.
    """
    builtin = loads_subset(text)
    forced = os.environ.get("PHOCINAE_RULEPACK_PYYAML") == "1"
    if not _pyyaml_available():
        if forced:
            raise PackError(
                "E_YAML",
                "PHOCINAE_RULEPACK_PYYAML=1 but PyYAML is not importable",
            )
        return builtin
    import yaml

    try:
        reference = yaml.safe_load(text)
    except Exception as exc:  # pragma: no cover - depends on optional dep
        raise PackError("E_YAML", "PyYAML rejected the document: %s" % exc)
    if reference != builtin:
        raise PackError(
            "E_YAML",
            "built-in YAML subset parser and PyYAML disagree; refusing to guess "
            "(builtin=%r pyyaml=%r)" % (builtin, reference),
        )
    return builtin


def load_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        return load(handle.read())
