/* Kier — site behaviour.
 *
 * No colour is defined here. Everything visual comes from kier.css (generated)
 * or from window.KIER (generated, in palette.js). This file only decides which
 * flavour is on and paints the palette grids from that data.
 *
 * Vanilla ES2018. No framework, no bundler, no network at runtime.
 */
(function () {
  "use strict";

  var KIER = window.KIER;
  if (!KIER || !KIER.flavours) {
    console.warn("Kier: palette.js did not load; the page will still render.");
    return;
  }

  var root = document.documentElement;
  var ORDER = Object.keys(KIER.flavours).sort(function (a, b) {
    return KIER.flavours[a].order - KIER.flavours[b].order;
  });
  var STORAGE_KEY = "kier.flavour";
  var current = null;

  /* ── little helpers ─────────────────────────────────────────────────── */

  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) {
    return Array.prototype.slice.call((ctx || document).querySelectorAll(sel));
  }

  function stored() {
    try { return window.localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }
  function store(id) {
    try { window.localStorage.setItem(STORAGE_KEY, id); } catch (e) { /* private mode */ }
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  /* ── toast ──────────────────────────────────────────────────────────── */

  var toastNode = $("#toast");
  var toastTimer = null;

  function toast(message) {
    if (!toastNode) return;
    toastNode.textContent = message;
    toastNode.classList.add("on");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toastNode.classList.remove("on");
    }, 1600);
  }

  /* ── clipboard, with a file:// friendly fallback ────────────────────── */

  function copy(text, done) {
    function fallback() {
      var ta = el("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      done(ok);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
    } else {
      fallback();
    }
  }

  /* ── swatches ───────────────────────────────────────────────────────── */

  function swatch(token, hex, ratio, showRatio) {
    var btn = el("button", "sw");
    btn.type = "button";
    btn.setAttribute("data-token", token);
    btn.setAttribute(
      "aria-label",
      token + ", " + hex + (showRatio ? ", contrast " + ratio.toFixed(2) + " to 1 on base" : "")
    );

    var chip = el("span", "sw-chip");
    chip.style.background = hex;
    chip.setAttribute("aria-hidden", "true");

    var meta = el("span", "sw-meta");
    meta.appendChild(el("span", "sw-name", token));
    meta.appendChild(el("span", "sw-hex", hex));
    if (showRatio) {
      var cr = el("span", "sw-cr", ratio.toFixed(2) + ":1 on base");
      if (ratio >= 5) cr.classList.add("pass");
      meta.appendChild(cr);
    }

    btn.appendChild(chip);
    btn.appendChild(meta);

    btn.addEventListener("click", function () {
      copy(hex, function (ok) {
        toast(ok ? hex + " copied" : "copy blocked — " + hex);
        var name = $(".sw-name", btn);
        if (!ok || !name) return;
        var was = name.textContent;
        name.textContent = "copied";
        name.classList.add("sw-copied");
        window.setTimeout(function () {
          name.textContent = was;
          name.classList.remove("sw-copied");
        }, 900);
      });
    });
    return btn;
  }

  function paintSwatches(flavour) {
    var neutralGrid = $("#neutral-grid");
    var accentGrid = $("#accent-grid");
    var ansiGrid = $("#ansi-grid");

    if (neutralGrid) {
      neutralGrid.textContent = "";
      KIER.neutralOrder.forEach(function (token) {
        var n = flavour.neutrals[token];
        neutralGrid.appendChild(swatch(token, n.hex, n.contrast, false));
      });
    }

    if (accentGrid) {
      accentGrid.textContent = "";
      KIER.accentOrder.forEach(function (token) {
        var a = flavour.accents[token];
        accentGrid.appendChild(swatch(token, a.hex, a.contrast, true));
      });
    }

    if (ansiGrid) {
      ansiGrid.textContent = "";
      Object.keys(flavour.ansi).forEach(function (token) {
        ansiGrid.appendChild(swatch(token, flavour.ansi[token], 0, false));
      });
    }
  }

  /* ── flavour switching ──────────────────────────────────────────────── */

  var BINDINGS = {
    name: function (f) { return f.name; },
    reference: function (f) { return f.reference; },
    blurb: function (f) { return f.blurb; },
    contrastLine: function (f) {
      return "text " + f.textContrast.toFixed(1) + ":1 · " + f.minAccent.token +
        " " + f.minAccent.ratio.toFixed(2) + ":1";
    }
  };

  function setFlavour(id, options) {
    if (id === current) return;
    if (!KIER.flavours[id]) id = ORDER[0];
    var flavour = KIER.flavours[id];
    current = id;

    root.setAttribute("data-flavour", id);

    $$(".pill").forEach(function (p) {
      p.setAttribute("aria-pressed", String(p.getAttribute("data-flavour") === id));
    });
    $$(".fcard").forEach(function (c) {
      if (c.getAttribute("data-flavour") === id) c.setAttribute("aria-current", "true");
      else c.removeAttribute("aria-current");
    });

    Object.keys(BINDINGS).forEach(function (key) {
      $$('[data-bind="' + key + '"]').forEach(function (node) {
        node.textContent = BINDINGS[key](flavour);
      });
    });

    paintSwatches(flavour);
    store(id);

    if (options && options.announce) toast(flavour.name + " — " + flavour.reference);
  }

  $$(".pill").forEach(function (pill) {
    pill.addEventListener("click", function () {
      setFlavour(pill.getAttribute("data-flavour"));
    });
  });

  $$(".fcard").forEach(function (card) {
    card.addEventListener("click", function () {
      setFlavour(card.getAttribute("data-flavour"), { announce: true });
    });
  });

  /* Arrow keys move along the switcher; 1..5 jump straight to a flavour. */
  var switcher = $(".switcher");
  if (switcher) {
    switcher.addEventListener("keydown", function (ev) {
      var delta = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
      if (!delta) return;
      ev.preventDefault();
      var i = ORDER.indexOf(current);
      var next = ORDER[(i + delta + ORDER.length) % ORDER.length];
      setFlavour(next);
      var btn = $('.pill[data-flavour="' + next + '"]');
      if (btn) btn.focus();
    });
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    var tag = (ev.target && ev.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || ev.target.isContentEditable) return;
    var n = parseInt(ev.key, 10);
    if (n >= 1 && n <= ORDER.length) setFlavour(ORDER[n - 1], { announce: true });
  });

  /* ── specimen tabs ──────────────────────────────────────────────────── */

  var tabs = $$(".stab");
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      var want = tab.getAttribute("data-spec");
      tabs.forEach(function (t) {
        t.setAttribute("aria-selected", String(t.getAttribute("data-spec") === want));
      });
      $$(".spanel").forEach(function (panel) {
        panel.hidden = panel.id !== "spec-" + want;
      });
    });
  });

  var stabs = $(".stabs");
  if (stabs) {
    stabs.addEventListener("keydown", function (ev) {
      var delta = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
      if (!delta) return;
      ev.preventDefault();
      var i = tabs.findIndex ? tabs.findIndex(function (t) {
        return t.getAttribute("aria-selected") === "true";
      }) : 0;
      var next = tabs[(i + delta + tabs.length) % tabs.length];
      if (next) { next.click(); next.focus(); }
    });
  }

  /* ── boot ───────────────────────────────────────────────────────────── */

  var initial = stored();
  setFlavour(KIER.flavours[initial] ? initial : ORDER[0]);
})();
