"""
Quick smoke-test for the Ollama integration.
Builds a minimal encounter context and calls generate_scene(), printing the result.

Run from the backend/ directory:
    python test_ollama.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Ensure backend/ is on the path when run from project root
sys.path.insert(0, str(Path(__file__).parent))

from ai.local_client import generate_scene, check_ollama_health, load_model_config

# ---------------------------------------------------------------------------
# Minimal hardcoded context — no DB needed
# ---------------------------------------------------------------------------

CONTEXT = """\
=== CHAMPION ===
Name: Aelindra
Corruption: 32.0%
Transformation Stage: 1 — Vulpine-Touched
  Fox ears, full tail, amber eyes, fur patches — clearly changed.

Physical State:
  Stage 1 (Vulpine-Touched). No cursed items. No toys.

Arousal: 18/100
Submission Score: 24.0/100  (not shown to player — for narrative calibration only)
Stat Penalties: Within normal range

Body Modifiers:
  Chastity Device Locked: False
  Cursed Items: None
  Active Toys/Plugs: None

Active Status Effects:
  None

Kasyrra's Mark: Not yet applied

=== COMPANIONS ===
Saoirse (relationship 35/100):
  Current dynamic: Noticeably more watchful. Hasn't said anything yet.
Mireille (relationship 35/100):
  Current dynamic: Taking notes on the physical changes. Clinical, but not unkind.
Tierlan (relationship 35/100):
  Current dynamic: Jokes about the ears. Actually comfortable with it.

=== WORLD STATE ===
Region: Wolf-Road Edge
Time: evening, Day 3
Weather: overcast
Supplies: 8 days remaining
Party Morale: 62/100

=== KASYRRA ===
Virility Stage: 0/5
Current State: Has not yet revealed the full scope of her intent.
Kasyrra-Champion Alignment Score: 0.0
Last Encounter: No prior encounter.

=== ENCOUNTER ===
Scene Type: encounter_loss
Enemy/NPC: Corrupted Wolf Scout
Combat Result: loss
Corruption Gained This Event: 4.0%
Submission Events Triggered:
  - combat_loss_penetrated
Additional Notes: Late evening on the road. Companions are a short distance behind."""

DIRECTIVE = """\
Write a combat loss scene.

The Champion lost to a corrupted wolf scout on the Wolf-Road at dusk. \
The companions are close but not close enough. Submission score is low — \
the Champion's resistance is strong and present throughout. \
400–500 words."""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    # Health check
    healthy, msg = await check_ollama_health()
    cfg = load_model_config()
    print(f"Model : {cfg['model']}")
    print(f"Ollama: {msg}")
    print()

    if not healthy:
        print("Aborting — Ollama not reachable.")
        return

    system_path = Path(__file__).parent / "ai" / "prompts" / "system_base.txt"
    system_prompt = system_path.read_text(encoding="utf-8")

    full_prompt = f"{CONTEXT}\n\n{DIRECTIVE}"

    print("--- Generating scene... ---\n")
    t0 = time.perf_counter()
    result = await generate_scene(full_prompt, system_prompt)
    elapsed = time.perf_counter() - t0

    print(result)
    print(f"\n--- Done in {elapsed:.1f}s ---")


if __name__ == "__main__":
    asyncio.run(main())
