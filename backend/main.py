"""
Echoes of the Tainted Throne — FastAPI backend.

Endpoints:
  POST /api/saves/new          — create new save
  GET  /api/saves/list         — list all save slots (up to 3)
  GET  /api/saves/{save_id}    — load full game state
  DELETE /api/saves/{save_id} — delete a save slot
  POST /api/time/advance       — advance in-game time (triggers passive ticks)
  POST /api/corruption/apply   — apply corruption delta
  POST /api/submission/event   — fire a submission event
  POST /api/combat/resolve     — resolve a combat encounter (dice + consequences)
  POST /api/scene/stream       — SSE stream: scene generation via local AI
  POST /api/scene/generate     — one-shot (non-streaming) scene generation
  GET  /api/ai/status          — check Ollama health
  GET  /api/character/sheet    — return structured character sheet
  GET  /api/saves/{save_id}/memory     — last 20 significant events
  GET  /api/saves/{save_id}/reputation — faction reputation state
  GET  /api/regions/{region_id}        — region data file
  GET  /api/codex/{entry_id}           — codex entry (flag-gated)
  GET  /api/saves/{save_id}/equipment  — equipped items for this save
  POST /api/saves/{save_id}/equip      — equip or unequip an item
  POST /api/travel/set-destination     — set travel destination for a save
  GET  /api/travel/status              — return travel destination and progress
  GET  /api/npc/dialogue/{npc_name}   — dialogue options for NPC at current relationship tier
  POST /api/npc/dialogue/respond       — register response choice, apply rel_delta, return reply
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.models import (
    SaveGame, Champion, WorldState, KasyrraState, Companion,
    init_db, get_session,
)
from corruption import apply_corruption, modified_corruption_gain, passive_corruption_tick
from submission import update_submission, passive_submission_tick, passive_arousal_tick
from character_sheet_sync import build_stage_0_sheet
from faction_reputation import update_reputation, reputation_dict
from event_log import log_event, format_recent_history
from equipment import get_starting_equipment, get_stat_bonuses, serialize_equipment
from leveling import award_xp, get_xp_to_next_level


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Log Ollama status at startup — non-fatal if not running
    from ai.local_client import check_ollama_health
    healthy, message = await check_ollama_health()
    status = "OK" if healthy else "WARN"
    print(f"[AI] Ollama status ({status}): {message}")
    yield


app = FastAPI(title="Echoes of the Tainted Throne", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to localhost:3000 in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------

def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Debug: last AI prompt cache (keyed by save_id, in-process only)
# ---------------------------------------------------------------------------

_last_ai_prompt: dict[int, str] = {}


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class NewSaveRequest(BaseModel):
    slot_name: str
    champion_name: str


class NewSaveRequestV2(BaseModel):
    slot_name: str
    champion_name: str
    background: str        = "warrior"         # warrior/scholar/scout
    gender_attraction: str = "female-leaning"
    # Extended character creation fields (Wave 1)
    gender: str            = "male"
    hair_color: str        = "brown"
    eye_color: str         = "brown"
    build: str             = "average"         # lean/average/broad
    sin: str               = "pride"           # pride/lust/sloth/wrath/envy/greed/gluttony
    tone_preference: str   = "conflict"        # dread/conflict/relief
    champion_secret: str | None = None
    # Extended character creation fields (Wave 2)
    height_cm: float       = 175.0             # 150–200cm
    face_desc: str         = ""                # freeform up to 60 chars
    personality: str       = "stoic"           # stoic/warm/analytical/reckless


class DeleteSaveRequest(BaseModel):
    save_id: int


class TimeAdvanceRequest(BaseModel):
    save_id: int
    hours: float


class CorruptionRequest(BaseModel):
    save_id: int
    delta: float
    source: str = "encounter"
    apply_modifiers: bool = True   # run through modified_corruption_gain()


class SubmissionEventRequest(BaseModel):
    save_id: int
    event_id: str


class CombatResolveRequest(BaseModel):
    save_id: int
    encounter_id: str


class SceneRequest(BaseModel):
    save_id: int
    encounter_data: dict
    show_thinking: bool = False
    style_sample: str = ""


class IntrospectRequest(BaseModel):
    save_id: int
    scene_text: str


class SelfDescribeRequest(BaseModel):
    save_id: int


class DebugThinkRequest(BaseModel):
    save_id: int
    scene_text: str


# ---------------------------------------------------------------------------
# Response serialisers (lightweight — full state serialisation in /saves)
# ---------------------------------------------------------------------------

def _champion_dict(c: Champion) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "corruption": round(c.corruption, 2),
        "stage": c.stage,
        "stage_name": c.stage_name,
        "stage_description_brief": c.stage_description_brief,
        "submission_score": round(c.submission_score, 2),
        "arousal": c.arousal,
        "resolve": c.resolve,
        "grace": c.grace,
        "force": c.force,
        "presence": c.presence,
        "essence": c.essence,
        "current_hp": c.current_hp,
        "max_hp": c.max_hp,
        "feminization": c.feminization,
        "height_offset_in": c.height_offset_in,
        "color_path": c.color_path,
        "chastity_locked": c.chastity_locked,
        "kasyrra_mark_applied": c.kasyrra_mark_applied,
        "ponr_locks": {
            "1": c.ponr_1_locked,
            "2": c.ponr_2_locked,
            "3": c.ponr_3_locked,
            "4": c.ponr_4_locked,
        },
        "active_statuses": [
            {"effect_id": s.effect_id, "display_name": s.display_name, "duration": s.duration_remaining}
            for s in c.statuses if s.is_active
        ],
        "physical_description": c.physical_description_current(),
        "cursed_items": c.cursed_items,
        "active_toys": c.active_toys,
        "experience":      c.experience or 0,
        "xp_current":      c.experience or 0,
        "level":           c.level or 1,
        "xp_to_next":      get_xp_to_next_level(c.level or 1),
        "equipment_slots": c.equipment_slots or {},
        "sin":             getattr(c, "sin", "pride") or "pride",
        "tone_preference": getattr(c, "tone_preference", "conflict") or "conflict",
        "gender":          getattr(c, "gender", "male") or "male",
        "hair_color":      getattr(c, "hair_color", "brown") or "brown",
        "eye_color":       getattr(c, "eye_color", "brown") or "brown",
        "build":           getattr(c, "build", "average") or "average",
        "background":      getattr(c, "background", "warrior") or "warrior",
        "prologue_done":   bool(getattr(c, "prologue_done", False)),
        "height_cm":       getattr(c, "height_cm", 175.0),
        "height_cm_base":  getattr(c, "height_cm_base", 175.0),
    }


def _world_dict(w: WorldState) -> dict:
    weather_str = str(w.weather.value if hasattr(w.weather, "value") else w.weather)
    try:
        from weather import get_weather_symbol, get_weather_effects
        weather_symbol  = get_weather_symbol(weather_str)
        weather_effects = get_weather_effects(weather_str)
    except Exception:
        weather_symbol  = "☁"
        weather_effects = {}
    return {
        "region":              w.region,
        "time_of_day":         str(w.time_of_day.value if hasattr(w.time_of_day, "value") else w.time_of_day),
        "weather":             weather_str,
        "weather_symbol":      weather_symbol,
        "weather_days":        getattr(w, "weather_days_remaining", 2) or 2,
        "weather_effects":     weather_effects,
        "supplies":            w.supplies,
        "morale":              w.morale,
        "in_game_day":         w.in_game_day,
        "in_game_hour":        w.in_game_hour,
        "travel_destination":  w.travel_destination,
        "travel_progress":     w.travel_progress or 0,
        "travel_steps_total":  w.travel_steps_total or 10,
    }


def _kasyrra_dict(k: KasyrraState) -> dict:
    return {
        "virility_stage": k.virility_stage,
        "encounter_count": k.encounter_count,
        "last_encounter_summary": k.last_encounter_summary,
        "alignment_score": k.alignment_score,
    }


def _companion_dict(c: Companion) -> dict:
    return {
        "name": c.name,
        "relationship_level": c.relationship_level,
        "is_present": c.is_present,
        "flags": c.flags,
    }


def _character_sheet_dict(sheet) -> dict:
    if sheet is None:
        return {}
    return {
        "race":                    sheet.race,
        "height_cm":               sheet.height_cm,
        "gender_presentation":     sheet.gender_presentation,
        "gender_attraction":       sheet.gender_attraction,
        "body_desc_face":          sheet.body_desc_face,
        "body_desc_skin":          sheet.body_desc_skin,
        "body_desc_tail":          sheet.body_desc_tail,
        "body_desc_ears":          sheet.body_desc_ears,
        "scent":                   sheet.scent,
        "voice_desc":              sheet.voice_desc,
        "corruption_visible_signs": sheet.corruption_visible_signs,
        "attraction_current":      sheet.attraction_current,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_save_or_404(save_id: int, db: Session) -> SaveGame:
    save = db.get(SaveGame, save_id)
    if not save:
        raise HTTPException(status_code=404, detail=f"Save {save_id} not found")
    return save


def _check_dream_trigger(save: "SaveGame", db: "Session") -> dict | None:
    """
    Check if any dream sequence should fire after a long rest.
    Returns dream data dict if triggered, None otherwise.
    Each dream fires at most once per save (tracked in story_flags).
    """
    import json as _json, os as _os, glob as _glob

    champion = save.champion
    sheet    = getattr(save, 'character_sheet', None)
    flags    = save.story_flags or {}

    corruption    = champion.corruption or 0.0
    arc_score     = (sheet.attraction_arc_score if sheet else 0) or 0
    submission    = champion.submission_score or 0.0
    kasyrra_met   = bool(save.kasyrra and save.kasyrra.virility_stage > 0)

    # Find all dream files
    dreams_dir = _os.path.normpath(_os.path.join(
        _os.path.dirname(__file__), "..", "data", "dreams"
    ))
    dream_files = sorted(_glob.glob(_os.path.join(dreams_dir, "dream_*.json")))

    for dream_path in dream_files:
        try:
            with open(dream_path, "r", encoding="utf-8") as f:
                dream = _json.load(f)
        except Exception:
            continue

        dream_id = dream.get("id")
        if not dream_id or flags.get(f"dream_done_{dream_id}"):
            continue

        # Trigger fields: corruption_min, attraction_min, submission_min,
        # after_kasyrra_encounter (bool)
        trigger = dream.get("trigger", {})
        if corruption < trigger.get("corruption_min", 0):
            continue
        if arc_score < trigger.get("attraction_min", 0):
            continue
        if submission < trigger.get("submission_min", 0):
            continue
        if trigger.get("after_kasyrra_encounter") and not kasyrra_met:
            continue

        # Apply mechanical effects (field: mechanical_effects)
        effects = dream.get("mechanical_effects", {})
        if sheet and effects.get("attraction_arc"):
            sheet.attraction_arc_score = min(100, (sheet.attraction_arc_score or 0) + effects["attraction_arc"])
        if effects.get("submission"):
            champion.submission_score = min(100.0, (champion.submission_score or 0) + effects["submission"])
        if effects.get("arousal"):
            champion.arousal = min(100, (champion.arousal or 0) + effects["arousal"])
        if save.kasyrra and effects.get("kasyrra_alignment"):
            save.kasyrra.alignment_score = (save.kasyrra.alignment_score or 0) + effects["kasyrra_alignment"]
        if effects.get("corruption"):
            try:
                from corruption import apply_corruption
                apply_corruption(champion, effects["corruption"], source="dream")
            except Exception:
                pass

        flags[f"dream_done_{dream_id}"] = True
        save.story_flags = flags

        log_event(save, "dream", {
            "dream_id": dream_id,
            "day": save.world.in_game_day if save.world else 0,
        }, db)
        return {
            "id":    dream_id,
            "title": dream.get("title", ""),
            "text":  dream.get("text", ""),
        }

    return None


def _check_gift_trigger(save: "SaveGame", db: "Session") -> dict | None:
    """
    Check if Kasyrra's gift should be delivered based on corruption milestones.
    Returns gift data dict if triggered, None otherwise.
    Gifts fire at corruption thresholds 20/40/60/80%.
    """
    import json as _json, os as _os

    champion = save.champion
    flags    = save.story_flags or {}
    corruption = champion.corruption or 0.0

    gifts_path = _os.path.normpath(_os.path.join(
        _os.path.dirname(__file__), "..", "data", "gifts", "gifts.json"
    ))
    try:
        with open(gifts_path, "r", encoding="utf-8") as f:
            gifts_data = _json.load(f)
    except Exception:
        return None

    # gifts.json uses a dict keyed by gift id, with trigger_corruption field
    if isinstance(gifts_data, dict):
        gift_list = list(gifts_data.values())
    else:
        gift_list = gifts_data.get("gifts", [])

    # Sort by trigger threshold so lower ones fire first
    gift_list = sorted(gift_list, key=lambda g: g.get("trigger_corruption", 0))

    for gift in gift_list:
        gift_id   = gift.get("id")
        threshold = gift.get("trigger_corruption", gift.get("corruption_threshold", 0))

        if not gift_id or flags.get(f"gift_triggered_{gift_id}"):
            continue
        if corruption < threshold:
            continue

        flags[f"gift_triggered_{gift_id}"] = True
        save.story_flags = flags

        log_event(save, "kasyrra_gift", {
            "gift_id":   gift_id,
            "threshold": threshold,
            "day":       save.world.in_game_day if save.world else 0,
        }, db)
        return {
            "id":              gift_id,
            "name":            gift.get("name", ""),
            "discovery_scene": gift.get("discovery_scene", ""),
            # Normalize choices from the various effect keys present
            "consume_effects": gift.get("consume_effects"),
            "wear_effects":    gift.get("wear_effects"),
            "keep_effects":    gift.get("keep_effects"),
            "destroy_effects": gift.get("destroy_effects"),
            "unlock_chastity": gift.get("unlock_chastity", False),
        }

    return None


def _check_attraction_reactions(save: "SaveGame", db: Session) -> None:
    """
    Check if an attraction arc threshold was just crossed and log the
    corresponding companion reaction as a story event.
    Called after update_submission() commits attraction changes.
    """
    import json as _json
    import os as _os

    flags = save.story_flags or {}
    # Map of flag → reaction key in attraction_reactions.json
    reaction_map = {
        "attraction_crossed_uncertain":         "tierlan_uncertain",
        "attraction_crossed_male-drawn":        "mireille_male_drawn",
        "attraction_crossed_seeking_dominance": "saoirse_seeking",
    }

    any_triggered = False
    for flag_key, reaction_key in reaction_map.items():
        if flags.get(flag_key) and not flags.get(f"reaction_done_{reaction_key}"):
            # Load reaction text
            reactions_path = _os.path.normpath(_os.path.join(
                _os.path.dirname(__file__), "..", "data", "npcs", "attraction_reactions.json"
            ))
            try:
                with open(reactions_path, "r", encoding="utf-8") as f:
                    reactions = _json.load(f)
                reaction = reactions.get(reaction_key, {})
                speaker  = reaction.get("speaker", "Companion")
                text     = reaction.get("text") or reaction.get("notebook_text", "")
                log_event(save, "attraction_reaction", {
                    "reaction_key": reaction_key,
                    "speaker": speaker,
                    "text": text,
                    "trigger": reaction.get("trigger", ""),
                    "day": save.world.in_game_day if save.world else 0,
                })
                flags[f"reaction_done_{reaction_key}"] = True
                any_triggered = True
            except Exception:
                pass

    if any_triggered:
        save.story_flags = flags


def _check_kasyrra_1_trigger(save: "SaveGame", db: "Session") -> dict | None:
    """
    Fire the scripted first Kasyrra encounter on Day 3 (once only).
    Returns scene data dict or None.
    """
    import json as _json, os as _os

    world = save.world
    flags = save.story_flags or {}

    if flags.get("kasyrra_1_done"):
        return None
    if not world or world.in_game_day < 3:
        return None

    scene_path = _os.path.normpath(_os.path.join(
        _os.path.dirname(__file__), "..", "data", "story", "kasyrra_1.json"
    ))
    try:
        with open(scene_path, "r", encoding="utf-8") as f:
            scene = _json.load(f)
    except Exception:
        return None

    champion = save.champion
    apply_corruption(champion, float(scene.get("corruption_gain", 5.0)),
                     source="kasyrra_1_encounter")
    if scene.get("mark_applied"):
        champion.kasyrra_mark_applied = True

    flags["kasyrra_1_done"] = True
    save.story_flags = flags

    log_event(save, "kasyrra_1_encounter", {
        "day": world.in_game_day,
        "corruption_gain": scene.get("corruption_gain", 5.0),
    }, db)

    bg = getattr(champion, "background", None) or "warrior"
    text_key = f"text_{bg}"
    text = scene.get(text_key) or scene.get("text_default", "")

    return {
        "id":                  "kasyrra_1",
        "title":               scene.get("title", "First Encounter"),
        "text":                text,
        "companion_reactions": scene.get("companion_reactions", {}),
        "aftermath":           scene.get("aftermath", ""),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/ai/status")
async def ai_status():
    """Check whether the local Ollama instance is reachable and which models are available."""
    from ai.local_client import check_ollama_health, load_model_config
    healthy, message = await check_ollama_health()
    cfg = load_model_config()
    return {
        "ollama_healthy": healthy,
        "message": message,
        "configured_model": cfg["model"],
    }


@app.post("/api/saves/new", status_code=201)
async def new_save(req: NewSaveRequestV2, db: Session = Depends(get_db)):
    """Create a new save slot with default game state."""
    from db.models import CharacterSheet, FactionReputation

    save = SaveGame(slot_name=req.slot_name)
    db.add(save)
    db.flush()  # get save.id before creating children

    champion = Champion(
        save_id=save.id,
        name=req.champion_name,
        corruption=0.0,
        submission_score=0.0,
        stage=0,
        background=req.background,
        sin=req.sin,
        tone_preference=req.tone_preference,
        gender=req.gender,
        hair_color=req.hair_color,
        eye_color=req.eye_color,
        build=req.build,
    )
    world = WorldState(save_id=save.id)
    kasyrra = KasyrraState(save_id=save.id)

    companions = [
        Companion(save_id=save.id, name="Saoirse",  relationship_level=30),
        Companion(save_id=save.id, name="Mireille", relationship_level=30),
        Companion(save_id=save.id, name="Tierlan",  relationship_level=30),
    ]

    db.add_all([champion, world, kasyrra, *companions])
    db.flush()  # get champion.id

    # Apply background stat + HP bonuses
    background_bonuses = {
        "warrior": {"force": 2, "max_hp": 15, "current_hp": 15},
        "scholar": {"presence": 2, "essence": 20},
        "scout":   {"grace": 2},
    }
    bonuses = background_bonuses.get(req.background, {})
    for stat, bonus in bonuses.items():
        current = getattr(champion, stat, None)
        if current is not None:
            setattr(champion, stat, current + bonus)

    # Apply build stat bonuses
    build_bonuses = {
        "lean":  {"grace": 2},
        "broad": {"force": 2},
    }
    for stat, bonus in build_bonuses.get(req.build, {}).items():
        current = getattr(champion, stat, 10)
        setattr(champion, stat, current + bonus)

    # Store champion secret in story_flags
    if req.champion_secret:
        save.story_flags = {**(save.story_flags or {}), "champion_secret": req.champion_secret}

    # Apply height from character creation
    height_cm_base = max(150.0, min(200.0, float(req.height_cm or 175.0)))
    champion.height_cm_base = height_cm_base

    # Apply personality to story_flags (used by AI context)
    save.story_flags = {
        **(save.story_flags or {}),
        "personality": req.personality or "stoic",
    }

    # Create character sheet with appearance details
    sheet_data = build_stage_0_sheet(save.id)
    # Build face description: use custom input if provided, else auto-generate
    if req.face_desc and req.face_desc.strip():
        face_desc = req.face_desc.strip()[:60]
    else:
        face_desc = (
            f"{req.hair_color} hair, {req.eye_color} eyes"
            + (", angular jaw" if req.gender == "male" else ", soft features")
        )
    sheet = CharacterSheet(
        save_id=save.id,
        gender_attraction=req.gender_attraction,
        attraction_current=req.gender_attraction,
        body_desc_face=face_desc,
        **{k: v for k, v in sheet_data.items() if k not in ("save_id", "body_desc_face")},
    )

    # Create faction reputation
    reputation = FactionReputation(save_id=save.id)

    db.add_all([sheet, reputation])

    # Initialize starting equipment
    champion.equipment_slots = get_starting_equipment(req.background)
    champion.level = 1
    champion.experience = 0

    db.commit()
    db.refresh(save)

    return {"save_id": save.id, "slot_name": save.slot_name}


@app.get("/api/saves/list")
async def list_saves(db: Session = Depends(get_db)):
    """Return all save slots (up to 3)."""
    saves = db.query(SaveGame).order_by(SaveGame.id).limit(3).all()
    result = []
    for s in saves:
        c = s.champion
        w = s.world
        result.append({
            "save_id":    s.id,
            "slot_name":  s.slot_name,
            "exists":     True,
            "champion_name": c.name if c else "—",
            "stage":      c.stage if c else 0,
            "stage_name": c.stage_name if c else "Human",
            "corruption": round(c.corruption, 1) if c else 0.0,
            "days":       w.in_game_day if w else 1,
            "region":     w.region if w else "Wolf-Road Edge",
        })
    # Pad to 3 empty slots
    while len(result) < 3:
        result.append({"save_id": None, "exists": False, "slot_name": f"Slot {len(result)+1}"})
    return result


@app.get("/api/saves/{save_id}")
async def load_save(save_id: int, db: Session = Depends(get_db)):
    """Return the full game state for a save slot."""
    save = _load_save_or_404(save_id, db)
    return {
        "save_id":        save.id,
        "slot_name":      save.slot_name,
        "champion":       _champion_dict(save.champion),
        "world":          _world_dict(save.world),
        "kasyrra":        _kasyrra_dict(save.kasyrra),
        "companions":     [_companion_dict(c) for c in save.companions],
        "character_sheet": _character_sheet_dict(save.character_sheet),
        "story_flags":    save.story_flags or {},
    }


@app.delete("/api/saves/{save_id}")
async def delete_save(save_id: int, db: Session = Depends(get_db)):
    """Delete a save slot."""
    save = _load_save_or_404(save_id, db)
    db.delete(save)
    db.commit()
    return {"deleted": True, "save_id": save_id}


@app.post("/api/saves/save")
async def touch_save(req: DeleteSaveRequest, db: Session = Depends(get_db)):
    """Touch the save's updated_at timestamp. Called after combat/rest/gift."""
    save = _load_save_or_404(req.save_id, db)
    save.updated_at = datetime.utcnow()
    db.commit()
    return {"saved": True, "save_id": req.save_id}


@app.get("/api/saves/{save_id}/equipment")
async def get_equipment(save_id: int, db: Session = Depends(get_db)):
    """Return equipped items for this save."""
    save = _load_save_or_404(save_id, db)
    return {"slots": serialize_equipment(save.champion.equipment_slots)}


@app.post("/api/saves/{save_id}/equip")
async def equip_item(save_id: int, slot: str, item_id: str | None = None, db: Session = Depends(get_db)):
    """Equip or unequip an item. Pass item_id=null to unequip."""
    from equipment import SLOT_ORDER
    save = _load_save_or_404(save_id, db)
    if slot not in SLOT_ORDER:
        raise HTTPException(status_code=400, detail=f"Unknown slot: {slot}")
    slots = dict(save.champion.equipment_slots or {})
    slots[slot] = None  # unequip
    save.champion.equipment_slots = slots
    db.commit()
    return {"slot": slot, "item": None, "message": "Unequipped"}


@app.post("/api/travel/set-destination")
async def set_travel_destination(save_id: int, destination: str, db: Session = Depends(get_db)):
    """Set the travel destination for a save."""
    save = _load_save_or_404(save_id, db)
    save.world.travel_destination = destination
    save.world.travel_progress = 0
    db.commit()
    return _world_dict(save.world)


@app.get("/api/travel/status")
async def get_travel_status(save_id: int, db: Session = Depends(get_db)):
    """Return travel destination and progress."""
    save = _load_save_or_404(save_id, db)
    w = save.world
    return {
        "destination": w.travel_destination,
        "progress":    w.travel_progress or 0,
        "total_steps": w.travel_steps_total or 10,
        "arrived":     (w.travel_progress or 0) >= (w.travel_steps_total or 10),
    }


@app.get("/api/character/sheet")
async def get_character_sheet(save_id: int, db: Session = Depends(get_db)):
    """Return the character sheet for a save."""
    save = _load_save_or_404(save_id, db)
    sheet = save.character_sheet
    if sheet is None:
        raise HTTPException(status_code=404, detail="Character sheet not found")
    return {
        "race":                    sheet.race,
        "height_cm":               sheet.height_cm,
        "gender_presentation":     sheet.gender_presentation,
        "gender_attraction":       sheet.gender_attraction,
        "body_desc_chest":         sheet.body_desc_chest,
        "body_desc_hips":          sheet.body_desc_hips,
        "body_desc_face":          sheet.body_desc_face,
        "body_desc_skin":          sheet.body_desc_skin,
        "body_desc_tail":          sheet.body_desc_tail,
        "body_desc_ears":          sheet.body_desc_ears,
        "scent":                   sheet.scent,
        "voice_desc":              sheet.voice_desc,
        "corruption_visible_signs": sheet.corruption_visible_signs,
        "attraction_current":      sheet.attraction_current,
        "attraction_arc_score":    sheet.attraction_arc_score,
    }


@app.get("/api/saves/{save_id}/memory")
async def get_memory(save_id: int, db: Session = Depends(get_db)):
    """Return last 20 significant events for narrative continuity."""
    save = _load_save_or_404(save_id, db)
    from db.models import EventLogEntry
    entries = (
        db.query(EventLogEntry)
        .filter(EventLogEntry.champion_id == save.champion.id)
        .order_by(EventLogEntry.id.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id":         e.id,
            "event_type": e.event_id,
            "data":       e.event_data,
            "day":        (e.event_data or {}).get("day", "?"),
        }
        for e in entries
    ]


@app.get("/api/saves/{save_id}/reputation")
async def get_reputation(save_id: int, db: Session = Depends(get_db)):
    """Return faction reputation state."""
    save = _load_save_or_404(save_id, db)
    return reputation_dict(save.reputation)


# ---------------------------------------------------------------------------
# Prologue routes
# ---------------------------------------------------------------------------

@app.get("/api/prologue/status")
async def prologue_status(save_id: int, db: Session = Depends(get_db)):
    """Return current prologue status for a save."""
    from prologue import is_prologue_done, get_current_act, load_prologue_acts
    save = _load_save_or_404(save_id, db)
    done = is_prologue_done(save)
    current_act = get_current_act(save) if not done else None
    acts_data = load_prologue_acts()
    acts = acts_data.get("acts", [])
    act_data = next((a for a in acts if a["id"] == current_act), None) if current_act else None
    return {
        "prologue_done":    done,
        "current_act":      current_act,
        "act_data":         act_data,
        "background":       save.champion.background or "warrior",
    }


@app.post("/api/prologue/advance")
async def prologue_advance(save_id: int, completed_act: str, db: Session = Depends(get_db)):
    """Mark a prologue act complete and return the next act."""
    from prologue import advance_prologue_act, load_prologue_acts
    save = _load_save_or_404(save_id, db)
    next_act_id = advance_prologue_act(save, completed_act, db)
    db.commit()
    acts_data = load_prologue_acts()
    acts = acts_data.get("acts", [])
    next_act = next((a for a in acts if a["id"] == next_act_id), None) if next_act_id else None
    return {
        "completed_act":  completed_act,
        "next_act":       next_act_id,
        "next_act_data":  next_act,
        "prologue_done":  next_act_id is None,
        "world":          _world_dict(save.world),
        "champion":       _champion_dict(save.champion),
    }


class PrologueCombatRequest(BaseModel):
    save_id: int
    act_id: str
    result: str   # "win" or "loss"


@app.post("/api/prologue/combat")
async def prologue_combat(req: PrologueCombatRequest, db: Session = Depends(get_db)):
    """
    Resolve a prologue combat act (act_7_lone_wolf).
    Applies corruption on loss, then advances to the next act.
    Returns next act data and updated state.
    """
    from prologue import advance_prologue_act, load_prologue_acts
    save = _load_save_or_404(req.save_id, db)
    acts_data = load_prologue_acts()
    acts = acts_data.get("acts", [])
    act = next((a for a in acts if a["id"] == req.act_id), None)

    if act is None:
        raise HTTPException(status_code=404, detail=f"Prologue act '{req.act_id}' not found")

    corruption_gained = 0.0
    if req.result == "loss":
        corruption_gained = float(act.get("combat_corruption_on_loss", 2.0))
        save.champion.corruption = min(100.0, (save.champion.corruption or 0.0) + corruption_gained)

    next_act_id = advance_prologue_act(save, req.act_id, db)
    db.commit()

    next_act = next((a for a in acts if a["id"] == next_act_id), None) if next_act_id else None
    return {
        "act_id":           req.act_id,
        "result":           req.result,
        "corruption_gained": corruption_gained,
        "next_act":         next_act_id,
        "next_act_data":    next_act,
        "prologue_done":    next_act_id is None,
        "world":            _world_dict(save.world),
        "champion":         _champion_dict(save.champion),
    }


@app.post("/api/prologue/skip")
async def prologue_skip(save_id: int, db: Session = Depends(get_db)):
    """Skip the prologue and start at day 3."""
    from prologue import skip_prologue, load_prologue_acts
    save = _load_save_or_404(save_id, db)
    skip_prologue(save, db)
    db.commit()
    acts_data = load_prologue_acts()
    return {
        "skipped":   True,
        "skip_text": acts_data.get("skip_text", ""),
        "world":     _world_dict(save.world),
        "champion":  _champion_dict(save.champion),
    }


class GiftChoiceRequest(BaseModel):
    save_id: int
    gift_id: str
    choice: str   # "consume", "wear", "keep", "destroy"


@app.post("/api/gift/apply")
async def gift_apply(req: GiftChoiceRequest, db: Session = Depends(get_db)):
    """Apply the player's gift choice and return updated champion state."""
    import json as _json, os as _os
    save = _load_save_or_404(req.save_id, db)
    champion = save.champion
    sheet = getattr(save, 'character_sheet', None)

    gifts_path = _os.path.normpath(_os.path.join(
        _os.path.dirname(__file__), "..", "data", "gifts", "gifts.json"
    ))
    try:
        with open(gifts_path, "r", encoding="utf-8") as f:
            gifts_data = _json.load(f)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load gifts data")

    gift = gifts_data.get(req.gift_id)
    if not gift:
        raise HTTPException(status_code=404, detail=f"Gift '{req.gift_id}' not found")

    choice = req.choice
    applied = {}

    if choice == "consume" and gift.get("consume_effects"):
        eff = gift["consume_effects"]
        if eff.get("hp_restore"):
            champion.current_hp = min(champion.max_hp, (champion.current_hp or 0) + eff["hp_restore"])
            applied["hp_restored"] = eff["hp_restore"]
        if eff.get("arousal_reduce"):
            champion.arousal = max(0, (champion.arousal or 0) - eff["arousal_reduce"])
            applied["arousal_reduced"] = eff["arousal_reduce"]

    elif choice == "keep" and gift.get("keep_effects"):
        eff = gift["keep_effects"]
        if eff.get("presence"):
            champion.presence = (champion.presence or 10) + eff["presence"]
            applied["presence_gained"] = eff["presence"]
        if eff.get("kasyrra_alignment") and save.kasyrra:
            save.kasyrra.alignment_score = (save.kasyrra.alignment_score or 0) + eff["kasyrra_alignment"]
            applied["kasyrra_alignment"] = eff["kasyrra_alignment"]

    elif choice == "wear" and gift.get("wear_effects"):
        eff = gift["wear_effects"]
        if eff.get("presence"):
            champion.presence = (champion.presence or 10) + eff["presence"]
            applied["presence_gained"] = eff["presence"]
        if eff.get("kasyrra_alignment") and save.kasyrra:
            save.kasyrra.alignment_score = (save.kasyrra.alignment_score or 0) + eff["kasyrra_alignment"]
            applied["kasyrra_alignment"] = eff["kasyrra_alignment"]

    elif choice == "destroy" and gift.get("destroy_effects"):
        eff = gift["destroy_effects"]
        if eff.get("kasyrra_alignment") and save.kasyrra:
            save.kasyrra.alignment_score = (save.kasyrra.alignment_score or 0) + eff["kasyrra_alignment"]
            applied["kasyrra_alignment"] = eff["kasyrra_alignment"]

    elif choice == "unlock" and gift.get("unlock_chastity"):
        champion.chastity_locked = False
        applied["chastity_unlocked"] = True

    log_event(save, "gift_choice", {
        "gift_id": req.gift_id,
        "choice":  choice,
        "day":     save.world.in_game_day if save.world else 0,
    }, db)
    db.commit()
    return {"gift_id": req.gift_id, "choice": choice, "applied": applied, "champion": _champion_dict(champion)}


@app.get("/api/regions/{region_id}")
async def get_region(region_id: str):
    """Return a region data file from data/regions/."""
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..", "data", "regions", f"{region_id}.json"
    )
    path = os.path.normpath(path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Region '{region_id}' not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/codex/{entry_id}")
async def get_codex_entry(entry_id: str, save_id: int, db: Session = Depends(get_db)):
    """Return a codex entry if unlocked for this save."""
    import os
    save = _load_save_or_404(save_id, db)
    story_flags = save.story_flags or {}

    # Try data/codex/{entry_id}.json
    path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "codex", f"{entry_id}.json"
    ))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Codex entry '{entry_id}' not found")

    with open(path, "r", encoding="utf-8") as f:
        entry = json.load(f)

    unlock_flag = entry.get("unlock_flag", "")
    if unlock_flag and not story_flags.get(unlock_flag, False):
        return {"id": entry_id, "locked": True, "unlock_condition": entry.get("unlock_condition", "")}

    return entry


@app.get("/api/npc/dialogue/{npc_name}")
async def get_npc_dialogue(npc_name: str, save_id: int, db: Session = Depends(get_db)):
    """
    Return dialogue options for an NPC based on current relationship level.
    Selects the tier at or below the current relationship.
    """
    import os, random as _rand
    save = _load_save_or_404(save_id, db)

    # Find companion
    companion = next(
        (c for c in save.companions if c.name.lower() == npc_name.lower()),
        None
    )
    rel = companion.relationship_level if companion else 30

    # Load dialogue JSON
    path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "npcs", "dialogue", f"{npc_name.lower()}.json"
    ))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"No dialogue for {npc_name}")

    with open(path, "r", encoding="utf-8") as f:
        dialogue = json.load(f)

    tiers = dialogue.get("tiers", {})
    # Find the highest tier <= current relationship
    valid_tiers = [int(k) for k in tiers.keys() if int(k) <= rel]
    if not valid_tiers:
        valid_tiers = [min(int(k) for k in tiers.keys())]

    tier_key = str(max(valid_tiers))
    tier_data = tiers[tier_key]

    return {
        "npc":         npc_name,
        "relationship": rel,
        "tier":        int(tier_key),
        "opening":     _rand.choice(tier_data.get("opening", ["..."])),
        "responses":   tier_data.get("responses", []),
    }


@app.post("/api/npc/dialogue/respond")
async def respond_to_dialogue(
    save_id: int,
    npc_name: str,
    response_id: str,
    db: Session = Depends(get_db),
):
    """
    Register a dialogue response choice. Applies rel_delta to companion.
    Returns the NPC reply text.
    """
    import os, random as _rand
    save = _load_save_or_404(save_id, db)

    companion = next(
        (c for c in save.companions if c.name.lower() == npc_name.lower()),
        None
    )
    rel = companion.relationship_level if companion else 30

    # Load dialogue
    path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "npcs", "dialogue", f"{npc_name.lower()}.json"
    ))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"No dialogue for {npc_name}")

    with open(path, "r", encoding="utf-8") as f:
        dialogue = json.load(f)

    tiers = dialogue.get("tiers", {})
    valid_tiers = [int(k) for k in tiers.keys() if int(k) <= rel]
    if not valid_tiers:
        valid_tiers = [min(int(k) for k in tiers.keys())]
    tier_key = str(max(valid_tiers))
    tier_data = tiers[tier_key]

    # Find the chosen response
    chosen = next((r for r in tier_data.get("responses", []) if r["id"] == response_id), None)
    if not chosen:
        raise HTTPException(status_code=404, detail=f"Response '{response_id}' not found")

    # Apply rel_delta
    if companion:
        companion.relationship_level = max(0, min(100,
            companion.relationship_level + chosen.get("rel_delta", 0)
        ))
        db.commit()

    return {
        "response_id": response_id,
        "reply":       chosen.get("reply", ""),
        "rel_delta":   chosen.get("rel_delta", 0),
        "new_rel":     companion.relationship_level if companion else rel,
    }


@app.post("/api/time/advance")
async def advance_time(req: TimeAdvanceRequest, db: Session = Depends(get_db)):
    """
    Advance in-game time by req.hours, firing all passive ticks.
    Returns a summary of changes.
    """
    save = _load_save_or_404(req.save_id, db)
    champion = save.champion
    world = save.world

    # Advance clock — track if day rolled over for weather
    old_day = world.in_game_day
    world.in_game_hour += req.hours
    day_changed = False
    while world.in_game_hour >= 24.0:
        world.in_game_hour -= 24.0
        world.in_game_day += 1
        day_changed = True

    # Advance weather when day changes
    weather_result = None
    if day_changed:
        try:
            from weather import advance_weather
            weather_result = advance_weather(world)
        except Exception:
            pass

    # Recompute time-of-day band from new hour
    from db.models import TimeOfDay as _TOD
    h = world.in_game_hour
    if h < 6.0:
        world.time_of_day = _TOD.NIGHT
    elif h < 9.0:
        world.time_of_day = _TOD.DAWN
    elif h < 13.0:
        world.time_of_day = _TOD.MORNING
    elif h < 17.0:
        world.time_of_day = _TOD.MIDDAY
    elif h < 21.0:
        world.time_of_day = _TOD.EVENING
    else:
        world.time_of_day = _TOD.NIGHT

    # Passive ticks
    corruption_delta = passive_corruption_tick(champion, req.hours)
    submission_delta = passive_submission_tick(champion, req.hours)
    new_arousal = passive_arousal_tick(champion, req.hours)

    # HP restore — full restoration at 8h rest, partial heal otherwise
    old_hp = champion.current_hp
    if req.hours >= 8:
        champion.current_hp = champion.max_hp
    elif req.hours >= 1:
        heal = max(1, int(champion.max_hp * req.hours / 16))
        champion.current_hp = min(champion.max_hp, champion.current_hp + heal)
    hp_restored = champion.current_hp - old_hp

    # Dream trigger check — only fires on long rest (8+ hours)
    dream_triggered = None
    if req.hours >= 8:
        dream_triggered = _check_dream_trigger(save, db)

    # Gift trigger check — on any day change
    gift_triggered = None
    if day_changed:
        gift_triggered = _check_gift_trigger(save, db)

    # Kasyrra first encounter — Day 3, once only
    kasyrra_scene = None
    if day_changed:
        kasyrra_scene = _check_kasyrra_1_trigger(save, db)

    db.commit()

    return {
        "hours_elapsed":    req.hours,
        "day":              world.in_game_day,
        "hour":             round(world.in_game_hour, 2),
        "corruption_delta": round(corruption_delta, 3),
        "submission_delta": round(submission_delta, 3),
        "arousal":          new_arousal,
        "hp_restored":      hp_restored,
        "weather_changed":  weather_result.get("changed", False) if weather_result else False,
        "weather":          weather_result.get("new_weather", None) if weather_result else None,
        "dream":            dream_triggered,
        "gift":             gift_triggered,
        "kasyrra_scene":    kasyrra_scene,
        "champion":         _champion_dict(champion),
        "world":            _world_dict(world),
    }


@app.post("/api/corruption/apply")
async def apply_corruption_route(req: CorruptionRequest, db: Session = Depends(get_db)):
    """Apply a corruption delta to the champion and return the result."""
    save = _load_save_or_404(req.save_id, db)
    champion = save.champion

    delta = req.delta
    if req.apply_modifiers:
        delta = modified_corruption_gain(champion, delta)

    result = apply_corruption(champion, delta, source=req.source)
    db.commit()

    return {
        "old_corruption": result.old_corruption,
        "new_corruption": result.new_corruption,
        "delta_applied": result.corruption_delta,
        "stage_changed": result.stage_changed,
        "old_stage": result.old_stage,
        "new_stage": result.new_stage,
        "ponr_gates_triggered": result.ponr_gates_triggered,
        "champion": _champion_dict(champion),
    }


@app.post("/api/submission/event")
async def submission_event(req: SubmissionEventRequest, db: Session = Depends(get_db)):
    """Fire a submission event and return updated submission state."""
    save = _load_save_or_404(req.save_id, db)
    champion = save.champion

    result = update_submission(champion, req.event_id)

    # Check for attraction arc threshold crossings — log companion reaction events
    _check_attraction_reactions(save, db)

    db.commit()

    sheet = getattr(save, 'character_sheet', None)
    return {
        "event_id": result.event_id,
        "base_delta": result.base_delta,
        "applied_delta": round(result.applied_delta, 3),
        "old_score": result.old_score,
        "new_score": result.new_score,
        "multipliers": result.multipliers_applied,
        "champion": _champion_dict(champion),
        "attraction_current": sheet.attraction_current if sheet else None,
        "attraction_arc_score": sheet.attraction_arc_score if sheet else 0,
    }


# ---------------------------------------------------------------------------
# Combat
# ---------------------------------------------------------------------------

@app.post("/api/combat/resolve")
async def combat_resolve(req: CombatResolveRequest, db: Session = Depends(get_db)):
    """
    Resolve a combat encounter.

    Loads the encounter JSON, runs dice resolution against champion stats,
    applies corruption and submission consequences, commits, and returns the
    full result including encounter_data — the dict the frontend passes
    directly to /api/scene/stream.
    """
    from combat import load_encounter, resolve_combat

    save = _load_save_or_404(req.save_id, db)
    champion = save.champion

    try:
        encounter = load_encounter(req.encounter_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    result = resolve_combat(champion, encounter)
    db.commit()

    log_event(save, "combat", {
        "enemy":             result.enemy_display_name,
        "encounter_id":      result.encounter_id,
        "outcome":           result.outcome,
        "corruption_gained": round(result.corruption_gained, 2),
        "hp_lost":           result.hp_lost,
    }, db)
    update_reputation(save, result.encounter_id, result.outcome, db)
    db.commit()

    # Award XP based on outcome
    from leveling import XP_FROM_COMBAT_WIN, XP_FROM_COMBAT_LOSS
    xp_amount = XP_FROM_COMBAT_WIN if result.outcome == "win" else XP_FROM_COMBAT_LOSS
    xp_result = award_xp(champion, xp_amount, source=result.encounter_id)
    db.commit()

    return {
        "outcome":                   result.outcome,
        "outcome_tier":              result.outcome_tier,
        "encounter_id":              result.encounter_id,
        "enemy_display_name":        result.enemy_display_name,
        "champion_roll":             result.champion_roll,
        "effective_score":           result.effective_score,
        "enemy_difficulty":          result.enemy_difficulty,
        "margin":                    result.margin,
        "corruption_gained":         round(result.corruption_gained, 2),
        "submission_events":         result.submission_events,
        "stage_at_combat":           result.stage_at_combat,
        "kasyrra_mark_hesitation":   result.kasyrra_mark_hesitation,
        "hp_lost":                   result.hp_lost,
        "carried_to_safety":         result.carried_to_safety,
        "encounter_data":            result.as_encounter_data(),
        "champion":                  _champion_dict(champion),
        "xp_result":                 xp_result,
    }


# ---------------------------------------------------------------------------
# Scene streaming — SSE via local Ollama
# ---------------------------------------------------------------------------

@app.post("/api/scene/stream")
async def stream_scene_route(req: SceneRequest, db: Session = Depends(get_db)):
    """
    Stream an AI-generated scene via Server-Sent Events.
    Frontend reads token-by-token for typewriter rendering.
    """
    # Import here to avoid circular startup issues
    from ai.local_client import stream_scene
    from ai.context_builder import build_scene_context
    from ai.prompt_builder import build_encounter_prompt

    save = _load_save_or_404(req.save_id, db)

    # Build structured context for the local model
    context = build_scene_context(save, req.encounter_data.get("scene_type", ""))
    prompt = build_encounter_prompt(context, req.encounter_data)
    system_prompt = _load_system_prompt("system_base")

    # Optionally prepend a player-supplied style sample
    if req.style_sample and req.style_sample.strip():
        style_prefix = f"Match this writing style:\n{req.style_sample.strip()}\n\n"
        system_prompt = style_prefix + system_prompt

    # Cache for debug panel
    _last_ai_prompt[req.save_id] = prompt

    async def event_generator():
        try:
            async for token in stream_scene(prompt, system_prompt, save_id=req.save_id):
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/scene/generate")
async def generate_scene_route(req: SceneRequest, db: Session = Depends(get_db)):
    """
    One-shot scene generation (non-streaming).
    Returns the complete scene text in a single response.
    Use for NPC dialogue flavour or short event text where typewriter isn't needed.
    """
    from ai.local_client import generate_scene
    from ai.context_builder import build_scene_context
    from ai.prompt_builder import build_encounter_prompt

    save = _load_save_or_404(req.save_id, db)
    context = build_scene_context(save, req.encounter_data.get("scene_type", ""))
    prompt = build_encounter_prompt(context, req.encounter_data)
    system_prompt = _load_system_prompt("system_base")

    try:
        text = await generate_scene(prompt, system_prompt)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"scene_text": text}


# ---------------------------------------------------------------------------
# Inner monologue — short first-person thought block after a scene
# ---------------------------------------------------------------------------

@app.post("/api/scene/introspect")
async def introspect_scene(req: IntrospectRequest, db: Session = Depends(get_db)):
    """
    Generate a 100-150 word inner monologue from the champion's POV.
    Called by the frontend after each streamed scene completes.
    Returns the monologue as plain text, intended to be rendered in italics.
    """
    from ai.local_client import generate_scene
    from ai.context_builder import build_scene_context
    from ai.prompt_builder import build_introspection_prompt

    save = _load_save_or_404(req.save_id, db)
    context = build_scene_context(save, "encounter_loss")
    prompt = build_introspection_prompt(context, req.scene_text)
    system_prompt = _load_system_prompt("inner_monologue")

    try:
        text = await generate_scene(prompt, system_prompt,
                                    config_override={"num_predict": 600})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"monologue": text.strip()}


# ---------------------------------------------------------------------------
# Self-description — inventory SELF tab
# ---------------------------------------------------------------------------

@app.post("/api/scene/self_describe")
async def self_describe(req: SelfDescribeRequest, db: Session = Depends(get_db)):
    """
    Generate a 200-300 word self-examination passage for the inventory SELF tab.
    Includes physical description + emotional reaction to the champion's current state.
    """
    from ai.local_client import generate_scene
    from ai.context_builder import build_scene_context
    from ai.prompt_builder import build_self_description_prompt

    save = _load_save_or_404(req.save_id, db)
    context = build_scene_context(save)
    prompt = build_self_description_prompt(context)  # no scene_type needed, introspective
    system_prompt = _load_system_prompt("system_base")

    try:
        text = await generate_scene(prompt, system_prompt,
                                    config_override={"num_predict": 600})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"description": text.strip()}


# ---------------------------------------------------------------------------
# Debug think — returns Gemma's <think> block for the AI panel
# ---------------------------------------------------------------------------

@app.post("/api/scene/debug-think")
async def debug_think(req: DebugThinkRequest, db: Session = Depends(get_db)):
    """
    Run generation with think: True and return both the think block and main text.
    Used by the AI debugging panel when 'Show Gemma thinking' is enabled.
    """
    from ai.local_client import generate_with_think
    from ai.context_builder import build_scene_context
    from ai.prompt_builder import build_introspection_prompt

    save = _load_save_or_404(req.save_id, db)
    context = build_scene_context(save)
    prompt = build_introspection_prompt(context, req.scene_text)
    system_prompt = _load_system_prompt("system_base")

    try:
        text, think_block = await generate_with_think(prompt, system_prompt)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"text": text, "think_block": think_block}


@app.get("/api/debug/last-prompt")
async def debug_last_prompt(save_id: int):
    """Return the most recent AI prompt built for this save (in-process cache)."""
    prompt = _last_ai_prompt.get(save_id)
    if not prompt:
        return {"save_id": save_id, "prompt": None, "note": "No prompt cached yet for this save this session."}
    return {"save_id": save_id, "prompt": prompt}


@app.get("/api/debug/last-thinking/{save_id}")
async def debug_last_thinking(save_id: int):
    """Return the last extracted think block for this save (in-process cache)."""
    from ai.local_client import _last_thinking_block
    block = _last_thinking_block.get(save_id)
    if not block:
        return {
            "save_id": save_id,
            "think_block": None,
            "note": "Model did not think (thinking disabled or no think block captured yet).",
        }
    return {"save_id": save_id, "think_block": block}


def _load_system_prompt(prompt_name: str) -> str:
    """Load a system prompt template from disk."""
    import os
    path = os.path.join(os.path.dirname(__file__), "ai", "prompts", f"{prompt_name}.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are a skilled narrative author writing scenes for a dark fantasy text RPG."
