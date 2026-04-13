"""
Character sheet synchronization for Echoes of the Tainted Throne.

Called when corruption stage transitions occur to update the structured
character sheet with stage-appropriate physical descriptions.

Stage 4 specifics (per GDD):
- Skin: soft, pale, almost luminous — succubus aesthetic, NOT hard scales
- Face: vulpine muzzle, soft and feminine, large amber eyes, small dark nose
- Body: petite, delicate, extremely feminine curves
- Features: fox ears, fluffy tail, tiny vestigial wings, retractable claws
- Faint iridescent shimmer in certain light only
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import Champion


# ---------------------------------------------------------------------------
# Stage physical baselines
# ---------------------------------------------------------------------------

STAGE_BASELINES: dict[int, dict] = {
    0: {
        "race":                   "Human",
        "height_cm":              178.0,
        "gender_presentation":    "masculine",
        "body_desc_face":         "angular jaw, weathered features, brown-amber eyes",
        "body_desc_chest":        "broad shoulders, flat chest — a fighter's build",
        "body_desc_hips":         "narrow, angular, unremarkable",
        "body_desc_skin":         "tanned, weathered — a soldier's skin",
        "body_desc_tail":         "none",
        "body_desc_ears":         "normal human",
        "scent":                  "sweat, steel, leather",
        "voice_desc":             "low, authoritative — used to being obeyed",
        "corruption_visible_signs": "none yet",
    },
    1: {
        "race":                   "Vulpine-Touched",
        "height_cm":              174.0,   # -4cm from baseline
        "gender_presentation":    "masculine-shifting",
        "body_desc_face":         "angular features softening slightly, amber eyes brighter than before",
        "body_desc_chest":        "still flat but the frame is losing definition around the edges",
        "body_desc_hips":         "barely perceptible rounding — you'd only notice if you'd looked before",
        "body_desc_skin":         "unchanged but warmer to the touch than it should be",
        "body_desc_tail":         "full fox tail — appears without warning, impossible to ignore",
        "body_desc_ears":         "pointed fox ears replacing human ears, mobile and sensitive",
        "scent":                  "steel and leather still, with warm animal musk underneath",
        "voice_desc":             "unchanged — still yours",
        "corruption_visible_signs": "fox ears, full tail, amber eyes that catch light differently at night",
    },
    2: {
        "race":                   "Full Vulpine",
        "height_cm":              169.0,   # -9cm from baseline
        "gender_presentation":    "androgynous",
        "body_desc_face":         "softer, almost beautiful in a way that doesn't sit right — your face, but changed",
        "body_desc_chest":        "small but unmistakable chest development — you've stopped looking at mirrors",
        "body_desc_hips":         "clearly wider now, impossible to hide under armor — the body is changing shape",
        "body_desc_skin":         "patches of fine auburn fur on shoulders, hips, upper thighs — spreading slowly",
        "body_desc_tail":         "full fox tail, more expressive than you want it to be",
        "body_desc_ears":         "fox ears, fully mobile — they move without your permission sometimes",
        "scent":                  "the soldier's smell is fading — what's left is warmer, softer, animal",
        "voice_desc":             "half an octave higher than it was — you hear it in your own words",
        "corruption_visible_signs": "visible fur patches, undeniable chest, face that reads as feminine to strangers",
    },
    3: {
        "race":                   "Kobold-Vulpine Hybrid",
        "height_cm":              152.0,   # -26cm from baseline
        "gender_presentation":    "feminine",
        "body_desc_face":         "vulpine features dominant — shorter muzzle, wide amber eyes, small nose, unmistakably animal",
        "body_desc_chest":        "fully developed, soft — the body has made its decision without you",
        "body_desc_hips":         "extreme hourglass — small frame, pronounced curve — a different kind of body entirely",
        "body_desc_skin":         "fur coverage on most of the body, fine and soft, auburn with darker accents",
        "body_desc_tail":         "full fox tail, thick and expressive — sometimes wraps around you when you're cold",
        "body_desc_ears":         "fox ears at full development — hearing range has expanded significantly",
        "scent":                  "distinctly vulpine musk now — compounds make certain NPCs respond differently to proximity",
        "voice_desc":             "high, soft, almost musical — nothing like the voice you trained to project command",
        "corruption_visible_signs": "extreme size reduction, hybrid features fully visible, movement patterns changed",
    },
    4: {
        "race":                   "Draconic Final Form",
        "height_cm":              107.0,   # -71cm from baseline, ~3.5 ft
        "gender_presentation":    "hyperfeminine",
        "body_desc_face":         "vulpine muzzle, soft and feminine — large luminous amber eyes, small dark nose, delicate — not fearsome",
        "body_desc_chest":        "full, soft, extremely sensitive — the draconic form amplifies all sensation here",
        "body_desc_hips":         "petite frame, extreme curves — delicate architecture that looks fragile and isn't",
        "body_desc_skin":         "impossibly soft, pale, almost luminous — like candlelight through silk — no hard scales, a faint iridescent shimmer in direct light only",
        "body_desc_tail":         "full fox tail, permanently warm — an extension of mood and sensation",
        "body_desc_ears":         "fox ears, ultra-sensitive — sound lands like touch at this stage",
        "scent":                  "soft, warm, involuntary — the kind of scent that affects others before they register it",
        "voice_desc":             "high, clear, soft — carries further than it should for the size",
        "corruption_visible_signs": "tiny vestigial wings (non-functional, deeply sensitive), retractable small claws, full transformation visible — nothing of the original form survives",
    },
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def build_stage_0_sheet(save_id: int, **overrides) -> dict:
    """Return the initial CharacterSheet field values for a new save."""
    baseline = {"save_id": save_id, **STAGE_BASELINES[0]}
    baseline.update(overrides)
    return baseline


def update_character_sheet(champion: "Champion", new_stage: int) -> None:
    """
    Apply stage-appropriate physical descriptions to the champion's character sheet.
    Called when a stage transition occurs in apply_corruption().
    Does NOT commit — the caller's session commit covers this.
    """
    sheet = None
    try:
        sheet = champion.save.character_sheet
    except Exception:
        return
    if sheet is None:
        return

    baseline = STAGE_BASELINES.get(new_stage, STAGE_BASELINES[4])
    for field, value in baseline.items():
        if field == "save_id":
            continue
        if hasattr(sheet, field):
            setattr(sheet, field, value)

    # Height sync: use champion's actual height_offset_in for precision
    baseline_height_cm = 178.0
    inches_to_cm = 2.54
    sheet.height_cm = round(
        baseline_height_cm + (champion.height_offset_in * inches_to_cm), 1
    )

    # Attraction arc thresholds (score already updated by submission.py)
    score = sheet.attraction_arc_score
    if score >= 85:
        sheet.attraction_current = "devoted to manhood"
    elif score >= 60:
        sheet.attraction_current = "male-drawn"
    elif score >= 30:
        sheet.attraction_current = "uncertain"
    # else leave as-is (female-leaning is the default)
