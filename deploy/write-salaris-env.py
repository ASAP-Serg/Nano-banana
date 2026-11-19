#!/usr/bin/env python3
"""Write /tmp/salaris.env from SALARIS_* environment variables (GitHub Actions → SSH)."""
from __future__ import annotations

import os
from pathlib import Path


def esc(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def main() -> None:
    lines = [
        f"API_KEY={esc(os.environ.get('SALARIS_API_KEY', ''))}",
        "PROCESS_API_URL=https://ooneclickk.ru/salaris",
        "PORT=5000",
        "DEBUG=False",
        "HEADLESS=false",
        "CHROME_USER_DATA_DIR=/data/chrome-user-data",
        f"MOSAICA_EMAIL={esc(os.environ.get('SALARIS_MOSAICA_EMAIL', ''))}",
        f"MOSAICA_PASSWORD={esc(os.environ.get('SALARIS_MOSAICA_PASSWORD', ''))}",
    ]
    creds = (os.environ.get("SALARIS_GOOGLE_SHEETS_CREDENTIALS") or "").strip()
    if creds:
        lines.append(f"GOOGLE_SHEETS_CREDENTIALS={esc(creds)}")
    Path("/tmp/salaris.env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote /tmp/salaris.env from GitHub Secrets")


if __name__ == "__main__":
    main()
