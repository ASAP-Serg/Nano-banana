"""Оценка стоимости генерации в USD.

Фактическое списание смотри в кабинете Moonez по job_id.
Если провайдер вернул cost — берём его; иначе оценка по модели/разрешению.
Pro 1K ≈ $0.03 (в кабинете Moonez среднее около $0.0335).
"""
from typing import Optional

MODEL_USD = {
    "nano-banana": 0.015,
    "nano-banana-2": 0.02,
    "nano-banana-pro": 0.03,
    "nano-banana-2-r8": 0.02,
    "nano-banana-r8": 0.015,
    "nano-banana-pro-r8": 0.03,
    "gemini-2.5-flash-image": 0.02,
    "imagen-4": 0.04,
    "imagen-4-fast": 0.02,
    "imagen-4-ultra": 0.06,
    "gpt-image-2": 0.08,
    "gpt-image-1-mini": 0.015,
    "gpt-5-image": 0.05,
    "gpt-5-image-mini": 0.02,
}

RESOLUTION_MULTIPLIER = {"1K": 1.0, "2K": 1.6, "4K": 2.5}
REF_FEE_USD = 0.002
MAX_REFS = 14


def estimate_cost_usd(
    *,
    model_name: Optional[str] = None,
    resolution: Optional[str] = None,
    reference_count: int = 0,
) -> float:
    model = (model_name or "nano-banana-pro").lower()
    res = (resolution or "1K").upper()
    price = MODEL_USD.get(model, 0.02)
    mult = RESOLUTION_MULTIPLIER.get(res, 1.0)
    refs = min(max(int(reference_count or 0), 0), MAX_REFS)
    return round(price * mult + refs * REF_FEE_USD, 6)
