"""
Sin system for Echoes of the Tainted Throne.

The player's chosen sin flavors corruption mechanics, color path weighting,
and certain event multipliers throughout the game.
"""
from __future__ import annotations

# Sin definitions — mechanical effects as multipliers/modifiers
SIN_DEFINITIONS: dict[str, dict] = {
    "pride": {
        "label":       "Pride",
        "symbol":      "♦",
        "color":       "#d4af37",
        "corruption_gain_mod":   -0.20,   # -20% corruption gain
        "corruption_post_ponr":  +0.30,   # +30% gain after PONR
        "color_path_weights":    {"ivory": 2, "teal": 2},
        "description": "Resists corruption longer. When the fall comes, it comes hard.",
    },
    "lust": {
        "label":       "Lust",
        "symbol":      "♥",
        "color":       "#c45c8a",
        "arousal_gain_mod":      +0.50,   # +50% arousal gain
        "erotic_encounter_mod":  +0.25,
        "color_path_weights":    {"rose": 2, "amber": 2},
        "description": "Early encounters more intense. The arousal curve is steeper.",
    },
    "sloth": {
        "label":       "Sloth",
        "symbol":      "♠",
        "color":       "#7b68ee",
        "corruption_gain_mod":   +0.10,   # +10% corruption gain
        "companion_morale_mod":  -0.20,   # morale degrades 20% slower
        "color_path_weights":    {"violet": 3},
        "description": "Corruption spreads faster. Companions compensate.",
    },
    "wrath": {
        "label":       "Wrath",
        "symbol":      "♣",
        "color":       "#c0392b",
        "combat_win_xp_bonus":   10,
        "combat_loss_hp_mod":    3,       # +3 extra HP loss on loss
        "color_path_weights":    {"crimson": 3},
        "description": "Combat wins pay more. Losses cost more.",
    },
    "envy": {
        "label":       "Envy",
        "symbol":      "★",
        "color":       "#e8a83a",
        "attraction_arc_mod":    +0.25,   # +25% faster arc when triggered by companions
        "color_path_weights":    {"amber": 3},
        "description": "The attraction arc advances faster through companion observation.",
    },
    "greed": {
        "label":       "Greed",
        "symbol":      "$",
        "color":       "#95a5a6",
        "discovery_chance_mod":  +0.15,   # +15% discovery events
        "item_effect_mod":       +0.15,
        "color_path_weights":    {"grey": 3},
        "description": "Discoveries are more common. Found items are more potent.",
    },
    "gluttony": {
        "label":       "Gluttony",
        "symbol":      "●",
        "color":       "#d47a7a",
        "corruption_gain_mod":   +0.15,   # +15% corruption from sources
        "resistance_mod":        +0.15,   # resistance items +15% effective
        "color_path_weights":    {"rose": 1, "violet": 2},
        "description": "Everything amplifies. Corruption and resistance both.",
    },
}


def get_sin(sin_id: str) -> dict:
    """Return sin definition dict."""
    return SIN_DEFINITIONS.get(sin_id, SIN_DEFINITIONS["pride"])


def get_corruption_modifier(champion) -> float:
    """
    Return the total corruption gain multiplier for a champion based on sin.
    Returns a delta (e.g. -0.20 means 20% reduction). Add to 1.0 for multiplier.
    """
    sin = getattr(champion, "sin", "pride") or "pride"
    defn = get_sin(sin)
    mod = defn.get("corruption_gain_mod", 0.0)

    # Post-PONR escalation for Pride
    if sin == "pride":
        if getattr(champion, "ponr_1_locked", False):
            mod += defn.get("corruption_post_ponr", 0.0)

    return mod


def get_arousal_modifier(champion) -> float:
    """Return arousal gain multiplier delta for champion's sin."""
    sin = getattr(champion, "sin", "pride") or "pride"
    return get_sin(sin).get("arousal_gain_mod", 0.0)


def get_combat_xp_bonus(champion) -> int:
    """Return extra XP granted on combat win from sin."""
    sin = getattr(champion, "sin", "pride") or "pride"
    return get_sin(sin).get("combat_win_xp_bonus", 0)


def inject_sin_context(champion) -> str:
    """Return the sin context line for AI context injection."""
    sin = getattr(champion, "sin", "pride") or "pride"
    defn = get_sin(sin)
    tone = getattr(champion, "tone_preference", "conflict") or "conflict"
    tone_labels = {
        "dread":    "experiences transformation with dread — the inner monologue emphasizes loss and wrongness",
        "conflict": "experiences transformation with conflict — compelling and distressing simultaneously",
        "relief":   "experiences transformation with secret relief — disturbed by how little they resist it",
    }
    return (
        f"Sin: {defn['label']} — {defn['description']}\n"
        f"Transformation Tone: {tone_labels.get(tone, tone_labels['conflict'])}"
    )
