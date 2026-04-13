"""
Prompt assembler for Echoes of the Tainted Throne.

Takes a context packet (from context_builder) and encounter_data dict,
loads the appropriate template, and returns the complete user prompt
that gets sent to the local model alongside the system prompt.

Scene types (encounter_data["scene_type"]):
  "encounter_loss"   — combat loss / forced submission scene
  "encounter_win"    — combat win, brief flavour or tension scene
  "transformation"   — stage transition body change scene
  "kasyrra"          — Kasyrra encounter (any virility stage)
  "companion"        — companion event / interaction scene
  "camp"             — rest scene, passive reflection
  "travel"           — travel narration between regions
"""

from __future__ import annotations
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Template loader
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_SCENE_TYPE_TO_TEMPLATE: dict[str, str] = {
    "encounter_loss":  "encounter_loss.txt",
    "encounter_win":   "encounter_win.txt",
    "transformation":  "transformation.txt",
    "kasyrra":         "kasyrra.txt",
    "companion":       "companion.txt",
    "camp":            "camp.txt",
    "travel":          "travel.txt",
}

_FALLBACK_TEMPLATE = "encounter_loss.txt"


def _load_template(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    # Fallback: plain instruction if template file is missing
    return (
        "Using the context block above, write a scene for the encounter described "
        "in the ENCOUNTER section. Second person, present tense. 400–600 words.\n"
    )


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------

def build_encounter_prompt(context: str, encounter_data: dict) -> str:
    """
    Assemble the full user prompt.

    Structure:
      [context block]
      [encounter slot — appended to context]
      [blank line]
      [template directive]
    """
    from ai.context_builder import build_encounter_slot

    scene_type = encounter_data.get("scene_type", "encounter_loss")
    template_file = _SCENE_TYPE_TO_TEMPLATE.get(scene_type, _FALLBACK_TEMPLATE)
    template = _load_template(template_file)

    encounter_slot = build_encounter_slot(encounter_data)

    # Fill template placeholders with encounter_data values.
    # Templates use {key} syntax. Unknown keys are left as-is.
    filled_template = _safe_format(template, encounter_data)

    return f"{context}\n\n{encounter_slot}\n\n{filled_template}"


def _safe_format(template: str, data: dict) -> str:
    """
    Format a template string, silently leaving unfilled {keys} unchanged
    rather than raising KeyError.
    """
    import string

    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    return string.Formatter().vformat(template, [], SafeDict(data))


# ---------------------------------------------------------------------------
# Scene-type-specific convenience builders
# (called directly when the engine knows exactly what scene type to generate)
# ---------------------------------------------------------------------------

def build_transformation_prompt(context: str, stage_data: dict) -> str:
    """
    stage_data keys:
      old_stage (int), new_stage (int), stage_name (str),
      ponr_locked (bool), corruption_at_transition (float)
    """
    encounter_data = {
        "scene_type": "transformation",
        **stage_data,
    }
    return build_encounter_prompt(context, encounter_data)


def build_kasyrra_prompt(context: str, kasyrra_data: dict) -> str:
    """
    kasyrra_data keys:
      virility_stage (int), encounter_number (int),
      champion_submissive (bool), notes (str)
    """
    encounter_data = {
        "scene_type": "kasyrra",
        **kasyrra_data,
    }
    return build_encounter_prompt(context, encounter_data)


def build_companion_prompt(context: str, companion_data: dict) -> str:
    """
    companion_data keys:
      companion_name (str), event_id (str), notes (str)
    """
    encounter_data = {
        "scene_type": "companion",
        **companion_data,
    }
    return build_encounter_prompt(context, encounter_data)


def build_introspection_prompt(context: str, scene_text: str) -> str:
    """
    Prompt for the inner monologue endpoint.
    scene_text is the recently generated scene the champion is reacting to.
    The actual monologue instructions live in inner_monologue.txt system prompt.
    """
    return (
        f"{context}\n\n"
        f"SCENE THAT JUST OCCURRED:\n{scene_text}\n\n"
        "TASK:\n"
        "Write the champion's inner monologue now. "
        "First person, present tense. 100–150 words. No headers."
    )


def build_self_description_prompt(context: str) -> str:
    """
    Prompt for the inventory SELF tab — champion examining themselves in a mirror
    or stream, confronting what they've become. Emotional beat, not a stat readout.
    The word count guidance lives in self_description.txt system prompt.
    """
    return (
        f"{context}\n\n"
        "TASK:\n"
        "The champion examines themselves fully for the first time in days. "
        "Write what they see and what they feel about it. "
        "Second person, present tense. 200–300 words. No headers. No bullet points."
    )
