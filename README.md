# Kier — the website

The canonical page for [Kier](https://github.com/kier/core), a warm retro dark
theme in five flavours named for Lady Miss Kier of Deee-Lite.

Static HTML, CSS and one vanilla JS file. No framework, no bundler, no CDN, and
nothing fetched at runtime except Google Fonts. It opens straight from
`file://` — double-click `index.html`.

---

## How it works

Every colour on this page comes from `../core/palette/kier.json`. Nothing is
typed in by hand, in the HTML, in the CSS or in the JS.

`generate.py` reads the palette and emits the site ahead of time. It is a
**build-time generator** rather than a runtime fetch, for one reason: a page
opened from `file://` cannot `fetch()` a sibling JSON file — Chrome treats it as
a cross-origin request and blocks it. Baking the data into a `.js` file keeps
the page working with no server at all, which is the whole point of a reference
page people will save locally.

```
src/                       hand-written inputs
  template.html            page structure + prose, with {{PLACEHOLDER}} slots
  site.css                 layout and type; every colour is a var(), no hex
  app.js                   flavour switching, click-to-copy, tabs
  specimens/               real source files shown in the syntax section
    flavour.rs
    palette.ts
    build_theme.py
    kier.toml

generate.py                reads kier.json + mappings.json, writes:
  index.html                 template with every slot filled
  kier.css                   custom properties, one block per flavour, plus
                             a .t-<role> rule for each of the syntax roles
  palette.js                 window.KIER — colours, contrast ratios, metadata
  site.css                   copied verbatim from src/
  app.js                     copied verbatim from src/

verify.py                  checks the emitted files without a browser
```

### What is generated, precisely

| output | contents |
|---|---|
| `kier.css` | `:root[data-flavour="<id>"]` blocks holding `--n-*` neutrals, `--a-*` accents, `--ui-*` roles and `--sy-*` syntax roles; one `.t-<role>` colour rule per syntax role; one switcher-dot rule and one hero-wedge rule per flavour |
| `palette.js` | `window.KIER` — every flavour's hexes with WCAG contrast against that flavour's own `base` precomputed, plus ANSI 16, alias list and ecosystem coverage |
| `index.html` | the template with the flavour pills, flavour cards, hero disc, tokenized code specimens, the hue-assignment table, the ports grid, the ecosystem table and every derived statistic filled in |

Switching flavour is a single attribute write — `document.documentElement.dataset.flavour`
— so the whole page including the code specimen repaints in one style
recalculation. `app.js` then repaints the palette grids, which are the only
parts that need literal hex text in the DOM.

### The syntax specimens

The files under `src/specimens/` are real source, not snippets written to look
pretty. `generate.py` contains a small regex tokenizer (`RULES`, `KEYWORDS`,
`tokenize`) that scans them into the *same role names kier.json defines* —
`keyword.import`, `variable.parameter`, `string.escape`, `punctuation.bracket`
and so on — and wraps each token in `<span class="t-<role>">`. The colour then
comes from `--sy-<role>` in `kier.css`, which came from the palette.

It is a scanner, not a parser: good enough to be honest about which role a token
plays, and deliberately not a language server.

Specimens may not type a hex either. `kier.toml` uses placeholders —
`@n:base@`, `@a:tangerine@`, `@u:cursor@`, `@x:bright_red@` — which resolve
against the default flavour at build time. That is why the config sample shows
genuinely generated output.

---

## Regenerating

Any time `core/palette/kier.json` or `core/palette/mappings.json` changes:

```sh
python3 web/generate.py
python3 web/verify.py
```

Run it from anywhere; both scripts resolve their own paths. `generate.py`
refuses to write if an accent has fallen below the 5.0:1 floor, or if a hex that
kier.json does not own has leaked into the HTML.

Numbers quoted in the prose — role count, alias count, binding and scope totals,
the contrast floor, the closest non-aliased pair in OKLab and the warm-hue arc —
are all computed from the palette at build time, so they cannot go stale.
`closest_role_pair()` mirrors the check in `core/tools/validate.py` so the page
quotes the same figure the build gate enforces.

### Changing content

- Prose, sections, nav → `src/template.html`
- Layout, type, spacing → `src/site.css` (a hex literal here is a bug)
- Behaviour → `src/app.js`
- Code samples → `src/specimens/`, then re-run `generate.py`
- Port list and groupings → `PORT_GROUPS` in `generate.py`

Do not edit `index.html`, `kier.css`, `palette.js`, `site.css` or `app.js` in
this directory. They are overwritten.

---

## Verifying

`verify.py` runs without a browser, a bundler or a network:

- `index.html` parses with `html.parser`, every tag balanced, every `id` unique
- every in-page anchor resolves to an element that exists
- every local asset referenced is on disk
- the only external hosts are `github.com` and the two Google Fonts domains
- all 19 ports appear in the ports grid
- `window.KIER` is valid JSON and matches `kier.json` colour for colour
- no hex anywhere in the output that `kier.json` does not own
- CSS braces balance and every `var()` used is declared
- every syntax role class the specimens emit has a rule in `kier.css`

For a JS check, `node --check app.js palette.js` is enough — there is no module
system to resolve.

---

## Deploying to GitHub Pages

The site is the repository root: `index.html` and its four assets sit beside
this README, with no build step. Two ways to publish it.

### Deploy from a branch (simplest)

1. Push this directory to a repo, e.g. `kier/kier.github.io` or `kier/web`.
2. **Settings → Pages → Build and deployment**.
3. Source: **Deploy from a branch**. Branch: `main`, folder: `/ (root)`.
4. Save. The site appears at `https://kier.github.io/` (for the
   `<org>.github.io` repo) or `https://kier.github.io/web/` otherwise.

Nothing else is required — Pages serves the committed files as-is. There is no
Jekyll content here, but if Pages ever tries to process it, add an empty
`.nojekyll` file at the root.

### Deploy with Actions (regenerates on every push)

Use this if the palette lives in the same repository and you want the site
rebuilt whenever it changes. Put this at `.github/workflows/pages.yml`:

```yaml
name: Pages
on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Regenerate from the palette
        run: python3 web/generate.py
      - name: Verify
        run: python3 web/verify.py
      - name: Fail if the committed output is stale
        run: git diff --exit-code -- web/
      - uses: actions/upload-pages-artifact@v3
        with:
          path: web
      - id: deploy
        uses: actions/deploy-pages@v4
```

Then set **Settings → Pages → Source** to **GitHub Actions**.

The `git diff --exit-code` step is the useful part: it fails the build if
someone changed the palette without re-running `generate.py`, which keeps the
committed HTML honest.

### Custom domain

Add a `CNAME` file at the root containing the bare hostname, e.g.
`kier.style`, then point a `CNAME` DNS record at `kier.github.io`. For an apex
domain use `A` records to GitHub's Pages IPs instead.

---

## Notes and constraints

- **Always dark.** Kier is a dark theme; a light flavour is deliberately not
  shipped yet. The page commits to one look and paints every background and
  colour explicitly, so it never borrows a host theme. `color-scheme: dark` is
  declared for form controls and scrollbars.
- **Fonts.** Fraunces (display), Archivo (body) and IBM Plex Mono (code), all
  from Google Fonts, each with a real fallback stack. Google Fonts is the only
  permitted network dependency; if it is blocked the page still reads correctly
  in the fallbacks.
- **Wide content scrolls in its own box.** Code specimens, the ecosystem table
  and the flavour switcher each have their own `overflow-x`; the body never
  scrolls sideways.
- **Reduced motion.** The rotating hero disc, the caret blink and every hover
  transform are switched off under `prefers-reduced-motion: reduce`.
- **Storage.** The chosen flavour is remembered in `localStorage` under
  `kier.flavour`, wrapped in try/catch — private windows and blocked site data
  fall back to the first flavour.
- **Clipboard.** Swatch copy uses `navigator.clipboard` where available and
  falls back to a hidden textarea plus `execCommand`, which is what makes
  click-to-copy work from `file://`.

## Licence

MIT, same as the rest of Kier. Named for Lady Miss Kier of Deee-Lite; not
affiliated with, or endorsed by, anyone who made those records.
