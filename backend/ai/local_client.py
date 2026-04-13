"""
Ollama wrapper for Echoes of the Tainted Throne.

Provides both a one-shot generate_scene() and a streaming stream_scene()
that yields tokens for SSE delivery to the frontend's typewriter renderer.

Model config is read from models/model_config.json at the project root.
All game logic lives in the engine — this file only moves text.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncGenerator

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OLLAMA_BASE = "http://localhost:11434"

_DEFAULT_CONFIG = {
    "model": "gemma3:12b",
    "temperature": 0.85,
    "top_p": 0.92,
    "repeat_penalty": 1.1,
    "num_predict": 800,
}


def load_model_config() -> dict:
    """
    Load model config from models/model_config.json relative to the project root.
    Falls back to defaults if the file is missing.
    """
    # backend/ai/local_client.py → project root is two levels up
    root = Path(__file__).resolve().parents[2]
    config_path = root / "models" / "model_config.json"

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**_DEFAULT_CONFIG, **data}

    return _DEFAULT_CONFIG.copy()


# ---------------------------------------------------------------------------
# Ollama health check
# ---------------------------------------------------------------------------

async def check_ollama_health() -> tuple[bool, str]:
    """
    Returns (is_healthy, message).
    Called at startup and before streaming to give a clear error if Ollama
    isn't running rather than a confusing timeout.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                return True, f"Ollama running. Available models: {', '.join(models) or 'none pulled yet'}"
            return False, f"Ollama responded with status {r.status_code}"
    except httpx.ConnectError:
        return False, "Ollama not reachable at localhost:11434. Run: ollama serve"
    except Exception as exc:
        return False, f"Ollama check failed: {exc}"


# ---------------------------------------------------------------------------
# One-shot generation (non-streaming)
# ---------------------------------------------------------------------------

async def generate_scene(
    prompt: str,
    system: str,
    config_override: dict | None = None,
) -> str:
    """
    Call Ollama synchronously and return the complete response string.
    Used for non-streaming calls (e.g., short NPC dialogue flavour).
    """
    cfg = load_model_config()
    if config_override:
        cfg.update(config_override)

    payload = {
        "model":      cfg["model"],
        "prompt":     prompt,
        "system":     system,
        "stream":     False,
        "keep_alive": cfg.get("keep_alive", "15m"),
        "options": {
            "temperature": cfg["temperature"],
            "top_k":       cfg.get("top_k", 64),
            "top_p":       cfg["top_p"],
            "num_predict": cfg["num_predict"],
            "num_thread":  cfg.get("num_thread", 8),
            "num_gpu":     cfg.get("num_gpu", 1),
            "think":       False,
        },
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(f"{OLLAMA_BASE}/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["response"].encode("utf-8", errors="replace").decode("utf-8")


# ---------------------------------------------------------------------------
# Streaming generation (SSE)
# ---------------------------------------------------------------------------

async def stream_scene(
    prompt: str,
    system: str,
    config_override: dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream tokens from Ollama for typewriter rendering.
    Yields individual token strings; caller wraps them in SSE frames.

    Raises OllamaUnavailableError if Ollama isn't running, so the caller
    can surface a clean error to the frontend instead of a raw timeout.
    """
    cfg = load_model_config()
    if config_override:
        cfg.update(config_override)

    payload = {
        "model":      cfg["model"],
        "prompt":     prompt,
        "system":     system,
        "stream":     True,
        "keep_alive": cfg.get("keep_alive", "15m"),
        "options": {
            "temperature": cfg["temperature"],
            "top_k":       cfg.get("top_k", 64),
            "top_p":       cfg["top_p"],
            "num_predict": cfg["num_predict"],
            "num_thread":  cfg.get("num_thread", 8),
            "num_gpu":     cfg.get("num_gpu", 1),
            "think":       False,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE}/api/generate",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("done"):
                        break
                    token = chunk.get("response", "")
                    if token:
                        yield token

    except httpx.ConnectError as exc:
        raise OllamaUnavailableError(
            "Ollama not reachable at localhost:11434. Start it with: ollama serve"
        ) from exc


# ---------------------------------------------------------------------------
# Generation with thinking mode enabled
# ---------------------------------------------------------------------------

def _split_think(text: str) -> tuple[str, str]:
    """
    Split a Gemma response that may contain a <think>...</think> block.
    Returns (think_content, main_text).
    If no think block is present, returns ("", text).
    """
    import re
    m = re.search(r'<think>([\s\S]*?)</think>', text)
    if m:
        return m.group(1).strip(), text[m.end():].strip()
    return "", text.strip()


async def generate_with_think(
    prompt: str,
    system: str,
    config_override: dict | None = None,
) -> tuple[str, str]:
    """
    Like generate_scene(), but enables Gemma's thinking mode.
    Returns (main_text, think_block).
    The think block is empty if the model produces none.
    """
    cfg = load_model_config()
    if config_override:
        cfg.update(config_override)

    payload = {
        "model":      cfg["model"],
        "prompt":     prompt,
        "system":     system,
        "stream":     False,
        "keep_alive": cfg.get("keep_alive", "15m"),
        "options": {
            "temperature": cfg["temperature"],
            "top_k":       cfg.get("top_k", 64),
            "top_p":       cfg["top_p"],
            "num_predict": cfg.get("num_predict", 800) + 400,  # extra budget for think block
            "num_thread":  cfg.get("num_thread", 8),
            "num_gpu":     cfg.get("num_gpu", 1),
            "think":       True,
        },
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(f"{OLLAMA_BASE}/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
        raw = data["response"].encode("utf-8", errors="replace").decode("utf-8")

    think_block, main_text = _split_think(raw)
    return main_text, think_block


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class OllamaUnavailableError(RuntimeError):
    """Raised when the Ollama process is not running or unreachable."""
