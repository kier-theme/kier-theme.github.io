/**
 * Kier — load a flavour and hand back CSS custom properties.
 * The palette is the single source of truth; nothing here invents a colour.
 */
import { readFile } from "node:fs/promises";

export type FlavourId = "groove" | "clique" | "dewdrop" | "infinity" | "runaway";

export interface SyntaxRole {
  readonly color: string;
  readonly token: string;
  readonly style?: "italic" | "bold" | "underline" | "strikethrough";
}

interface Flavour {
  id: FlavourId;
  name: string;
  neutrals: Record<string, string>;
  accents: Record<string, string>;
  syntax: Record<string, SyntaxRole>;
}

const CONTRAST_FLOOR = 5.0 as const;

export async function loadPalette(path = "core/palette/kier.json"): Promise<Palette> {
  const raw = await readFile(path, "utf8");
  const parsed = JSON.parse(raw) as Palette;
  if (!parsed.flavours) throw new TypeError(`no flavours in ${path}`);
  return parsed;
}

export function toCustomProperties(flavour: Flavour): string {
  const lines: string[] = [`:root[data-flavour="${flavour.id}"] {`];

  for (const [token, hex] of Object.entries(flavour.neutrals)) {
    lines.push(`  --n-${token}: ${hex};`);
  }
  for (const [token, hex] of Object.entries(flavour.accents)) {
    lines.push(`  --a-${token}: ${hex};`);
  }
  for (const [role, spec] of Object.entries(flavour.syntax)) {
    const safe = role.replace(/\./g, "-");
    lines.push(`  --sy-${safe}: ${spec.color};`);
    if (spec.style) lines.push(`  --sy-${safe}-style: ${spec.style};`);
  }

  return lines.concat("}").join("\n");
}

/** Fails loudly rather than shipping an unreadable accent. */
export function audit(flavour: Flavour): void {
  const base = flavour.neutrals.base;
  const dim = Object.entries(flavour.accents)
    .map(([token, hex]) => [token, contrast(hex, base)] as const)
    .filter(([, ratio]) => ratio < CONTRAST_FLOOR);

  if (dim.length > 0) {
    const detail = dim.map(([t, r]) => `${t} at ${r.toFixed(2)}:1`).join(", ");
    throw new RangeError(`${flavour.name}: ${detail}`);
  }
}
