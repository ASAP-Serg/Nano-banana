"""Оценка стоимости генерации в USD.

Если Moonez вернул price в job — на карточке факт, не эта оценка.
Цифры 1K ниже с кабинета Moonez 7 Oct 2026 (image-to-image, 1:1):
Banana 2 = $0.03350, Pro = $0.06780, Banana 2.5 = $0.10000.
Референсы в оценке Moonez не плюсуем — они уже в цене job.
"""
from typing import Optional

MODEL_USD = {
    "nano-banana": 0.10,
    "nano-banana-2": 0.0335,
    "nano-banana-2-lite": 0.02,
    "nano-banana-2.1": 0.0084,
    "nano-banana-pro": 0.0678,
    "nano-banana-2-r8": 0.02,
    "nano-banana-r8": 0.015,
    "nano-banana-pro-r8": 0.03,
    "gemini-2.5-flash-image": 0.10,
    "gemini-3.1-flash-image": 0.0335,
    "gemini-3.1-flash-lite-image": 0.02,
    "gemini-nano-banana-2.1": 0.0084,
    "gemini-3-pro-image": 0.0678,
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

# OpenRouter chat (prompt rewrite/enhance). USD per 1M tokens.
# Fallback estimate when response has no native `usage.cost`.
OPENROUTER_CHAT_USD_PER_1M = {
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "openai/gpt-4o": {"input": 2.50, "output": 10.0},
    "openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "google/gemini-2.0-flash-001": {"input": 0.10, "output": 0.40},
    "google/gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}


def estimate_openrouter_chat_cost_usd(
    *,
    model: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> float:
    rates = OPENROUTER_CHAT_USD_PER_1M.get(
        (model or "").strip(),
        OPENROUTER_CHAT_USD_PER_1M["openai/gpt-4o-mini"],
    )
    inp = max(int(prompt_tokens or 0), 0)
    out = max(int(completion_tokens or 0), 0)
    return round((inp * rates["input"] + out * rates["output"]) / 1_000_000.0, 8)


def extract_openrouter_chat_cost_usd(body: Optional[dict], model: Optional[str] = None) -> Optional[float]:
    """Prefer OpenRouter native usage.cost; else estimate from tokens."""
    if not isinstance(body, dict):
        return None
    usage = body.get("usage")
    if isinstance(usage, dict):
        for key in ("cost", "total_cost", "cost_usd"):
            raw = usage.get(key)
            if raw is not None:
                try:
                    amount = float(raw)
                    if amount >= 0:
                        return round(amount, 8)
                except (TypeError, ValueError):
                    pass
        try:
            prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        except (TypeError, ValueError):
            prompt_tokens = completion_tokens = 0
        if prompt_tokens or completion_tokens:
            return estimate_openrouter_chat_cost_usd(
                model=model or body.get("model"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
    return None


def _moonez_bills_flat_job(model: str) -> bool:
    if model.endswith("-r8"):
        return False
    if model.startswith("nano-banana"):
        return True
    return model.startswith("gemini-") and "image" in model


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
    refs_fee = 0.0 if _moonez_bills_flat_job(model) else refs * REF_FEE_USD
    return round(price * mult + refs_fee, 6)
