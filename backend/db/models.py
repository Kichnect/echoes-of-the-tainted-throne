"""
SQLAlchemy models for Echoes of the Tainted Throne.
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, Float, String, Boolean,
    DateTime, ForeignKey, Text, JSON, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session
import enum

DATABASE_URL = "sqlite:///./db/game.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ColorPath(str, enum.Enum):
    VIOLET  = "violet"
    CRIMSON = "crimson"
    TEAL    = "teal"
    ROSE    = "rose"
    AMBER   = "amber"
    GREY    = "grey"
    IVORY   = "ivory"


class TransformationStage(int, enum.Enum):
    HUMAN          = 0   # 0–20%
    VULPINE_TOUCHED = 1  # 20–45%
    FULL_VULPINE   = 2   # 45–65%
    KOBOLD_VULPINE = 3   # 65–85%
    DRACONIC_FINAL = 4   # 85–100%


class TimeOfDay(str, enum.Enum):
    DAWN    = "dawn"
    MORNING = "morning"
    MIDDAY  = "midday"
    EVENING = "evening"
    NIGHT   = "night"


class Weather(str, enum.Enum):
    CLEAR    = "clear"
    OVERCAST = "overcast"
    RAIN     = "rain"
    FOG      = "fog"
    STORM    = "storm"


# ---------------------------------------------------------------------------
# SaveGame (top-level save slot)
# ---------------------------------------------------------------------------

class SaveGame(Base):
    __tablename__ = "save_games"

    id          = Column(Integer, primary_key=True, index=True)
    slot_name   = Column(String(64), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    story_flags = Column(JSON, default=dict)

    champion       = relationship("Champion",  back_populates="save", uselist=False, cascade="all, delete-orphan")
    world          = relationship("WorldState", back_populates="save", uselist=False, cascade="all, delete-orphan")
    kasyrra        = relationship("KasyrraState", back_populates="save", uselist=False, cascade="all, delete-orphan")
    companions     = relationship("Companion", back_populates="save", cascade="all, delete-orphan")
    character_sheet = relationship("CharacterSheet", back_populates="save", uselist=False, cascade="all, delete-orphan")
    reputation     = relationship("FactionReputation", back_populates="save", uselist=False, cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Champion
# ---------------------------------------------------------------------------

class Champion(Base):
    __tablename__ = "champions"

    id      = Column(Integer, primary_key=True, index=True)
    save_id = Column(Integer, ForeignKey("save_games.id"), nullable=False)
    name    = Column(String(64), nullable=False)

    # Core stats
    corruption       = Column(Float, default=0.0)    # 0–100
    essence          = Column(Integer, default=100)
    resolve          = Column(Integer, default=10)
    grace            = Column(Integer, default=10)
    force            = Column(Integer, default=10)
    presence         = Column(Integer, default=10)

    # Derived / tracked scores
    submission_score = Column(Float, default=0.0)   # 0–100
    arousal          = Column(Integer, default=0)   # 0–100
    color_path       = Column(SAEnum(ColorPath), default=ColorPath.GREY)

    # Transformation
    stage            = Column(Integer, default=0)   # TransformationStage value
    height_offset_in = Column(Float, default=0.0)   # inches lost from baseline

    # Background
    background       = Column(String(32), default="warrior")

    # PONR locks — once True, that threshold cannot be reversed
    ponr_1_locked = Column(Boolean, default=False)  # 20%
    ponr_2_locked = Column(Boolean, default=False)  # 45%
    ponr_3_locked = Column(Boolean, default=False)  # 65%
    ponr_4_locked = Column(Boolean, default=False)  # 85%

    # Color path accumulator scores (raw, not normalized)
    cp_kasyrra_submission       = Column(Float, default=0.0)
    cp_kasyrra_encounters_aligned = Column(Integer, default=0)
    cp_kasyrra_encounters_total   = Column(Integer, default=0)
    cp_kasyrra_dialogue_chosen    = Column(Integer, default=0)
    cp_combat_wins_high_corruption = Column(Integer, default=0)
    cp_resistance_actions         = Column(Integer, default=0)
    cp_ponr_delays                = Column(Integer, default=0)
    cp_purification_uses          = Column(Integer, default=0)
    cp_submission_events          = Column(Float, default=0.0)
    cp_feminization_events        = Column(Integer, default=0)
    cp_cursed_item_days           = Column(Float, default=0.0)
    cp_companion_protection_events = Column(Integer, default=0)

    # Health
    current_hp = Column(Integer, default=90)
    max_hp     = Column(Integer, default=90)

    # Status effect flags (booleans — see StatusEffect table for full state)
    chastity_locked = Column(Boolean, default=False)

    # Character creation fields (Wave 1)
    sin                  = Column(String(32), default="pride")      # pride/lust/sloth/wrath/envy/greed/gluttony
    tone_preference      = Column(String(32), default="conflict")   # dread/conflict/relief
    gender               = Column(String(16), default="male")       # male/female/other
    hair_color           = Column(String(32), default="brown")
    eye_color            = Column(String(32), default="brown")
    build                = Column(String(16), default="average")    # lean/average/broad
    prologue_done        = Column(Boolean, default=False)

    # Height system
    height_cm_base       = Column(Float, default=175.0)  # set at character creation

    # Misc flags
    kasyrra_mark_applied = Column(Boolean, default=False)
    opening_scene_done   = Column(Boolean, default=False)

    # Equipment (Item 4)
    equipment_slots = Column(JSON, default=dict)

    # Level / XP (Item 5)
    experience = Column(Integer, default=0)
    level      = Column(Integer, default=1)

    save       = relationship("SaveGame", back_populates="champion")
    statuses   = relationship("ActiveStatus", back_populates="champion", cascade="all, delete-orphan")
    event_log  = relationship("EventLogEntry", back_populates="champion", cascade="all, delete-orphan")

    @property
    def height_cm(self) -> float:
        """Current height in cm: base minus stage-based reduction."""
        stage_loss = {0: 0, 1: 2, 2: 8, 3: 18, 4: 32}.get(self.stage or 0, 0)
        return round((self.height_cm_base or 175.0) - stage_loss, 1)

    @property
    def stage_name(self) -> str:
        names = {
            0: "Human",
            1: "Vulpine-Touched",
            2: "Full Vulpine",
            3: "Kobold-Vulpine Hybrid",
            4: "Draconic Final Form",
        }
        return names.get(self.stage, "Unknown")

    @property
    def stage_description_brief(self) -> str:
        descriptions = {
            0: "No visible changes.",
            1: "Fox ears, tail, amber eyes — first tells.",
            2: "Fur coverage spread, frame softening, feminization visible.",
            3: "Shrinking, scales emerging, kobold-vulpine hybrid — striking and fragile.",
            4: "Full draconic form — feminine, hypersensitive, maximally beautiful.",
        }
        return descriptions.get(self.stage, "")

    @property
    def cursed_items(self) -> list[str]:
        return [s.effect_id for s in self.statuses if s.is_cursed_item and s.is_active]

    @property
    def active_toys(self) -> list[str]:
        return [s.effect_id for s in self.statuses if s.is_toy and s.is_active]

    def has_status(self, effect_id: str) -> bool:
        return any(s.effect_id == effect_id and s.is_active for s in self.statuses)

    @property
    def feminization(self) -> int:
        """
        Feminization percentage (0–100).
        Rises with transformation stage; cursed items add a bonus.
        """
        stage_base = {0: 0, 1: 20, 2: 45, 3: 70, 4: 95}.get(self.stage, 0)
        bonus = 0
        if self.has_status("cursed_harem_clothes"):
            bonus += 8
        if self.has_status("cursed_plug"):
            bonus += 3
        if self.chastity_locked:
            bonus += 5
        return min(100, stage_base + bonus)

    def physical_description_current(self) -> str:
        """Short prose description of current physical state for AI context."""
        base = f"Stage {self.stage} ({self.stage_name})."
        if self.height_offset_in < 0:
            base += f" {abs(self.height_offset_in):.0f}\" shorter than baseline."
        if self.chastity_locked:
            base += " Chastity device locked."
        if self.has_status("cursed_harem_clothes"):
            base += " Wearing cursed harem attire."
        if self.has_status("cursed_plug"):
            base += " Binding plug active."
        return base


# ---------------------------------------------------------------------------
# Active Status Effects
# ---------------------------------------------------------------------------

class ActiveStatus(Base):
    __tablename__ = "active_statuses"

    id           = Column(Integer, primary_key=True, index=True)
    champion_id  = Column(Integer, ForeignKey("champions.id"), nullable=False)
    effect_id    = Column(String(64), nullable=False)   # matches StatusEffect.id
    display_name = Column(String(128))
    is_active    = Column(Boolean, default=True)
    is_cursed_item = Column(Boolean, default=False)
    is_toy         = Column(Boolean, default=False)
    duration_remaining = Column(Integer, nullable=True)   # None = permanent
    applied_at   = Column(DateTime, default=datetime.utcnow)

    champion = relationship("Champion", back_populates="statuses")


# ---------------------------------------------------------------------------
# Companions
# ---------------------------------------------------------------------------

class Companion(Base):
    __tablename__ = "companions"

    id           = Column(Integer, primary_key=True, index=True)
    save_id      = Column(Integer, ForeignKey("save_games.id"), nullable=False)
    name         = Column(String(64), nullable=False)   # Saoirse, Mireille, Tierlan
    relationship_level = Column(Integer, default=0)    # 0–100
    is_present   = Column(Boolean, default=True)
    notes        = Column(JSON, default=list)           # Mireille's research notes

    # Companion-specific flags
    flags        = Column(JSON, default=dict)

    save = relationship("SaveGame", back_populates="companions")


# ---------------------------------------------------------------------------
# World State
# ---------------------------------------------------------------------------

class WorldState(Base):
    __tablename__ = "world_states"

    id          = Column(Integer, primary_key=True, index=True)
    save_id     = Column(Integer, ForeignKey("save_games.id"), nullable=False)
    region      = Column(String(64), default="Wolf-Road Edge")
    time_of_day = Column(SAEnum(TimeOfDay), default=TimeOfDay.MORNING)
    weather     = Column(SAEnum(Weather), default=Weather.CLEAR)
    supplies    = Column(Integer, default=10)     # days of rations
    morale      = Column(Integer, default=70)     # 0–100
    in_game_day = Column(Integer, default=1)
    in_game_hour = Column(Float, default=8.0)     # 0–24

    # Travel / Map Progression (Item 3)
    travel_destination  = Column(String(64), nullable=True)
    travel_progress     = Column(Integer, default=0)    # steps taken (0–10)
    travel_steps_total  = Column(Integer, default=10)   # steps needed to arrive

    # Weather system (Wave 5)
    weather_days_remaining = Column(Integer, default=2)   # days until next weather change

    save = relationship("SaveGame", back_populates="world")


# ---------------------------------------------------------------------------
# Kasyrra State
# ---------------------------------------------------------------------------

class KasyrraState(Base):
    __tablename__ = "kasyrra_states"

    id              = Column(Integer, primary_key=True, index=True)
    save_id         = Column(Integer, ForeignKey("save_games.id"), nullable=False)
    virility_stage  = Column(Integer, default=0)   # 0–5
    encounter_count = Column(Integer, default=0)
    last_encounter_summary = Column(Text, default="")
    alignment_score = Column(Float, default=0.0)   # drives Violet/Amber paths

    save = relationship("SaveGame", back_populates="kasyrra")


# ---------------------------------------------------------------------------
# Event Log (used for color path accumulation + AI context)
# ---------------------------------------------------------------------------

class EventLogEntry(Base):
    __tablename__ = "event_log"

    id          = Column(Integer, primary_key=True, index=True)
    champion_id = Column(Integer, ForeignKey("champions.id"), nullable=False)
    event_id    = Column(String(128), nullable=False)
    event_data  = Column(JSON, default=dict)
    occurred_at = Column(DateTime, default=datetime.utcnow)

    champion = relationship("Champion", back_populates="event_log")


# ---------------------------------------------------------------------------
# Character Sheet
# ---------------------------------------------------------------------------

class CharacterSheet(Base):
    __tablename__ = "character_sheets"

    id                      = Column(Integer, primary_key=True, index=True)
    save_id                 = Column(Integer, ForeignKey("save_games.id"), nullable=False, unique=True)
    race                    = Column(String(64), default="Human")
    height_cm               = Column(Float, default=178.0)
    gender_presentation     = Column(String(64), default="masculine")
    gender_attraction       = Column(String(64), default="female-leaning")
    body_desc_chest         = Column(Text, default="")
    body_desc_hips          = Column(Text, default="")
    body_desc_face          = Column(Text, default="angular, strong jaw, amber-brown eyes")
    body_desc_skin          = Column(Text, default="tanned, weathered — a soldier's skin")
    body_desc_tail          = Column(Text, default="none")
    body_desc_ears          = Column(Text, default="normal human")
    scent                   = Column(Text, default="sweat, steel, leather")
    voice_desc              = Column(Text, default="low, authoritative")
    corruption_visible_signs = Column(Text, default="none yet")
    attraction_current      = Column(String(64), default="female-leaning")
    attraction_arc_score    = Column(Integer, default=0)

    save = relationship("SaveGame", back_populates="character_sheet")


# ---------------------------------------------------------------------------
# Faction Reputation
# ---------------------------------------------------------------------------

class FactionReputation(Base):
    __tablename__ = "faction_reputations"

    id                 = Column(Integer, primary_key=True, index=True)
    save_id            = Column(Integer, ForeignKey("save_games.id"), nullable=False, unique=True)
    warden_order       = Column(Integer, default=0)
    free_lupines       = Column(Integer, default=50)
    kitsune_wanderers  = Column(Integer, default=50)
    kasyrra_cult       = Column(Integer, default=0)
    settlements        = Column(Integer, default=50)

    save = relationship("SaveGame", back_populates="reputation")


# ---------------------------------------------------------------------------
# DB init helper
# ---------------------------------------------------------------------------

def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_db()


def _migrate_db():
    """
    Add columns that may be missing from pre-existing databases.
    SQLite ALTER TABLE ADD COLUMN is safe to repeat — we swallow
    the OperationalError that fires when the column already exists.
    """
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE champions ADD COLUMN current_hp INTEGER DEFAULT 90",
        "ALTER TABLE champions ADD COLUMN max_hp     INTEGER DEFAULT 90",
        "ALTER TABLE save_games ADD COLUMN story_flags JSON DEFAULT '{}'",
        "ALTER TABLE champions ADD COLUMN background TEXT DEFAULT 'warrior'",
        # New tables - use CREATE TABLE IF NOT EXISTS
        """CREATE TABLE IF NOT EXISTS character_sheets (
    id INTEGER PRIMARY KEY,
    save_id INTEGER UNIQUE NOT NULL REFERENCES save_games(id),
    race TEXT DEFAULT 'Human',
    height_cm REAL DEFAULT 178.0,
    gender_presentation TEXT DEFAULT 'masculine',
    gender_attraction TEXT DEFAULT 'female-leaning',
    body_desc_chest TEXT DEFAULT '',
    body_desc_hips TEXT DEFAULT '',
    body_desc_face TEXT DEFAULT 'angular, strong jaw, amber-brown eyes',
    body_desc_skin TEXT DEFAULT 'tanned, weathered — a soldier''s skin',
    body_desc_tail TEXT DEFAULT 'none',
    body_desc_ears TEXT DEFAULT 'normal human',
    scent TEXT DEFAULT 'sweat, steel, leather',
    voice_desc TEXT DEFAULT 'low, authoritative',
    corruption_visible_signs TEXT DEFAULT 'none yet',
    attraction_current TEXT DEFAULT 'female-leaning',
    attraction_arc_score INTEGER DEFAULT 0
)""",
        """CREATE TABLE IF NOT EXISTS faction_reputations (
    id INTEGER PRIMARY KEY,
    save_id INTEGER UNIQUE NOT NULL REFERENCES save_games(id),
    warden_order INTEGER DEFAULT 0,
    free_lupines INTEGER DEFAULT 50,
    kitsune_wanderers INTEGER DEFAULT 50,
    kasyrra_cult INTEGER DEFAULT 0,
    settlements INTEGER DEFAULT 50
)""",
        # Item 3 — Map / Travel Progression
        "ALTER TABLE world_states ADD COLUMN travel_destination TEXT",
        "ALTER TABLE world_states ADD COLUMN travel_progress INTEGER DEFAULT 0",
        "ALTER TABLE world_states ADD COLUMN travel_steps_total INTEGER DEFAULT 10",
        # Item 4 — Equipment System
        "ALTER TABLE champions ADD COLUMN equipment_slots JSON DEFAULT '{}'",
        # Item 5 — Level / XP System
        "ALTER TABLE champions ADD COLUMN experience INTEGER DEFAULT 0",
        "ALTER TABLE champions ADD COLUMN level INTEGER DEFAULT 1",
        # Wave 1 — Character Creation Expansion
        "ALTER TABLE champions ADD COLUMN sin TEXT DEFAULT 'pride'",
        "ALTER TABLE champions ADD COLUMN tone_preference TEXT DEFAULT 'conflict'",
        "ALTER TABLE champions ADD COLUMN gender TEXT DEFAULT 'male'",
        "ALTER TABLE champions ADD COLUMN hair_color TEXT DEFAULT 'brown'",
        "ALTER TABLE champions ADD COLUMN eye_color TEXT DEFAULT 'brown'",
        "ALTER TABLE champions ADD COLUMN build TEXT DEFAULT 'average'",
        "ALTER TABLE champions ADD COLUMN prologue_done INTEGER DEFAULT 0",
        # Wave 5 — Weather System
        "ALTER TABLE world_states ADD COLUMN weather_days_remaining INTEGER DEFAULT 2",
        # Fix 6 — Height system
        "ALTER TABLE champions ADD COLUMN height_cm_base REAL DEFAULT 175.0",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass   # column already exists or table already created


def get_session() -> Session:
    return Session(engine)
