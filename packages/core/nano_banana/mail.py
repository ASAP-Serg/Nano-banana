"""Transactional email via Resend HTTP API."""
from __future__ import annotations

import html
import logging
from typing import Optional
from urllib.parse import urlparse

import requests

from nano_banana.config import settings

logger = logging.getLogger(__name__)


def mail_configured() -> bool:
    return bool((settings.RESEND_API_KEY or "").strip() and (settings.MAIL_FROM or "").strip())


def _safe_link(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "#"
    return html.escape(raw, quote=True)


def send_email(*, to: str, subject: str, html_body: str, text: Optional[str] = None) -> bool:
    if not mail_configured():
        logger.warning("[MAIL] not configured — skip send to %s (%s)", to, subject)
        return False
    payload = {
        "from": settings.MAIL_FROM.strip(),
        "to": [to.strip()],
        "subject": subject,
        "html": html_body,
    }
    if text:
        payload["text"] = text
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY.strip()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if resp.status_code >= 300:
            logger.error("[MAIL] Resend %s: %s", resp.status_code, (resp.text or "")[:300])
            return False
        return True
    except Exception as exc:
        logger.error("[MAIL] send failed: %s", type(exc).__name__)
        return False


def send_verify_email(to: str, verify_url: str, username: str) -> bool:
    safe_name = html.escape((username or "друг").strip() or "друг")
    link = _safe_link(verify_url)
    return send_email(
        to=to,
        subject="Подтвердите email — Nano Banana",
        text=f"Здравствуйте!\n\nПодтвердите email: {verify_url}\n\nСсылка действует 24 часа.",
        html_body=(
            f"<p>Здравствуйте, <b>{safe_name}</b>!</p>"
            f"<p>Подтвердите email, чтобы завершить регистрацию в Nano Banana.</p>"
            f'<p><a href="{link}">Подтвердить email</a></p>'
            f"<p style='color:#666;font-size:13px'>Ссылка действует 24 часа. Если это не вы — просто игнорируйте письмо.</p>"
        ),
    )


def send_reset_password_email(to: str, reset_url: str, username: str) -> bool:
    safe_name = html.escape((username or "друг").strip() or "друг")
    link = _safe_link(reset_url)
    return send_email(
        to=to,
        subject="Сброс пароля — Nano Banana",
        text=f"Здравствуйте!\n\nСброс пароля: {reset_url}\n\nСсылка действует 1 час.",
        html_body=(
            f"<p>Здравствуйте, <b>{safe_name}</b>!</p>"
            f"<p>Запрос на сброс пароля в Nano Banana.</p>"
            f'<p><a href="{link}">Задать новый пароль</a></p>'
            f"<p style='color:#666;font-size:13px'>Ссылка действует 1 час. Если это не вы — игнорируйте письмо.</p>"
        ),
    )
