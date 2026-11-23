"""Transactional email via Resend (HTTPS API first; SMTP fallback).

AdminVPS NL blocks outbound SMTP 465/587; RU VPS often timed out on HTTPS.
Try API first, then SMTP.
"""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional
from urllib.parse import urlparse

import requests

from nano_banana.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def mail_configured() -> bool:
    return bool((settings.RESEND_API_KEY or "").strip() and (settings.MAIL_FROM or "").strip())


def _safe_link(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "#"
    return html.escape(raw, quote=True)


def _parse_from(raw: str) -> tuple[str, str]:
    """Return (display_name, email) from 'Name <email@x>' or bare email."""
    text = (raw or "").strip()
    if "<" in text and text.endswith(">"):
        name, _, rest = text.partition("<")
        return name.strip().strip('"') or "Nano Banana", rest[:-1].strip()
    return "Nano Banana", text


def _public_origin() -> str:
    for part in (settings.CORS_ORIGINS or "").split(","):
        origin = part.strip().rstrip("/")
        if origin.startswith("https://") or origin.startswith("http://"):
            return origin
    return "https://ooneclickk.ru"


def _brand_header_html() -> str:
    logo = html.escape(f"{_public_origin()}/favicon.ico", quote=True)
    return (
        "<div style='margin:0 0 20px'>"
        f"<img src='{logo}' width='48' height='48' alt='Nano Banana' "
        "style='display:block;border:0;border-radius:10px'/>"
        "</div>"
    )


def _send_via_api(
    *,
    api_key: str,
    from_header: str,
    to_addr: str,
    subject: str,
    html_body: str,
    text: str,
) -> bool:
    response = requests.post(
        RESEND_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_header,
            "to": [to_addr],
            "subject": subject,
            "html": html_body,
            "text": text,
        },
        timeout=20,
    )
    if response.status_code < 300:
        return True
    detail = (response.text or "")[:240]
    logger.error("[MAIL] Resend API HTTP %s: %s", response.status_code, detail)
    return False


def _send_via_smtp(
    *,
    api_key: str,
    from_header: str,
    to_addr: str,
    subject: str,
    html_body: str,
    text: str,
) -> bool:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = to_addr
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.resend.com", 465, timeout=12, context=ctx) as smtp:
        smtp.login("resend", api_key)
        smtp.send_message(msg)
    return True


def send_email(*, to: str, subject: str, html_body: str, text: Optional[str] = None) -> bool:
    if not mail_configured():
        logger.warning("[MAIL] not configured — skip send to %s (%s)", to, subject)
        return False

    api_key = settings.RESEND_API_KEY.strip()
    from_name, from_email = _parse_from(settings.MAIL_FROM)
    from_header = f"{from_name} <{from_email}>"
    to_addr = to.strip()
    body_text = text or "Откройте HTML-версию письма."

    try:
        if _send_via_api(
            api_key=api_key,
            from_header=from_header,
            to_addr=to_addr,
            subject=subject,
            html_body=html_body,
            text=body_text,
        ):
            logger.info("[MAIL] sent via Resend API to %s (%s)", to_addr, subject)
            return True
    except Exception as exc:
        logger.warning("[MAIL] Resend API failed: %s: %s", type(exc).__name__, str(exc)[:200])

    try:
        _send_via_smtp(
            api_key=api_key,
            from_header=from_header,
            to_addr=to_addr,
            subject=subject,
            html_body=html_body,
            text=body_text,
        )
        logger.info("[MAIL] sent via Resend SMTP to %s (%s)", to_addr, subject)
        return True
    except Exception as exc:
        logger.error("[MAIL] SMTP send failed: %s: %s", type(exc).__name__, str(exc)[:200])
        return False


def send_verify_email(to: str, verify_url: str, username: str, *, code: str = "") -> bool:
    safe_name = html.escape((username or "друг").strip() or "друг")
    link = _safe_link(verify_url)
    code_digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    code_block = ""
    text_code = ""
    if len(code_digits) == 6:
        safe_code = html.escape(code_digits)
        code_block = (
            f"<p>Код подтверждения:</p>"
            f"<p style='font-size:28px;letter-spacing:6px;font-weight:700'>{safe_code}</p>"
            f"<p>Введите его в форме регистрации на сайте.</p>"
        )
        text_code = f"\n\nКод подтверждения: {code_digits}\nВведите его на сайте.\n"
    return send_email(
        to=to,
        subject="Подтвердите email — Nano Banana",
        text=(
            f"Здравствуйте!\n{text_code}\n"
            f"Или откройте ссылку: {verify_url}\n\nКод/ссылка действуют 24 часа."
        ),
        html_body=(
            f"{_brand_header_html()}"
            f"<p>Здравствуйте, <b>{safe_name}</b>!</p>"
            f"<p>Подтвердите email, чтобы завершить регистрацию в Nano Banana.</p>"
            f"{code_block}"
            f'<p style="margin-top:16px"><a href="{link}">Или подтвердить по ссылке</a></p>'
            f"<p style='color:#666;font-size:13px'>Действует 24 часа. Если это не вы — просто игнорируйте письмо.</p>"
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
            f"{_brand_header_html()}"
            f"<p>Здравствуйте, <b>{safe_name}</b>!</p>"
            f"<p>Запрос на сброс пароля в Nano Banana.</p>"
            f'<p><a href="{link}">Задать новый пароль</a></p>'
            f"<p style='color:#666;font-size:13px'>Ссылка действует 1 час. Если это не вы — игнорируйте письмо.</p>"
        ),
    )
