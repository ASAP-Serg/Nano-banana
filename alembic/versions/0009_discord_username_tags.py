"""Append Discord-style #dddd tags to usernames missing them.

Revision ID: 0009_discord_username_tags
Revises: 0008_superadmin
Create Date: 2026-11-23
"""
from __future__ import annotations

import re
import secrets

import sqlalchemy as sa
from alembic import op

revision = "0009_discord_username_tags"
down_revision = "0008_superadmin"
branch_labels = None
depends_on = None

_NICK_RE = re.compile(r"^[\w.-]{2,28}$", re.UNICODE)
_FULL_RE = re.compile(r"^[\w.-]{2,28}#\d{4}$", re.UNICODE)


def _sanitize_nick(raw: str) -> str:
    text = (raw or "").strip()
    if "#" in text:
        text = text.split("#", 1)[0].strip()
    text = re.sub(r"[^\w.-]", "", text, flags=re.UNICODE)
    text = text.strip(".-_") or "user"
    if len(text) < 2:
        text = (text + "user")[:28]
    text = text[:28]
    if not _NICK_RE.fullmatch(text) or text[0] in ".-_" or text[-1] in ".-":
        text = "user"
    return text


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return

    rows = bind.execute(sa.text("SELECT id, username FROM users")).fetchall()
    used = {(r.username or "").lower() for r in rows if r.username}

    for row in rows:
        current = (row.username or "").strip()
        if _FULL_RE.fullmatch(current) and current[0] not in ".-_" and current.split("#", 1)[0][-1] not in ".-":
            continue
        nick = _sanitize_nick(current)
        for _ in range(300):
            tag = f"{secrets.randbelow(10000):04d}"
            candidate = f"{nick}#{tag}"
            if candidate.lower() not in used:
                bind.execute(
                    sa.text("UPDATE users SET username = :u WHERE id = :id"),
                    {"u": candidate, "id": row.id},
                )
                used.add(candidate.lower())
                break
        else:
            fallback = f"user{secrets.token_hex(3)}#{secrets.randbelow(10000):04d}"
            bind.execute(
                sa.text("UPDATE users SET username = :u WHERE id = :id"),
                {"u": fallback, "id": row.id},
            )
            used.add(fallback.lower())


def downgrade() -> None:
    # Irreversible: tags were assigned randomly.
    pass
