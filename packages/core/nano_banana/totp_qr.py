"""QR для TOTP без сторонних API — секрет не уходит с нашего сервера."""
from __future__ import annotations

import base64
import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def otpauth_qr_data_url(otpauth_url: str) -> str:
    uri = (otpauth_url or "").strip()
    if not uri.startswith("otpauth://"):
        raise ValueError("invalid otpauth url")
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
