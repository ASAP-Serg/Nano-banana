"""
Схемы данных для Nano Banana Pro API
"""
import re
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime

MAX_PROMPT_LENGTH = 4000
MAX_NEGATIVE_PROMPT_LENGTH = 2000
MAX_REFERENCE_IMAGES = 4
MAX_MODEL_NAME_LENGTH = 64
ALLOWED_RESOLUTIONS = frozenset({"1K", "2K", "4K"})
ALLOWED_ASPECT_RATIOS = frozenset({"1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "5:4", "2:3"})
ALLOWED_GENERATION_MODES = frozenset({"text-to-image", "image-to-image"})

_USERNAME_RE = re.compile(r"^[\w.-]{3,32}$", re.UNICODE)


def normalize_username(value: str) -> str:
    name = (value or "").strip()
    if (
        not _USERNAME_RE.fullmatch(name)
        or name[0] in ".-_"
        or name[-1] in ".-"
        or "<" in name
        or ">" in name
    ):
        raise ValueError("Имя: 3–32 символа, буквы и цифры, внутри можно . _ -")
    return name


# Аутентификация
class UserCreateRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return normalize_username(v)
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError('Пароль должен быть не менее 10 символов')
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Пароль слишком длинный (максимум 72 байта)')
        return v

class UserLoginRequest(BaseModel):
    username_or_email: str
    password: str
    totp_code: Optional[str] = None

    @field_validator("totp_code")
    @classmethod
    def validate_login_totp(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        if not digits:
            return None
        if len(digits) != 6:
            raise ValueError("Код: 6 цифр")
        return digits

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    is_admin: bool
    totp_enabled: bool = False
    created_at: datetime
    
    class Config:
        from_attributes = True

class AdminPasswordRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def validate_admin_password(cls, v: str) -> str:
        text = (v or "").strip()
        if len(text) < 10:
            raise ValueError("Нужен ваш пароль")
        return text


class TotpConfirmRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def validate_totp_code(cls, v: str) -> str:
        digits = "".join(ch for ch in (v or "") if ch.isdigit())
        if len(digits) != 6:
            raise ValueError("Код: 6 цифр")
        return digits


class ReplicateApiKeyRequest(BaseModel):
    api_key: str
    provider: Optional[str] = None

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        key = (v or "").strip()
        if not key or len(key) > 512:
            raise ValueError("Некорректный API ключ")
        return key

class ReplicateApiKeyResponse(BaseModel):
    message: str
    has_key: bool
    has_replicate_key: Optional[bool] = None
    has_bananalab_key: Optional[bool] = None
    has_openrouter_key: Optional[bool] = None
    selected_provider: Optional[str] = None

# Генерация изображений
class ImageGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt: str
    negative_prompt: Optional[str] = None
    generation_mode: str = "text-to-image"
    resolution: str = "1K"
    aspect_ratio: str = "1:1"
    guidance_scale: float = 7.5
    num_inference_steps: int = 50
    seed: Optional[int] = None
    reference_images: Optional[List[str]] = None
    model_name: Optional[str] = None
    rewrite_prompt: Optional[bool] = False

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("Нужно описание")
        if len(text) > MAX_PROMPT_LENGTH:
            raise ValueError(f"Описание слишком длинное (максимум {MAX_PROMPT_LENGTH} символов)")
        return text

    @field_validator("negative_prompt")
    @classmethod
    def validate_negative(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        text = v.strip()
        if not text:
            return None
        if len(text) > MAX_NEGATIVE_PROMPT_LENGTH:
            raise ValueError(
                f"Негативный промпт слишком длинный (максимум {MAX_NEGATIVE_PROMPT_LENGTH} символов)"
            )
        return text

    @field_validator("generation_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        mode = (v or "").strip()
        if mode not in ALLOWED_GENERATION_MODES:
            raise ValueError("Некорректный режим генерации")
        return mode

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, v: str) -> str:
        res = (v or "").strip()
        if res not in ALLOWED_RESOLUTIONS:
            raise ValueError("Разрешение: 1K, 2K или 4K")
        return res

    @field_validator("aspect_ratio")
    @classmethod
    def validate_aspect(cls, v: str) -> str:
        aspect = (v or "").strip()
        if aspect not in ALLOWED_ASPECT_RATIOS:
            raise ValueError("Некорректное соотношение сторон")
        return aspect

    @field_validator("guidance_scale")
    @classmethod
    def validate_guidance(cls, v: float) -> float:
        if v < 1 or v > 30:
            raise ValueError("Guidance должен быть от 1 до 30")
        return v

    @field_validator("num_inference_steps")
    @classmethod
    def validate_steps(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("Шаги: от 1 до 100")
        return v

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        name = v.strip()
        if not name:
            return None
        if len(name) > MAX_MODEL_NAME_LENGTH or "<" in name or ">" in name:
            raise ValueError("Некорректное имя модели")
        from nano_banana.providers.models import get_model_entry

        key = name.lower()
        if get_model_entry(key) is None:
            raise ValueError("Неизвестная модель")
        return key

    @field_validator("reference_images")
    @classmethod
    def validate_references(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if not v:
            return None
        if len(v) > MAX_REFERENCE_IMAGES:
            raise ValueError(f"Максимум {MAX_REFERENCE_IMAGES} референса")
        return v

class ImageGenerationResponse(BaseModel):
    status: str
    image_id: Optional[int] = None
    image_url: Optional[str] = None
    message: Optional[str] = None

class ImageResponse(BaseModel):
    id: int
    user_id: int
    prompt: str
    negative_prompt: Optional[str]
    generation_mode: str
    resolution: str
    aspect_ratio: str
    result_url: Optional[str]
    status: str
    created_at: datetime
    error_message: Optional[str] = None
    model_name: Optional[str] = None  # Модель, использованная для генерации
    retry_count: Optional[int] = 0  # Количество уже выполненных ретраев
    max_retries: Optional[int] = 5  # Максимум ретраев для текущей генерации
    fallback_model: Optional[str] = None  # Рекомендуемая fallback-модель для быстрого перезапуска
    provider: Optional[str] = None
    original_prompt: Optional[str] = None
    sanitized_prompt: Optional[str] = None
    sanitize_replacements: Optional[List[str]] = None
    rewritten_prompt: Optional[str] = None
    rewrite_model: Optional[str] = None
    rewrite_error: Optional[str] = None
    policy_gpt_attempts: Optional[List[dict]] = None
    provider_job_id: Optional[str] = None
    provider_model: Optional[str] = None
    provider_cost_usd: Optional[float] = None
    estimated_cost_usd: Optional[float] = None
    
    class Config:
        from_attributes = True

