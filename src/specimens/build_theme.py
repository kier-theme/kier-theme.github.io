#!/usr/bin/env python3
"""Kier — emit one theme file per flavour from the palette and the mappings.

A port never hardcodes a hex. It reads a role out of ``mappings.json``,
resolves it in ``kier.json``, and writes it back out in its own dialect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PALETTE = Path("core/palette/kier.json")
MAPPINGS = Path("core/palette/mappings.json")
CONTRAST_FLOOR = 5.0


@dataclass(frozen=True, slots=True)
class Role:
    name: str
    color: str
    token: str
    style: str | None = None
    scopes: tuple[str, ...] = field(default=())

    @property
    def is_alias(self) -> bool:
        return self.name.partition(".")[0] != self.name


class ThemeWriter:
    """Base class: subclass and override ``render`` for a new ecosystem."""

    ecosystem = "textmate"
    extension = ".json"

    def __init__(self, palette: dict, mappings: dict) -> None:
        self.palette = palette
        self.scopes = mappings["ecosystems"][self.ecosystem]["map"]

    def roles(self, flavour: str) -> list[Role]:
        syntax = self.palette["flavours"][flavour]["syntax"]
        out = []
        for name, spec in syntax.items():
            scopes = self.scopes.get(name, [])
            if isinstance(scopes, str):
                scopes = [scopes]
            out.append(
                Role(
                    name=name,
                    color=spec["color"],
                    token=spec["token"],
                    style=spec.get("style"),
                    scopes=tuple(scopes),
                )
            )
        return out

    def render(self, flavour: str) -> str:
        raise NotImplementedError(f"{type(self).__name__} must render {flavour!r}")

    def write_all(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for flavour in self.palette["flavours"]:
            target = out_dir / f"kier-{flavour}{self.extension}"
            target.write_text(self.render(flavour), encoding="utf-8")
            print(f"  wrote {target}  ({target.stat().st_size:,} bytes)")


def relative_luminance(hex_colour: str) -> float:
    raw = hex_colour.lstrip("#")
    channels = (int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((relative_luminance(fg), relative_luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    palette = json.loads(PALETTE.read_text(encoding="utf-8"))
    mappings = json.loads(MAPPINGS.read_text(encoding="utf-8"))

    for flavour_id, flavour in palette["flavours"].items():
        base = flavour["neutrals"]["base"]
        dim = {
            token: round(ratio, 2)
            for token, hex_colour in flavour["accents"].items()
            if (ratio := contrast(hex_colour, base)) < CONTRAST_FLOOR
        }
        if dim:
            raise SystemExit(f"{flavour['name']}: accents below floor -> {dim}")
        print(f"{flavour['name']:<10} {len(flavour['syntax'])} roles, base {base}")

    ThemeWriter(palette, mappings).write_all(Path("dist"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
