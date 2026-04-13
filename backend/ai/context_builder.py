"""
Context packet builder for Echoes of the Tainted Throne.

Every local AI call receives a structured context block assembled here.
The model never receives raw game state objects — only this serialised string.

The structure is stable and ordered so the model builds a reliable mental
model of what sections to expect.
"""

from __future__ import annotations
import json as _json
import os as _os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import SaveGame, Champion, Companion, WorldState, KasyrraState

# ---------------------------------------------------------------------------
# NPC profile cache — populated lazily from data/npcs/{name}.json
# ---------------------------------------------------------------------------

_NPC_CACHE: dict[str, dict] = {}


def _load_npc_profile(name: str) -> dict:
    """Load NPC profile from data/npcs/{name_lower}.json, with caching."""
    key = name.lower()
    if key in _NPC_CACHE:
        return _NPC_CACHE[key]

    # Path: context_builder.py is in backend/ai/, profiles are in data/npcs/
    path = _os.path.normpath(_os.path.join(
        _os.path.dirname(__file__), "..", "..", "data", "npcs", f"{key}.json"
    ))
    if _os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                profile = _json.load(f)
            _NPC_CACHE[key] = profile
            return profile
        except Exception:
            pass

    _NPC_CACHE[key] = {}
    return {}


# ---------------------------------------------------------------------------
# Scene types that warrant recent history injection
# ---------------------------------------------------------------------------

_HISTORY_SCENE_TYPES = {
    "encounter_loss", "encounter_win", "kasyrra", "transformation",
    "encounter_loss_oral", "encounter_loss_penetration"
}


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

def build_scene_context(save: "SaveGame", scene_type: str = "") -> str:
    """
    Assemble the full context packet from a SaveGame.
    Returns a structured string injected into every local AI prompt.
    """
    parts = [
        _champion_block(save.champion),
    ]

    # CHARACTER FACTS block — always present when character sheet exists
    sheet_block = _character_sheet_block(getattr(save, 'character_sheet', None))
    if sheet_block:
        parts.append(sheet_block)

    # SIN + TONE block — always injected; flavors every scene
    sin_block = _sin_tone_block(save.champion)
    if sin_block:
        parts.append(sin_block)

    parts.extend([
        _companions_block(save.companions),
        _world_block(save.world),
        _kasyrra_block(save.kasyrra),
    ])

    # RECENT HISTORY — only for encounter/transformation scenes
    history = _recent_history_block(save.champion, scene_type)
    if history:
        parts.append(history)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Champion block
# ---------------------------------------------------------------------------

def _champion_block(c: "Champion") -> str:
    active_statuses = [s for s in c.statuses if s.is_active]
    status_lines = "\n".join(
        f"  - {s.display_name}" + (f" ({s.duration_remaining} rounds remaining)" if s.duration_remaining else "")
        for s in active_statuses
    ) or "  None"

    cursed = ", ".join(c.cursed_items) or "None"
    toys   = ", ".join(c.active_toys)  or "None"

    # Stat penalty summary — only list stats modified below base (10)
    stat_notes = []
    if c.resolve < 10:
        stat_notes.append(f"Resolve {c.resolve}/10")
    if c.grace < 10:
        stat_notes.append(f"Grace {c.grace}/10")
    if c.force < 10:
        stat_notes.append(f"Force {c.force}/10")
    stat_note_str = ", ".join(stat_notes) if stat_notes else "Within normal range"

    height_note = ""
    try:
        h = c.height_cm  # uses property with stage reduction
        base = getattr(c, 'height_cm_base', 175.0) or 175.0
        height_note = f"\nHeight: {h:.0f}cm"
        if h < base:
            height_note += f" (baseline {base:.0f}cm — reduced by transformation)"
        if h < 160:
            height_note += " — notably shorter than most adults"
        if h < 150:
            height_note += " — distinctly small; companions help with height-dependent tasks"
    except Exception:
        if c.height_offset_in < 0:
            height_note = f"\nHeight Change: {abs(c.height_offset_in):.0f}\" shorter than baseline"

    return f"""=== CHAMPION ===
Name: {c.name}
Corruption: {c.corruption:.1f}%
Transformation Stage: {c.stage} — {c.stage_name}
  {c.stage_description_brief}{height_note}
Color Path (dominant): {c.color_path}

Physical State:
  {c.physical_description_current()}

Arousal: {c.arousal}/100
Submission Score: {c.submission_score:.1f}/100  (not shown to player — for narrative calibration only)
Stat Penalties: {stat_note_str}

Body Modifiers:
  Chastity Device Locked: {c.chastity_locked}
  Cursed Items: {cursed}
  Active Toys/Plugs: {toys}

Active Status Effects:
{status_lines}

Kasyrra's Mark: {'Applied — permanent' if c.kasyrra_mark_applied else 'Not yet applied'}"""


# ---------------------------------------------------------------------------
# Character facts block
# ---------------------------------------------------------------------------

def _character_sheet_block(sheet) -> str:
    """
    Structured physical facts that Gemma must not contradict.
    Injected into every AI context packet.
    """
    if sheet is None:
        return ""

    height_display = f"{sheet.height_cm:.0f}cm" if sheet.height_cm else "unknown"

    # Only show non-trivial tail/ear entries
    tail_line   = f"\nTail: {sheet.body_desc_tail}"   if sheet.body_desc_tail and sheet.body_desc_tail not in ("none", "") else ""
    ears_line   = f"\nEars: {sheet.body_desc_ears}"   if sheet.body_desc_ears and sheet.body_desc_ears not in ("normal human", "") else ""
    chest_line  = f"\nChest: {sheet.body_desc_chest}" if sheet.body_desc_chest and sheet.body_desc_chest.strip() else ""
    hips_line   = f"\nHips: {sheet.body_desc_hips}"   if sheet.body_desc_hips and sheet.body_desc_hips.strip() else ""
    signs_line  = f"\nVisible Corruption Signs: {sheet.corruption_visible_signs}" if sheet.corruption_visible_signs and sheet.corruption_visible_signs not in ("none yet", "none", "") else ""

    return f"""=== CHARACTER FACTS (do not contradict these) ===
Race/Form: {sheet.race}
Height: {height_display}
Gender Presentation: {sheet.gender_presentation}
Gender Attraction: {sheet.attraction_current}
Face: {sheet.body_desc_face}
Skin: {sheet.body_desc_skin}{chest_line}{hips_line}{tail_line}{ears_line}
Scent: {sheet.scent}
Voice: {sheet.voice_desc}{signs_line}
Attraction Arc: {sheet.attraction_current} (score {getattr(sheet, 'attraction_arc_score', 0)}/100)"""


# ---------------------------------------------------------------------------
# Sin + Tone block
# ---------------------------------------------------------------------------

_PERSONALITY_NOTES: dict[str, str] = {
    "stoic":      "Endures without complaint. Inner monologue is sparse, observational, action-oriented.",
    "warm":       "Connects easily. Processes change through feeling and relationship. More vulnerable interiority.",
    "analytical": "Catalogues everything. Processes change through understanding. Clinical framing that cracks under pressure.",
    "reckless":   "Acts before thinking. Less filtered inner monologue. The corruption has more to work with.",
}


def _sin_tone_block(c: "Champion") -> str:
    """
    Inject sin, tone preference, and personality into every AI context.
    Gemma uses this to calibrate scene intensity and inner monologue framing.
    """
    # Get personality from story_flags
    personality = "stoic"
    try:
        flags = (c.save.story_flags or {}) if hasattr(c, "save") and c.save else {}
        personality = flags.get("personality", "stoic") or "stoic"
    except Exception:
        pass
    personality_note = _PERSONALITY_NOTES.get(personality, _PERSONALITY_NOTES["stoic"])

    try:
        from sin_system import inject_sin_context
        base = inject_sin_context(c)
        return f"=== CHAMPION NATURE ===\n{base}\nPersonality: {personality} — {personality_note}"
    except Exception:
        sin = getattr(c, "sin", "pride") or "pride"
        tone = getattr(c, "tone_preference", "conflict") or "conflict"
        tone_labels = {
            "dread":    "experiences transformation with dread — emphasize loss and wrongness",
            "conflict": "experiences transformation with conflict — compelling and distressing simultaneously",
            "relief":   "experiences transformation with secret relief — disturbed by how little they resist",
        }
        return (
            f"=== CHAMPION NATURE ===\n"
            f"Sin: {sin}\n"
            f"Transformation Tone: {tone_labels.get(tone, tone_labels['conflict'])}\n"
            f"Personality: {personality} — {personality_note}"
        )


# ---------------------------------------------------------------------------
# Recent history block
# ---------------------------------------------------------------------------

def _recent_history_block(champion: "Champion", scene_type: str) -> str:
    """
    Last 5 significant events — only injected for encounter/transformation scenes.
    Travel and camp scenes don't need narrative history context.
    """
    if scene_type not in _HISTORY_SCENE_TYPES:
        return ""
    if not champion.event_log:
        return ""

    recent = sorted(champion.event_log, key=lambda e: e.id, reverse=True)[:5]
    recent.reverse()

    lines = ["=== RECENT HISTORY ==="]
    for entry in recent:
        d = entry.event_data or {}
        day = d.get("day", "?")
        etype = entry.event_id.replace("_", " ")
        parts = []
        if "enemy" in d:
            parts.append(f"vs {d['enemy']}")
        if "outcome" in d:
            parts.append(d["outcome"])
        if d.get("corruption_gained", 0) > 0:
            parts.append(f"corruption +{d['corruption_gained']:.1f}%")
        if "choice_made" in d:
            parts.append(f"chose: {d['choice_made']}")
        suffix = " | ".join(parts)
        lines.append(f"- Day {day} | {etype}" + (f" — {suffix}" if suffix else ""))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Companions block
# ---------------------------------------------------------------------------

_COMPANION_STAGE_NOTES: dict[str, dict[int, str]] = {
    "Saoirse": {
        0: "Treats Champion as the leader. Deferential on tactics.",
        1: "Noticeably more watchful. Hasn't said anything yet.",
        2: "Starting to make small decisions without asking. Doing it carefully.",
        3: "Protective anger at the situation — at Kasyrra, not the Champion. Making calls the Champion used to make.",
        4: "Primary carrier. Has a specific, memorised way of carrying the Champion. Never comments on it.",
    },
    "Mireille": {
        0: "Scholarly, composed, cataloguing everything.",
        1: "Taking notes on the physical changes. Clinical, but not unkind.",
        2: "Notes have become more personal. Quietly looking for a reversal.",
        3: "Has stopped looking for a reversal. Thinks the Champion deserves to know what they are now.",
        4: "Tells the Champion everything she knows about draconic physiology. Complete honesty.",
    },
    "Tierlan": {
        0: "Irreverent, sharp, testing everyone.",
        1: "Jokes about the ears. Actually comfortable with it.",
        2: "Built something to help carry supplies so the Champion doesn't have to. Didn't announce it.",
        3: "Keeps the levity alive — someone has to. Confides his history with corruption. Only at this stage.",
        4: "Carrier pack was done before anyone asked. Trusts the Champion absolutely.",
    },
}


def _companions_block(companions: list["Companion"]) -> str:
    if not companions:
        return "=== COMPANIONS ===\nNone present."

    lines = ["=== COMPANIONS ==="]
    for comp in companions:
        if not comp.is_present:
            lines.append(f"{comp.name}: Not present")
            continue

        stage = 0
        try:
            stage = comp.save.champion.stage
        except Exception:
            pass

        # Try JSON profile first, fall back to hardcoded dict
        profile = _load_npc_profile(comp.name)
        if profile:
            stage_reactions = profile.get("stage_reactions", {})
            stage_note = stage_reactions.get(str(stage), stage_reactions.get("0", ""))
            personality = profile.get("personality", "")
            voice_notes = profile.get("voice_notes", "")

            # Build a rich companion line
            note_parts = []
            if stage_note:
                note_parts.append(f"Current dynamic: {stage_note}")
            if voice_notes and stage == 0:
                note_parts.append(f"Voice: {voice_notes}")
            note_str = "\n  ".join(note_parts) if note_parts else "Present."
        else:
            # Fallback to hardcoded stage notes
            stage_note = _COMPANION_STAGE_NOTES.get(comp.name, {}).get(stage, "")
            note_str = f"Current dynamic: {stage_note}" if stage_note else "Present."

        lines.append(
            f"{comp.name} (relationship {comp.relationship_level}/100):\n"
            f"  {note_str}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# World block
# ---------------------------------------------------------------------------

def _world_block(w: "WorldState") -> str:
    weather_str = str(w.weather.value if hasattr(w.weather, "value") else w.weather)
    time_str    = str(w.time_of_day.value if hasattr(w.time_of_day, "value") else w.time_of_day)
    weather_note = ""
    if weather_str == "tainted_mist":
        weather_note = "\n  NOTE: Tainted mist is active — passive corruption +1/hour, arousal rising"
    elif weather_str == "storm":
        weather_note = "\n  NOTE: Storm — travel is impossible, enemies are sheltering"

    return f"""=== WORLD STATE ===
Region: {w.region}
Time: {time_str}, Day {w.in_game_day}
Weather: {weather_str}{weather_note}
Supplies: {w.supplies} days remaining
Party Morale: {w.morale}/100"""


# ---------------------------------------------------------------------------
# Kasyrra block
# ---------------------------------------------------------------------------

_KASYRRA_VIRILITY_DESC: dict[int, str] = {
    0: "Has not yet revealed the full scope of her intent.",
    1: "The first encounter has occurred. Her investment in the Champion is clear.",
    2: "Actively seeking the Champion out between arcs. More specific. More patient.",
    3: "The transformation is visibly proceeding as designed. She is pleased.",
    4: "Tender in a way she hasn't been with anything in centuries. Her goal is close.",
    5: "The Champion is what she built. The final encounter approaches.",
}


def _kasyrra_block(k: "KasyrraState") -> str:
    virility_desc = _KASYRRA_VIRILITY_DESC.get(k.virility_stage, "")
    last = k.last_encounter_summary or "No prior encounter."

    return f"""=== KASYRRA ===
Virility Stage: {k.virility_stage}/5
Current State: {virility_desc}
Kasyrra-Champion Alignment Score: {k.alignment_score:.1f}
Last Encounter: {last}"""


# ---------------------------------------------------------------------------
# Encounter slot builder
# Called by prompt_builder to append encounter-specific data to the context
# ---------------------------------------------------------------------------

def build_encounter_slot(encounter_data: dict) -> str:
    """
    Append the encounter-specific section to the context packet.
    This is the final section the model reads before writing.
    """
    scene_type        = encounter_data.get("scene_type", "encounter")
    enemy             = encounter_data.get("enemy", "Unknown")
    combat_result     = encounter_data.get("combat_result", "loss")
    corruption_gained = encounter_data.get("corruption_gained", 0.0)
    submission_events = encounter_data.get("submission_events", [])
    extra_notes       = encounter_data.get("notes", "")

    events_str = "\n".join(f"  - {e}" for e in submission_events) if submission_events else "  None"

    note_line   = f"\nAdditional Notes: {extra_notes}" if extra_notes else ""

    # Player's chosen narrative stance (set by the frontend after combat resolves)
    player_choice_label = encounter_data.get("player_choice_label", "")
    choice_line = (
        f"\nChampion's Response: {player_choice_label} "
        f"— Write the scene through this lens. Their choice is the frame."
    ) if player_choice_label else ""

    # HP damage note for the AI
    hp_lost = encounter_data.get("hp_lost", 0)
    carried = encounter_data.get("carried_to_safety", False)
    if carried:
        hp_line = "\nHP Note: Champion collapsed from wounds and was carried to safety by companions."
    elif hp_lost > 0:
        hp_line = f"\nHP Lost This Encounter: {hp_lost}"
    else:
        hp_line = ""

    return f"""=== ENCOUNTER ===
Scene Type: {scene_type}
Enemy/NPC: {enemy}
Combat Result: {combat_result}
Corruption Gained This Event: {corruption_gained:.1f}%
Submission Events Triggered:
{events_str}{note_line}{choice_line}{hp_line}"""
