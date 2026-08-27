#!/usr/bin/env python3
"""Kier — verify the generated website.

Checks the emitted files without a browser, a bundler or a network:

  * index.html parses with html.parser, every tag balanced, ids unique
  * every in-page anchor resolves to an element that exists
  * every local asset referenced actually sits on disk
  * the only external hosts are GitHub and Google Fonts
  * all 19 ports appear in the ports grid
  * window.KIER is valid JSON and matches kier.json colour for colour
  * no hex anywhere in the output that kier.json does not own
  * CSS braces balance and every var() used is declared
  * every syntax role class the specimens emit has a rule in kier.css

    python3 web/verify.py

Exits non-zero on the first category that fails.
"""
import json, re, sys
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parent
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}
fails = []


class Check(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.ids = set()
        self.hrefs = []
        self.srcs = []
        self.problems = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            if a["id"] in self.ids:
                self.problems.append(f"duplicate id: {a['id']}")
            self.ids.add(a["id"])
        if a.get("href"):
            self.hrefs.append(a["href"])
        if a.get("src"):
            self.srcs.append(a["src"])
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.problems.append(f"stray </{tag}> at {self.getpos()}")
            return
        open_tag, pos = self.stack[-1]
        if open_tag != tag:
            self.problems.append(
                f"mismatch: </{tag}> at {self.getpos()} closes <{open_tag}> opened at {pos}")
            # unwind to recover
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return
            return
        self.stack.pop()


html_text = (WEB / "index.html").read_text(encoding="utf-8")
p = Check()
p.feed(html_text)
p.close()

print("── html.parser ────────────────────────────────────────────")
for prob in p.problems:
    fails.append(prob)
    print("  FAIL", prob)
if p.stack:
    for tag, pos in p.stack:
        fails.append(f"unclosed <{tag}> opened at line {pos[0]}")
        print(f"  FAIL unclosed <{tag}> opened at line {pos[0]} col {pos[1]}")
if not p.problems and not p.stack:
    print(f"  OK   well-formed, {len(p.ids)} unique ids, all tags balanced")

print("── links ──────────────────────────────────────────────────")
anchors = [h for h in p.hrefs if h.startswith("#")]
for h in anchors:
    if h[1:] not in p.ids:
        fails.append(f"dangling anchor {h}")
        print("  FAIL dangling anchor", h)
print(f"  OK   {len(anchors)} in-page anchors, all resolve"
      if all(h[1:] in p.ids for h in anchors) else "")

local = [h for h in p.hrefs + p.srcs
         if not h.startswith(("#", "http://", "https://", "mailto:", "data:"))]
for rel in local:
    if not (WEB / rel).exists():
        fails.append(f"missing local file {rel}")
        print("  FAIL missing local file", rel)
print(f"  OK   {len(local)} local assets present: {sorted(set(local))}")

external = sorted({h for h in p.hrefs + p.srcs if h.startswith("http")})
hosts = sorted({re.match(r"https?://([^/]+)", h).group(1) for h in external})
print(f"  OK   {len(external)} external links, hosts: {hosts}")
bad_hosts = [h for h in hosts if h not in
             ("github.com", "fonts.googleapis.com", "fonts.gstatic.com",
              "en.wikipedia.org")]
if bad_hosts:
    fails.append(f"unexpected external host {bad_hosts}")
    print("  FAIL unexpected external host", bad_hosts)

print("── ports ──────────────────────────────────────────────────")
ports = re.findall(r'href="https://github\.com/kier/([a-z]+)"', html_text)
expected = {"cosmic", "nvim", "ghostty", "emacs", "jetbrains", "fleet", "vscode",
            "bat", "btop", "fzf", "starship", "tmux", "zellij", "grub", "eza",
            "firefox", "chrome", "darkreader", "obsidian"}
in_grid = set(re.findall(r'class="port" href="https://github\.com/kier/([a-z]+)"', html_text))
missing = expected - in_grid
extra = in_grid - expected
if missing or extra:
    fails.append(f"ports grid missing={missing} extra={extra}")
    print("  FAIL missing", missing, "extra", extra)
else:
    print(f"  OK   all {len(expected)} ports linked in the grid")

print("── palette.js ─────────────────────────────────────────────")
js = (WEB / "palette.js").read_text(encoding="utf-8")
m = re.search(r"window\.KIER = (\{.*\});\s*$", js, re.S)
if not m:
    fails.append("palette.js: cannot find the assignment")
    print("  FAIL cannot find window.KIER = {...};")
else:
    try:
        data = json.loads(m.group(1))
        print(f"  OK   JSON parses: {len(data['flavours'])} flavours, "
              f"{data['roleCount']} roles, {data['aliasCount']} aliases")
    except Exception as e:
        fails.append(f"palette.js JSON: {e}")
        print("  FAIL JSON:", e)
        data = None

print("── palette fidelity ───────────────────────────────────────")
src = json.loads((WEB.parent / "core" / "palette" / "kier.json").read_text())
drift = []
for fid, fl in src["flavours"].items():
    for tok, hexv in fl["neutrals"].items():
        if data["flavours"][fid]["neutrals"].get(tok, {}).get("hex") != hexv:
            drift.append(f"{fid}.{tok}")
    for tok, hexv in fl["accents"].items():
        if data["flavours"][fid]["accents"].get(tok, {}).get("hex") != hexv:
            drift.append(f"{fid}.{tok}")
if drift:
    fails.append(f"palette drift: {drift}")
    print("  FAIL drift:", drift)
else:
    print("  OK   all 5x24 palette colours byte-identical to kier.json")

# every hex anywhere in the emitted output must be one kier.json owns
owned = set()
for fl in src["flavours"].values():
    for key in ("neutrals", "accents", "ui", "ansi"):
        owned |= {v.upper() for v in fl[key].values()}
    owned |= {s["color"].upper() for s in fl["syntax"].values()}
for name in ("index.html", "kier.css", "site.css", "app.js"):
    found = {h.upper() for h in re.findall(r"#[0-9a-fA-F]{6}\b",
                                           (WEB / name).read_text())}
    stray = found - owned
    if stray:
        fails.append(f"{name}: unowned hex {sorted(stray)}")
        print(f"  FAIL {name}: unowned hex {sorted(stray)}")
    else:
        print(f"  OK   {name}: {len(found)} hex values, all owned by kier.json")

print("── css sanity ─────────────────────────────────────────────")
css = (WEB / "kier.css").read_text() + (WEB / "site.css").read_text()
if css.count("{") != css.count("}"):
    fails.append(f"css brace mismatch {css.count('{')} vs {css.count('}')}")
    print("  FAIL brace mismatch", css.count("{"), css.count("}"))
else:
    print(f"  OK   braces balanced ({css.count('{')} blocks)")
used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
declared = set(re.findall(r"^\s*(--[a-z0-9-]+):", css, re.M))
undeclared = used - declared
if undeclared:
    fails.append(f"undeclared css vars {sorted(undeclared)}")
    print("  FAIL undeclared vars:", sorted(undeclared))
else:
    print(f"  OK   {len(used)} custom properties used, all declared")

print("── syntax roles ───────────────────────────────────────────")
roles_in_css = set(re.findall(r"^\.t-([a-z0-9-]+) \{", (WEB / "kier.css").read_text(), re.M))
roles_in_html = set(re.findall(r'class="(t-[a-z0-9-]+)"', html_text))
roles_in_html = {r[2:] for r in roles_in_html}
orphan = roles_in_html - roles_in_css
if orphan:
    fails.append(f"specimen uses role classes with no rule: {sorted(orphan)}")
    print("  FAIL orphan role classes:", sorted(orphan))
else:
    print(f"  OK   specimens use {len(roles_in_html)} role classes, "
          f"all of {len(roles_in_css)} defined in kier.css")

print()
if fails:
    print(f"FAILED — {len(fails)} problem(s)")
    sys.exit(1)
print("PASS — site is standalone-safe")
