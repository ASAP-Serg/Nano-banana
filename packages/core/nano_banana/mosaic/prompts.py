"""Промпты мозаики: текст из конфигов, правка только админом (таблица mosaic_prompts)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from nano_banana.providers.models import moonez_slug

_CONFIG_DIR = Path(__file__).resolve().parent / "configs"
MODES = ("direct", "combo")
VARIANTS = ("default", "3_pro", "2.5_flash", "3.1_flash")


def variant_for_model(model_name: Optional[str]) -> Optional[str]:
    """Суффикс ключа prompt:* как в конфигах мозаики. Неизвестная модель → None (дальше default)."""
    mid = (model_name or "").strip().lower()
    slug = (moonez_slug(mid) or "").lower()
    if mid in {"nano-banana-pro", "nano-banana-pro-r8"} or "3-pro" in slug or "3-pro" in mid:
        return "3_pro"
    if mid in {"nano-banana-2", "nano-banana-2-r8"} or "3.1" in slug or "3.1" in mid:
        return "3.1_flash"
    if mid in {"nano-banana", "nano-banana-r8", "gemini-2.5-flash-image"} or "2.5" in slug or "2.5" in mid:
        return "2.5_flash"
    return None


@lru_cache(maxsize=4)
def _file_prompts(mode: str) -> Dict[str, str]:
    path = _CONFIG_DIR / f"{mode}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    gemini = (raw.get("parameters") or [{}])[0].get("gemini") or {}
    out: Dict[str, str] = {}
    for key, value in gemini.items():
        if not isinstance(value, str):
            continue
        if key == "prompt":
            out["prompt"] = value
        elif key.startswith("prompt:"):
            out[key.split(":", 1)[1]] = value
    return out


def bundled_prompts(mode: str) -> Dict[str, str]:
    if mode not in MODES:
        raise ValueError("Неизвестный режим мозаики")
    return dict(_file_prompts(mode))


def resolve_mosaic_prompt(mode: str, model_name: Optional[str], overrides: Optional[Dict[str, str]] = None) -> tuple[str, str]:
    """Как в ТЗ: prompt:{variant} → prompt:default → prompt. overrides: variant → текст админа."""
    prompts = bundled_prompts(mode)
    if overrides:
        for variant, text in overrides.items():
            if text and str(text).strip():
                prompts[variant] = str(text).strip()
    variant = variant_for_model(model_name)
    if variant and prompts.get(variant):
        return prompts[variant], variant
    if prompts.get("default"):
        return prompts["default"], "default"
    if prompts.get("prompt"):
        return prompts["prompt"], "prompt"
    raise ValueError("В конфиге мозаики нет промпта для этого режима")


def list_prompt_slots() -> List[dict]:
    rows = []
    for mode in MODES:
        for variant in VARIANTS:
            base = bundled_prompts(mode).get(variant)
            if not base:
                continue
            rows.append({"mode": mode, "variant": variant, "body": base})
    return rows
