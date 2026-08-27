//! Resolve a Kier flavour from `kier.json` into a concrete theme.
use std::collections::BTreeMap;
use std::fmt;

/// Every accent clears 5.0:1 against its own `base`.
const CONTRAST_FLOOR: f64 = 5.0;

#[derive(Debug, Clone, PartialEq)]
pub enum Ground {
    Crust,
    Mantle,
    Base,
    Surface(u8),
}

pub struct Flavour<'a> {
    pub id: &'a str,
    pub name: &'a str,
    neutrals: BTreeMap<String, Rgb>,
    accents: BTreeMap<String, Rgb>,
}

impl<'a> Flavour<'a> {
    /// Look a role up, falling through declared aliases before giving up.
    pub fn role(&self, role: &str, aliases: &[(&str, &str)]) -> Option<&Rgb> {
        self.accents.get(role).or_else(|| {
            aliases
                .iter()
                .find(|(from, _)| *from == role)
                .and_then(|(_, to)| self.accents.get(*to))
        })
    }

    pub fn audit(&self) -> Result<(), AuditError> {
        let base = self.neutrals.get("base").ok_or(AuditError::MissingBase)?;
        for (token, colour) in &self.accents {
            let ratio = contrast(colour, base);
            if ratio < CONTRAST_FLOOR {
                return Err(AuditError::TooDim {
                    token: token.clone(),
                    ratio,
                });
            }
        }
        Ok(())
    }
}

fn contrast(fg: &Rgb, bg: &Rgb) -> f64 {
    let (a, b) = (fg.luminance(), bg.luminance());
    let (hi, lo) = if a > b { (a, b) } else { (b, a) };
    (hi + 0.05) / (lo + 0.05)
}

impl fmt::Display for Ground {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Ground::Surface(n) => write!(f, "surface{n}"),
            other => write!(f, "{}", format!("{other:?}").to_lowercase()),
        }
    }
}
