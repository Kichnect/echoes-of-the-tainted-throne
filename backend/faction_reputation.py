"""
Faction reputation system for Echoes of the Tainted Throne.

Factions:
  warden_order       — the kingdom's anti-corruption wardens
  free_lupines       — corrupted lupines who have chosen wildness
  kitsune_wanderers  — neutral kitsune faction
  kasyrra_cult       — Kasyrra's devoted followers
  settlements        — general civilian settlements
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import SaveGame, FactionReputation
    from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Reputation effects per combat encounter outcome
# ---------------------------------------------------------------------------

# (encounter_id, outcome) → {faction: delta}
COMBAT_REP_EFFECTS: dict[tuple[str, str], dict[str, int]] = {
    ("lupine_pack",   "win"):  {"free_lupines": -5, "warden_order": +5},
    ("lupine_pack",   "loss"): {"free_lupines": +5},
    ("imp_swarm",     "win"):  {"warden_order": +3},
    ("imp_swarm",     "loss"): {},
    ("cult_devotee",  "win"):  {"kasyrra_cult": -8, "warden_order": +5},
    ("cult_devotee",  "loss"): {"kasyrra_cult": +10},
}

FACTION_LABELS: dict[str, str] = {
    "warden_order":      "Warden Order",
    "free_lupines":      "Free Lupines",
    "kitsune_wanderers": "Kitsune Wanderers",
    "kasyrra_cult":      "Kasyrra's Cult",
    "settlements":       "Settlements",
}

FACTION_DESCRIPTORS: list[tuple[int, str]] = [
    # (threshold, label)
    (80,  "Revered"),
    (65,  "Trusted"),
    (50,  "Neutral"),
    (35,  "Wary"),
    (20,  "Hostile"),
    (0,   "Refused"),
]


def get_descriptor(score: int) -> str:
    for threshold, label in FACTION_DESCRIPTORS:
        if score >= threshold:
            return label
    return "Refused"


def update_reputation(
    save: "SaveGame",
    encounter_id: str,
    outcome: str,
    db: "Session",
) -> None:
    """
    Apply reputation changes for a combat encounter outcome.
    Does NOT commit — caller commits.
    """
    rep = save.reputation
    if rep is None:
        return

    effects = COMBAT_REP_EFFECTS.get((encounter_id, outcome), {})
    for faction, delta in effects.items():
        current = getattr(rep, faction, 50)
        setattr(rep, faction, max(0, min(100, current + delta)))


def reputation_dict(rep: "FactionReputation") -> dict:
    """Serialize reputation for API responses."""
    if rep is None:
        return {}
    return {
        f: {
            "score":      getattr(rep, f, 50),
            "label":      FACTION_LABELS.get(f, f),
            "descriptor": get_descriptor(getattr(rep, f, 50)),
        }
        for f in ["warden_order", "free_lupines", "kitsune_wanderers", "kasyrra_cult", "settlements"]
    }
