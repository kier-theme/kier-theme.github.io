#!/usr/bin/env python3
"""Kier — build the website from the palette.

Reads ``core/palette/kier.json`` and ``core/palette/mappings.json`` and emits a
static site into this directory. Python 3 standard library only, no build step
needed to *view* the result — the emitted files are committed.

    python3 web/generate.py

Emits:
    web/index.html    the page (structure from src/template.html)
    web/kier.css      every colour, as custom properties, one block per flavour
    web/palette.js    the palette data + precomputed contrast, as window.KIER
    web/app.js        behaviour (copied verbatim from src/app.js)

Rule: no hex colour is ever typed into this file, the template, or app.js.
Every colour in the output traces back to kier.json.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "src"
PALETTE_PATH = ROOT / "core" / "palette" / "kier.json"
MAPPINGS_PATH = ROOT / "core" / "palette" / "mappings.json"

CONTRAST_FLOOR = 5.0


# --------------------------------------------------------------------------- #
# colour maths (WCAG relative luminance; mirrors core/tools/colorlib.py)
# --------------------------------------------------------------------------- #

def _channels(hex_colour: str) -> tuple[float, float, float]:
    raw = hex_colour.lstrip("#")
    return tuple(int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(hex_colour: str) -> float:
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
           for c in _channels(hex_colour)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def oklab(hex_colour: str) -> tuple[float, float, float]:
    """Same transform as core/tools/build_palette.py, so the site quotes the
    same number the build gate does."""
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
               for c in _channels(hex_colour))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def delta_e(a: str, b: str) -> float:
    x, y = oklab(a), oklab(b)
    return sum((x[i] - y[i]) ** 2 for i in range(3)) ** 0.5


# The roles core/tools/validate.py measures separation across: the ones that
# actually share a line of code. Diagnostic roles (error/warning/info/hint) are
# excluded there and here — they never sit adjacent to a keyword.
SEPARATION_ROLES = [
    "keyword", "string", "function", "number", "variable", "comment", "operator",
    "variable.parameter", "variable.member", "constant", "namespace", "type",
    "attribute", "string.regex", "string.escape", "function.call", "punctuation",
]


def closest_role_pair(palette: dict) -> tuple[float, str, str, str]:
    """Tightest non-aliased syntax pair anywhere in the set, in OKLab.

    Mirrors the check in core/tools/validate.py so the site quotes the same
    figure the build gate enforces. Pairs that share a palette token, or that
    kier.json declares as aliases, are separation-exempt by construction."""
    aliases = {tuple(sorted(pair)) for pair in palette["aliases"]}
    best = (float("inf"), "", "", "")
    for fid, flavour in palette["flavours"].items():
        syntax = flavour["syntax"]
        roles = [r for r in SEPARATION_ROLES if r in syntax]
        for i, a in enumerate(roles):
            for b in roles[i + 1:]:
                if syntax[a]["token"] == syntax[b]["token"]:
                    continue
                if tuple(sorted((a, b))) in aliases:
                    continue
                d = delta_e(syntax[a]["color"], syntax[b]["color"])
                if d < best[0]:
                    best = (d, flavour["name"], a, b)
    return best


def warm_span(palette: dict) -> tuple[int, int, int]:
    """How many accents crowd the warm end, and the arc they occupy."""
    import colorsys
    flavour = palette["flavours"][next(iter(palette["flavours"]))]
    hues = []
    for token in palette["accentOrder"]:
        r, g, b = _channels(flavour["accents"][token])
        hues.append(colorsys.rgb_to_hls(r, g, b)[0] * 360.0)
    warm = [h for h in hues if h >= 300.0 or h <= 60.0]
    lo = min((h for h in warm if h >= 300.0), default=min(warm))
    hi = max((h for h in warm if h <= 60.0), default=max(warm))
    return len(warm), round(lo), round(hi)


# --------------------------------------------------------------------------- #
# tokenizer
# --------------------------------------------------------------------------- #
#
# A small, deliberately unambitious scanner. It is not a parser and does not
# need to be: its only job is to put real code on the page wearing the role
# names that kier.json actually defines, so the colours are the palette's and
# not a guess. Roles emitted here must exist in `syntaxRoles`.

Token = tuple[str, str]  # (role, text)

KEYWORDS = {
    "rust": {
        "control": {"if", "else", "match", "loop", "while", "for", "in", "break",
                    "continue", "return", "await", "yield"},
        "keyword": {"fn", "let", "mut", "impl", "trait", "where", "as", "move",
                    "ref", "dyn", "unsafe", "async", "pub", "crate", "super"},
        "storage": {"struct", "enum", "type", "const", "static", "union"},
        "import": {"use", "mod", "extern"},
        "boolean": {"true", "false"},
        "builtin_type": {"u8", "u16", "u32", "u64", "usize", "i8", "i16", "i32",
                         "i64", "isize", "f32", "f64", "bool", "char", "str"},
        "builtin_var": {"self", "Self"},
    },
    "typescript": {
        "control": {"if", "else", "switch", "case", "default", "for", "while",
                    "do", "break", "continue", "return", "throw", "try", "catch",
                    "finally", "await", "yield"},
        "keyword": {"function", "class", "extends", "implements", "new", "this",
                    "typeof", "instanceof", "in", "of", "as", "async", "static",
                    "public", "private", "protected", "abstract", "declare",
                    "keyof", "satisfies", "is", "infer"},
        "storage": {"const", "let", "var", "readonly", "interface", "type",
                    "enum", "namespace"},
        "import": {"import", "export", "from", "require"},
        "boolean": {"true", "false"},
        "builtin_type": {"string", "number", "boolean", "void", "never", "any",
                         "unknown", "object", "symbol", "bigint", "Record",
                         "Promise", "Array", "Partial", "Readonly"},
        "builtin_var": {"this", "super"},
        "constant": {"null", "undefined", "NaN", "Infinity"},
    },
    "python": {
        "control": {"if", "elif", "else", "for", "while", "break", "continue",
                    "return", "yield", "try", "except", "finally", "raise",
                    "with", "match", "case", "pass", "await"},
        "keyword": {"def", "lambda", "and", "or", "not", "in", "is", "as",
                    "assert", "del", "global", "nonlocal", "async"},
        "storage": {"class"},
        "import": {"import", "from"},
        "boolean": {"True", "False"},
        "constant": {"None", "Ellipsis"},
        "builtin_type": {"int", "float", "str", "bool", "bytes", "list", "dict",
                         "set", "tuple", "frozenset", "type", "object"},
        "builtin_fn": {"print", "len", "range", "sorted", "round", "isinstance",
                       "open", "enumerate", "zip", "map", "filter", "sum", "min",
                       "max", "abs", "repr", "getattr", "setattr", "super"},
        "builtin_var": {"self", "cls"},
    },
    "toml": {},
}

# Ordered scan rules. First match at a position wins.
RULES: dict[str, list[tuple[str, str]]] = {
    "rust": [
        ("comment.doc", r"//[!/].*"),
        ("comment", r"//.*|/\*(?:[^*]|\*(?!/))*\*/"),
        ("attribute", r"#!?\[(?:[^\[\]]|\[[^\]]*\])*\]"),
        ("string", r'r?#*"(?:\\.|[^"\\])*"'),
        ("character", r"'(?:\\.|[^'\\])'"),
        ("label", r"'[A-Za-z_][A-Za-z0-9_]*"),
        ("function.macro", r"[A-Za-z_][A-Za-z0-9_]*!"),
        ("number", r"\b\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?"
                   r"(?:f32|f64|u8|u16|u32|u64|usize|i8|i16|i32|i64|isize)?\b"),
        ("@ident", r"[A-Za-z_][A-Za-z0-9_]*"),
        ("punctuation.bracket", r"[\[\]{}()]"),
        ("punctuation.delimiter", r"[,;]"),
        ("punctuation", r"::|\.|=>|->|\?"),
        ("operator", r"[-+*/%!&|^<>=~]+"),
    ],
    "typescript": [
        ("comment.doc", r"/\*\*(?:[^*]|\*(?!/))*\*/"),
        ("comment", r"//.*|/\*(?:[^*]|\*(?!/))*\*/"),
        ("attribute", r"@[A-Za-z_][A-Za-z0-9_]*"),
        ("string", r"`(?:\\.|[^`\\])*`|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'"),
        ("string.regex", r"(?<=[=(,:]\s)/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n])+/[gimsuy]*"),
        ("number", r"\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?n?\b"),
        ("@ident", r"[A-Za-z_$][A-Za-z0-9_$]*"),
        ("punctuation.bracket", r"[\[\]{}()]"),
        ("punctuation.delimiter", r"[,;]"),
        ("punctuation", r"\.\.\.|\.|=>|\?\.|[?:]"),
        ("operator", r"[-+*/%!&|^<>=~]+"),
    ],
    "python": [
        ("comment.doc", r'(?:[rRbBfFuU]{0,2})"""(?:[^"\\]|\\.|"(?!""))*"""'
                        r"|(?:[rRbBfFuU]{0,2})'''(?:[^'\\]|\\.|'(?!''))*'''"),
        ("comment", r"#.*"),
        ("attribute", r"@[A-Za-z_][A-Za-z0-9_.]*"),
        ("string", r'(?:[rRbBfFuU]{0,2})"(?:\\.|[^"\\])*"'
                   r"|(?:[rRbBfFuU]{0,2})'(?:\\.|[^'\\])*'"),
        ("number", r"\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b"),
        ("@ident", r"[A-Za-z_][A-Za-z0-9_]*"),
        ("punctuation.bracket", r"[\[\]{}()]"),
        ("punctuation.delimiter", r"[,;]"),
        ("punctuation", r"->|\.|:"),
        ("operator", r"[-+*/%!&|^<>=~]+"),
    ],
    "toml": [
        ("comment", r"#.*"),
        ("@table", r"^\s*\[\[?[^\]\n]+\]\]?", re.M),
        ("@key", r"^\s*[A-Za-z_][A-Za-z0-9_.-]*(?=\s*=)", re.M),
        ("string", r'"""(?:[^"\\]|\\.|"(?!""))*"""|"(?:\\.|[^"\\])*"'
                   r"|'(?:[^'])*'"),
        ("boolean", r"\b(?:true|false)\b"),
        ("number", r"\b\d[\d_]*(?:\.\d+)?\b"),
        ("punctuation.bracket", r"[\[\]{}]"),
        ("punctuation.delimiter", r"[,]"),
        ("operator", r"="),
        ("@ident", r"[A-Za-z_][A-Za-z0-9_-]*"),
    ],
}

ESCAPE_RE = re.compile(r"\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|.)")
FSTRING_RE = re.compile(r"\{[^{}\n]+\}")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _compiled(lang: str) -> re.Pattern[str]:
    parts = []
    for i, rule in enumerate(RULES[lang]):
        name, pattern = rule[0], rule[1]
        parts.append(f"(?P<r{i}>{pattern})")
    return re.compile("|".join(parts), re.M)


def _classify_ident(lang: str, word: str, before: str, after: str) -> str:
    """Give a bare identifier a role from the surrounding punctuation."""
    kw = KEYWORDS[lang]
    if word in kw.get("control", ()):
        return "keyword.control"
    if word in kw.get("import", ()):
        return "keyword.import"
    if word in kw.get("storage", ()):
        return "storage"
    if word in kw.get("boolean", ()):
        return "boolean"
    if word in kw.get("constant", ()):
        return "constant.builtin"
    if word in kw.get("builtin_var", ()):
        return "variable.builtin"
    if word in kw.get("keyword", ()):
        return "keyword"
    if word in kw.get("builtin_fn", ()) and after.startswith("("):
        return "function.builtin"
    if word in kw.get("builtin_type", ()):
        return "type.builtin"

    dotted = before.endswith(".")
    call = after.startswith("(") or after.startswith("<(")

    if word.isupper() and len(word) > 1:
        return "constant"
    if word[:1].isupper():
        return "constructor" if call else "type"
    if call:
        return "function.method" if dotted else "function"
    if dotted:
        return "variable.member"
    if lang == "typescript" and (after.startswith("?") or
                                 (after.startswith(":") and not after.startswith("::"))):
        return "property"
    if lang == "rust" and after.startswith("::"):
        return "namespace"
    if lang == "rust" and before.endswith("::"):
        return "variable.member"
    return "variable"


def _split_escapes(role: str, text: str, escape_role: str = "string.escape") -> list[Token]:
    out: list[Token] = []
    pos = 0
    for m in ESCAPE_RE.finditer(text):
        if m.start() > pos:
            out.append((role, text[pos:m.start()]))
        out.append((escape_role, m.group()))
        pos = m.end()
    if pos < len(text):
        out.append((role, text[pos:]))
    return out or [(role, text)]


def _split_fstring(text: str) -> list[Token]:
    out: list[Token] = []
    pos = 0
    for m in FSTRING_RE.finditer(text):
        if m.start() > pos:
            out.extend(_split_escapes("string", text[pos:m.start()]))
        out.append(("string.special", m.group()))
        pos = m.end()
    if pos < len(text):
        out.extend(_split_escapes("string", text[pos:]))
    return out


def _mark_parameters(lang: str, tokens: list[Token]) -> list[Token]:
    """Second pass: identifiers in a definition's parameter list wear `iris`."""
    if lang not in ("rust", "python", "typescript"):
        return tokens
    openers = {"rust": {"fn"}, "python": {"def"}, "typescript": {"function"}}[lang]
    out = list(tokens)
    armed = False
    depth = 0
    seen_name = False
    prev_sig = ""
    for i, (role, text) in enumerate(out):
        stripped = text.strip()
        if not stripped:
            continue
        if not armed:
            if text in openers and role in ("keyword", "storage", "keyword.control"):
                armed, seen_name, depth = True, False, 0
            continue
        if not seen_name:
            if stripped == "(":
                seen_name = True
                depth = 1
            elif role.startswith("function"):
                seen_name = False
            continue
        if stripped == "(":
            depth += 1
        elif stripped == ")":
            depth -= 1
            if depth <= 0:
                armed = False
            continue
        if depth == 1 and role in ("variable", "property") and prev_sig in ("(", ","):
            out[i] = ("variable.parameter", text)
        prev_sig = stripped[-1:] if stripped else prev_sig
    return out


def _mark_imports(lang: str, tokens: list[Token]) -> list[Token]:
    """`import json` / `from pathlib import Path` — the module is a namespace."""
    if lang != "python":
        return tokens
    out = list(tokens)
    on_import = False
    for i, (role, text) in enumerate(out):
        if "\n" in text:
            on_import = False
        if role == "keyword.import":
            on_import = True
            continue
        if on_import and role == "variable":
            out[i] = ("namespace", text)
    return out


def tokenize(lang: str, source: str) -> list[Token]:
    rules = RULES[lang]
    pattern = _compiled(lang)
    tokens: list[Token] = []
    pos = 0
    for m in pattern.finditer(source):
        if m.start() > pos:
            tokens.append(("", source[pos:m.start()]))
        idx = int(m.lastgroup[1:])  # type: ignore[union-attr]
        role = rules[idx][0]
        text = m.group()

        if role == "@ident":
            after = source[m.end():m.end() + 2].lstrip()
            before = source[max(0, m.start() - 2):m.start()].rstrip()
            role = _classify_ident(lang, text, before, after)
        elif role == "@table":
            lead = len(text) - len(text.lstrip())
            if lead:
                tokens.append(("", text[:lead]))
                text = text.lstrip()
            open_n = len(text) - len(text.lstrip("["))
            close_n = len(text) - len(text.rstrip("]"))
            tokens.append(("punctuation.bracket", text[:open_n]))
            tokens.append(("namespace", text[open_n:len(text) - close_n]))
            tokens.append(("punctuation.bracket", text[len(text) - close_n:]))
            pos = m.end()
            continue
        elif role == "@key":
            lead = len(text) - len(text.lstrip())
            if lead:
                tokens.append(("", text[:lead]))
                text = text.lstrip()
            role = "property"

        if role == "string" and lang == "python" and text[:1] in "fF":
            tokens.extend(_split_fstring(text))
        elif role in ("string", "character"):
            tokens.extend(_split_escapes(role, text))
        elif role == "attribute" and lang == "rust":
            tokens.extend(_split_rust_attribute(text))
        else:
            tokens.append((role, text))
        pos = m.end()
    if pos < len(source):
        tokens.append(("", source[pos:]))
    return _mark_imports(lang, _mark_parameters(lang, tokens))


def _split_rust_attribute(text: str) -> list[Token]:
    """`#[derive(Debug, Clone)]` — keep the type names reading as types."""
    out: list[Token] = []
    pos = 0
    for m in IDENT_RE.finditer(text):
        word = m.group()
        if not word[:1].isupper():
            continue
        if m.start() > pos:
            out.append(("attribute", text[pos:m.start()]))
        out.append(("type", word))
        pos = m.end()
    if pos < len(text):
        out.append(("attribute", text[pos:]))
    return out or [("attribute", text)]


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def role_class(role: str) -> str:
    return "t-" + role.replace(".", "-")


def render_code(lang: str, source: str) -> str:
    """Tokens -> line-wrapped HTML. Multi-line tokens are split per line so the
    gutter counter stays honest."""
    lines: list[list[Token]] = [[]]
    for role, text in tokenize(lang, source.rstrip("\n")):
        chunks = text.split("\n")
        for i, chunk in enumerate(chunks):
            if i:
                lines.append([])
            if chunk:
                lines[-1].append((role, chunk))

    out = []
    for line in lines:
        spans = []
        for role, text in line:
            esc = html.escape(text, quote=False)
            spans.append(esc if not role else
                         f'<span class="{role_class(role)}">{esc}</span>')
        out.append('<span class="cl">' + "".join(spans) + "</span>")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #

def css_var_block(flavour: dict, selector: str) -> str:
    lines = [f"{selector} {{"]
    lines.append("  /* neutrals */")
    for token, hexv in flavour["neutrals"].items():
        lines.append(f"  --n-{token}: {hexv};")
    lines.append("  /* accents */")
    for token, hexv in flavour["accents"].items():
        lines.append(f"  --a-{token}: {hexv};")
    lines.append("  /* ui */")
    for token, hexv in flavour["ui"].items():
        name = re.sub(r"(?<!^)(?=[A-Z])", "-", token).lower()
        lines.append(f"  --ui-{name}: {hexv};")
    lines.append("  /* syntax roles */")
    for role, spec in flavour["syntax"].items():
        lines.append(f"  --sy-{role.replace('.', '-')}: {spec['color']};")
    lines.append("}")
    return "\n".join(lines)


STYLE_DECL = {
    "italic": "font-style: italic;",
    "bold": "font-weight: 700;",
    "underline": "text-decoration: underline;",
    "strikethrough": "text-decoration: line-through;",
}


def build_css(palette: dict) -> str:
    flavours = palette["flavours"]
    first = flavours[list(flavours)[0]]

    out = [
        "/* Kier — generated by web/generate.py from core/palette/kier.json.",
        "   Do not edit by hand: every value here is owned by the palette. */",
        "",
    ]

    # Default (no data-flavour yet, e.g. before JS runs) = the first flavour.
    out.append(css_var_block(first, ":root"))
    out.append("")
    for fid, flavour in flavours.items():
        out.append(css_var_block(flavour, f':root[data-flavour="{fid}"]'))
        out.append("")

    # Per-flavour swatch dots for the switcher, so a pill shows its own colour
    # even while another flavour is active.
    out.append("/* switcher dots: each pill always shows its own flavour */")
    for fid, flavour in flavours.items():
        out.append(
            f'.pill[data-flavour="{fid}"] .pill-dot {{ '
            f'background: {flavour["ui"]["accent"]}; }}'
        )
        out.append(
            f'.pill[data-flavour="{fid}"] .pill-dot::after {{ '
            f'background: {flavour["neutrals"]["base"]}; }}'
        )
    out.append("")

    # Syntax role classes — one per role in syntaxRoles.
    out.append("/* syntax roles */")
    for role, spec in first["syntax"].items():
        safe = role.replace(".", "-")
        decl = f"color: var(--sy-{safe});"
        style = spec.get("style")
        if style in STYLE_DECL:
            decl += " " + STYLE_DECL[style]
        out.append(f".t-{safe} {{ {decl} }}")
    out.append("")

    # The 12-wedge disco disc in the hero: one wedge per accent.
    out.append("/* hero disc: one wedge per accent, in accentOrder */")
    for token in palette["accentOrder"]:
        out.append(f'.wedge[data-accent="{token}"] {{ fill: var(--a-{token}); }}')
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# data for the runtime
# --------------------------------------------------------------------------- #

def build_palette_js(palette: dict, mappings: dict) -> str:
    data = {
        "name": palette["name"],
        "version": palette["version"],
        "accentOrder": palette["accentOrder"],
        "neutralOrder": palette["neutralOrder"],
        "defaultAccent": palette["defaultAccent"],
        "roleCount": len(palette["syntaxRoles"]),
        "aliasCount": len(palette["aliases"]),
        "aliases": palette["aliases"],
        "flavours": {},
        "ecosystems": {},
    }

    for fid, fl in palette["flavours"].items():
        base = fl["neutrals"]["base"]
        text = fl["neutrals"]["text"]
        accents = {}
        for token in palette["accentOrder"]:
            hexv = fl["accents"][token]
            accents[token] = {
                "hex": hexv,
                "contrast": round(contrast(hexv, base), 2),
            }
        neutrals = {}
        for token in palette["neutralOrder"]:
            hexv = fl["neutrals"][token]
            neutrals[token] = {
                "hex": hexv,
                "contrast": round(contrast(hexv, base), 2),
            }
        worst = min(accents.items(), key=lambda kv: kv[1]["contrast"])
        data["flavours"][fid] = {
            "id": fid,
            "name": fl["name"],
            "order": fl["order"],
            "reference": fl["reference"],
            "blurb": fl["blurb"],
            "accent": fl["ui"]["accent"],
            "neutrals": neutrals,
            "accents": accents,
            "textContrast": round(contrast(text, base), 1),
            "minAccent": {"token": worst[0], "ratio": worst[1]["contrast"]},
            "ansi": fl["ansi"],
        }

    for eco, spec in mappings["ecosystems"].items():
        roles = len(spec["map"])
        scopes = sum(len(v) if isinstance(v, list) else 1 for v in spec["map"].values())
        data["ecosystems"][eco] = {"uses": spec["uses"], "roles": roles, "scopes": scopes}

    header = ("/* Kier — generated by web/generate.py from core/palette/kier.json.\n"
              "   Inlined rather than fetched so the page works from file://. */\n")
    return header + "window.KIER = " + json.dumps(data, indent=1, sort_keys=False) + ";\n"


# --------------------------------------------------------------------------- #
# specimen placeholders
# --------------------------------------------------------------------------- #
#
# A specimen may not type a hex either. `@n:base@`, `@a:tangerine@`, `@u:cursor@`
# and `@x:bright_red@` resolve against the default flavour at build time, which
# is how the config sample below can show real generated output.

PLACEHOLDER_RE = re.compile(r"@([naux]):([A-Za-z0-9_.]+)@")
_SECTION = {"n": "neutrals", "a": "accents", "u": "ui", "x": "ansi"}


def resolve_placeholders(text: str, palette: dict, flavour_id: str | None = None) -> str:
    flavour = palette["flavours"][flavour_id or next(iter(palette["flavours"]))]

    def sub(m: re.Match[str]) -> str:
        section, token = _SECTION[m.group(1)], m.group(2)
        try:
            return flavour[section][token]
        except KeyError:
            raise SystemExit(f"specimen asks for unknown colour {m.group(0)}") from None

    return PLACEHOLDER_RE.sub(sub, text)


def palette_colours(palette: dict) -> set[str]:
    """Every hex kier.json contains, for the output audit."""
    seen: set[str] = set()
    for flavour in palette["flavours"].values():
        for key in ("neutrals", "accents", "ui", "ansi"):
            seen.update(v.upper() for v in flavour[key].values())
        seen.update(spec["color"].upper() for spec in flavour["syntax"].values())
    return seen


# --------------------------------------------------------------------------- #
# page fragments
# --------------------------------------------------------------------------- #

PORT_GROUPS = [
    ("Editors", "Where the palette does most of its work.", [
        ("nvim", "Neovim", "treesitter + LSP semantic tokens, all five flavours"),
        ("vscode", "VS Code", "TextMate scopes and semantic highlighting"),
        ("emacs", "Emacs", "font-lock and treesit faces, Emacs 29+"),
        ("jetbrains", "JetBrains", "IntelliJ, PyCharm, GoLand, RustRover, the lot"),
        ("fleet", "Fleet", "JetBrains' lightweight editor"),
        ("obsidian", "Obsidian", "editor, reading view and code fences"),
    ]),
    ("Terminal", "The prompt, the pager and everything piped through them.", [
        ("ghostty", "Ghostty", "full ANSI 16 plus cursor and selection"),
        ("bat", "bat", "sublime-syntax themes for the better cat"),
        ("btop", "btop", "graphs, gauges and process table"),
        ("fzf", "fzf", "an env var per flavour, drop it in your shell rc"),
        ("starship", "Starship", "prompt modules coloured by role, not by guess"),
        ("tmux", "tmux", "status line, panes, copy-mode"),
        ("zellij", "Zellij", "KDL themes, one per flavour"),
        ("eza", "eza", "LS_COLORS for the modern ls"),
    ]),
    ("Desktop", "Grounds carried straight back to where they came from.", [
        ("cosmic", "COSMIC", "the original five hand-tuned desktop themes"),
        ("grub", "GRUB", "the theme you see before anything else loads"),
    ]),
    ("Browser", "For the other place you read text all day.", [
        ("firefox", "Firefox", "chrome theme and userChrome tweaks"),
        ("chrome", "Chrome", "packed extension per flavour"),
        ("darkreader", "Dark Reader", "import a flavour, recolour the web"),
    ]),
]

SPECIMENS = [
    ("rust", "Rust", "flavour.rs"),
    ("typescript", "TypeScript", "palette.ts"),
    ("python", "Python", "build_theme.py"),
    ("toml", "TOML", "kier.toml"),
]

def frag_flavour_pills(palette: dict) -> str:
    out = []
    ordered = sorted(palette["flavours"].values(), key=lambda f: f["order"])
    for fl in ordered:
        out.append(
            f'      <button class="pill" type="button" '
            f'aria-pressed="false" data-flavour="{fl["id"]}" '
            f'id="pill-{fl["id"]}" title="{html.escape(fl["reference"], quote=True)}">'
            f'<span class="pill-dot" aria-hidden="true"></span>'
            f'<span class="pill-name">{html.escape(fl["name"])}</span>'
            f'</button>'
        )
    return "\n".join(out)


def frag_flavour_cards(palette: dict) -> str:
    out = []
    for fl in sorted(palette["flavours"].values(), key=lambda f: f["order"]):
        out.append(
            f'''      <button class="fcard" type="button" data-flavour="{fl["id"]}">
        <span class="fcard-strip" aria-hidden="true"></span>
        <span class="fcard-body">
          <span class="fcard-name">{html.escape(fl["name"])}</span>
          <span class="fcard-ref">{html.escape(fl["reference"])}</span>
          <span class="fcard-blurb">{html.escape(fl["blurb"])}</span>
        </span>
      </button>'''
        )
    return "\n".join(out)


def frag_disc(palette: dict) -> str:
    """A twelve-wedge disc, one wedge per accent. Disco geometry, honest data."""
    import math
    n = len(palette["accentOrder"])
    r_out, r_in, cx, cy = 100.0, 34.0, 0.0, 0.0
    parts = []
    for i, token in enumerate(palette["accentOrder"]):
        a0 = (i / n) * 2 * math.pi - math.pi / 2
        a1 = ((i + 0.94) / n) * 2 * math.pi - math.pi / 2
        p = []
        for r, (s, e) in ((r_out, (a0, a1)), (r_in, (a1, a0))):
            x0, y0 = cx + r * math.cos(s), cy + r * math.sin(s)
            x1, y1 = cx + r * math.cos(e), cy + r * math.sin(e)
            if r == r_out:
                p.append(f"M {x0:.2f} {y0:.2f} A {r} {r} 0 0 1 {x1:.2f} {y1:.2f}")
            else:
                p.append(f"L {x0:.2f} {y0:.2f} A {r} {r} 0 0 0 {x1:.2f} {y1:.2f} Z")
        parts.append(f'      <path class="wedge" data-accent="{token}" '
                     f'd="{" ".join(p)}"></path>')
    return "\n".join(parts)


def frag_specimen_tabs() -> str:
    out = []
    for i, (lang, label, filename) in enumerate(SPECIMENS):
        sel = "true" if i == 0 else "false"
        out.append(
            f'        <button class="stab" type="button" role="tab" '
            f'aria-selected="{sel}" aria-controls="spec-{lang}" '
            f'id="stab-{lang}" data-spec="{lang}">'
            f'<span class="stab-label">{html.escape(label)}</span>'
            f'<span class="stab-file">{html.escape(filename)}</span></button>'
        )
    return "\n".join(out)


def frag_specimen_panels(sources: dict[str, str]) -> str:
    out = []
    for i, (lang, label, filename) in enumerate(SPECIMENS):
        hidden = "" if i == 0 else " hidden"
        code = render_code(lang, sources[filename])
        out.append(
            f'''      <div class="spanel" id="spec-{lang}" role="tabpanel"
           aria-labelledby="stab-{lang}"{hidden}>
        <div class="scroll-x">
<pre class="code"><code>{code}</code></pre>
        </div>
      </div>'''
        )
    return "\n".join(out)


def frag_hero_code(sources: dict[str, str]) -> str:
    lang, _, filename = SPECIMENS[0]
    src = sources[filename]
    # The hero shows a tight excerpt: enough to carry most of the hues, short
    # enough to sit in the window without being clipped mid-glyph.
    lines = src.split("\n")
    excerpt = "\n".join(lines[0:21])
    return render_code(lang, excerpt)


def frag_legend(palette: dict) -> str:
    """SPEC's hue-assignment table, rebuilt live from kier.json.

    Grouped by palette token rather than by role, so a reassignment in the
    palette shows up here as a regrouping instead of a stale caption."""
    first = palette["flavours"][list(palette["flavours"])[0]]
    groups: dict[str, list[str]] = {}
    for role, spec in first["syntax"].items():
        groups.setdefault(spec["token"], []).append(role)

    prefix = {t: "a" for t in palette["accentOrder"]}
    prefix.update({t: "n" for t in palette["neutralOrder"]})
    order = [t for t in palette["accentOrder"] + palette["neutralOrder"] if t in groups]
    order += [t for t in groups if t not in order]

    out = []
    for token in order:
        roles = groups[token]
        chips = " ".join(
            f'<code class="hue-role">{html.escape(r)}</code>' for r in roles)
        var = f'--{prefix.get(token, "a")}-{token}'
        out.append(
            '        <li class="hue-row">\n'
            f'          <span class="hue-chip" style="background: var({var})" aria-hidden="true"></span>\n'
            f'          <code class="hue-token">{html.escape(token)}</code>\n'
            f'          <span class="hue-count">{len(roles)}</span>\n'
            f'          <span class="hue-roles">{chips}</span>\n'
            '        </li>'
        )
    return "\n".join(out)

def frag_ports() -> str:
    out = []
    for group, tagline, ports in PORT_GROUPS:
        cards = []
        for slug, name, desc in ports:
            cards.append(
                f'''          <a class="port" href="https://github.com/kier/{slug}">
            <span class="port-name">{html.escape(name)}</span>
            <span class="port-desc">{html.escape(desc)}</span>
            <span class="port-slug">kier/{slug}</span>
          </a>'''
            )
        out.append(
            f'''      <div class="port-group">
        <div class="port-group-head">
          <h3 class="port-group-name">{html.escape(group)}</h3>
          <p class="port-group-tag">{html.escape(tagline)}</p>
          <span class="port-count">{len(ports)}</span>
        </div>
        <div class="port-grid">
{chr(10).join(cards)}
        </div>
      </div>'''
        )
    return "\n".join(out)


def frag_ecosystems(mappings: dict) -> str:
    out = []
    for eco, spec in mappings["ecosystems"].items():
        roles = len(spec["map"])
        scopes = sum(len(v) if isinstance(v, list) else 1 for v in spec["map"].values())
        uses = ", ".join(spec["uses"])
        out.append(
            f'          <tr><th scope="row"><code>{html.escape(eco)}</code></th>'
            f'<td class="num">{roles}</td><td class="num">{scopes}</td>'
            f'<td class="uses">{html.escape(uses)}</td></tr>'
        )
    return "\n".join(out)


def frag_stats(palette: dict, mappings: dict) -> dict[str, str]:
    flavours = palette["flavours"]
    floors = []
    text_ratios = []
    for fl in flavours.values():
        base = fl["neutrals"]["base"]
        floors.append(min(contrast(h, base) for h in fl["accents"].values()))
        text_ratios.append(contrast(fl["neutrals"]["text"], base))
    d_min, d_flavour, d_a, d_b = closest_role_pair(palette)
    warm_n, warm_lo, warm_hi = warm_span(palette)
    total_roles = sum(len(s["map"]) for s in mappings["ecosystems"].values())
    total_scopes = sum(
        len(v) if isinstance(v, list) else 1
        for s in mappings["ecosystems"].values() for v in s["map"].values()
    )
    return {
        "FLAVOUR_COUNT": str(len(flavours)),
        "NEUTRAL_COUNT": str(len(palette["neutralOrder"])),
        "ACCENT_COUNT": str(len(palette["accentOrder"])),
        "ROLE_COUNT": str(len(palette["syntaxRoles"])),
        "ALIAS_COUNT": str(len(palette["aliases"])),
        "ECOSYSTEM_COUNT": str(len(mappings["ecosystems"])),
        "BINDING_COUNT": str(total_roles),
        "SCOPE_COUNT": str(total_scopes),
        "PORT_COUNT": str(sum(len(p) for _, _, p in PORT_GROUPS)),
        "MIN_CONTRAST": f"{min(floors):.1f}",
        "MAX_TEXT_CONTRAST": f"{max(text_ratios):.1f}",
        "MIN_TEXT_CONTRAST": f"{min(text_ratios):.1f}",
        "PALETTE_VERSION": palette["version"],
        "MIN_DE": f"{d_min:.3f}",
        "MIN_DE_A": d_a,
        "MIN_DE_B": d_b,
        "MIN_DE_FLAVOUR": d_flavour,
        "WARM_COUNT": str(warm_n),
        "WARM_LO": str(warm_lo),
        "WARM_HI": str(warm_hi),
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    palette = json.loads(PALETTE_PATH.read_text(encoding="utf-8"))
    mappings = json.loads(MAPPINGS_PATH.read_text(encoding="utf-8"))

    # Sanity gate: the site must never publish an accent below the floor.
    for fid, fl in palette["flavours"].items():
        base = fl["neutrals"]["base"]
        for token, hexv in fl["accents"].items():
            ratio = contrast(hexv, base)
            if ratio + 0.05 < CONTRAST_FLOOR:
                raise SystemExit(
                    f"refusing to build: {fid}.{token} is {ratio:.2f}:1 on base")

    sources = {
        p.name: resolve_placeholders(p.read_text(encoding="utf-8"), palette)
        for p in sorted((SRC / "specimens").iterdir()) if p.is_file()
    }

    (HERE / "kier.css").write_text(build_css(palette), encoding="utf-8")
    (HERE / "palette.js").write_text(build_palette_js(palette, mappings), encoding="utf-8")
    shutil.copyfile(SRC / "app.js", HERE / "app.js")
    shutil.copyfile(SRC / "site.css", HERE / "site.css")

    template = (SRC / "template.html").read_text(encoding="utf-8")
    fields = frag_stats(palette, mappings)
    fields.update({
        "FLAVOUR_PILLS": frag_flavour_pills(palette),
        "FLAVOUR_CARDS": frag_flavour_cards(palette),
        "DISC_WEDGES": frag_disc(palette),
        "HERO_CODE": frag_hero_code(sources),
        "HERO_FILE": SPECIMENS[0][2],
        "SPECIMEN_TABS": frag_specimen_tabs(),
        "SPECIMEN_PANELS": frag_specimen_panels(sources),
        "LEGEND": frag_legend(palette),
        "PORTS": frag_ports(),
        "ECOSYSTEMS": frag_ecosystems(mappings),
    })

    missing = set(re.findall(r"\{\{([A-Z_]+)\}\}", template)) - set(fields)
    if missing:
        raise SystemExit(f"template has unfilled placeholders: {sorted(missing)}")

    page = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: fields[m.group(1)], template)

    # Hard rule: every hex that reaches the HTML must be one the palette owns.
    known = palette_colours(palette)
    stray = sorted({h.upper() for h in re.findall(r"#[0-9a-fA-F]{6}\b", page)} - known)
    if stray:
        raise SystemExit(f"hex not owned by kier.json leaked into index.html: {stray}")

    (HERE / "index.html").write_text(page, encoding="utf-8")

    print(f"kier.css     {(HERE / 'kier.css').stat().st_size:>7,} bytes")
    print(f"palette.js   {(HERE / 'palette.js').stat().st_size:>7,} bytes")
    print(f"site.css     {(HERE / 'site.css').stat().st_size:>7,} bytes")
    print(f"app.js       {(HERE / 'app.js').stat().st_size:>7,} bytes")
    print(f"index.html   {(HERE / 'index.html').stat().st_size:>7,} bytes")
    print(f"built {len(palette['flavours'])} flavours, "
          f"{len(palette['syntaxRoles'])} roles, "
          f"{sum(len(p) for _, _, p in PORT_GROUPS)} ports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
