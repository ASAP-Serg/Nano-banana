#!/usr/bin/env python3
"""Authorized defensive live smoke against a deployed Nano-banana instance.

Usage:
  LIVE_BASE_URL=https://ooneclickk.ru python scripts/security_live_smoke.py

Optional:
  LIVE_STORAGE_URL=https://storage.ooneclickk.ru

This script only checks that security controls respond as expected
(401/403/headers/redirects). It does not probe for exploits, brute-force,
or generate load.
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

BASE = (os.environ.get("LIVE_BASE_URL") or "").rstrip("/")
STORAGE = (os.environ.get("LIVE_STORAGE_URL") or "https://storage.ooneclickk.ru").rstrip("/")
TIMEOUT = float(os.environ.get("LIVE_SMOKE_TIMEOUT", "20"))


class Check:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""


def _request(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    data: Optional[bytes] = None,
) -> Tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(65536)
            return resp.getcode() or 200, dict(resp.headers.items()), body
    except urllib.error.HTTPError as exc:
        body = exc.read(65536) if exc.fp else b""
        return int(exc.code), dict(exc.headers.items()) if exc.headers else {}, body
    except Exception as exc:  # noqa: BLE001 — smoke must report network failures
        raise RuntimeError(f"{method} {url}: {exc}") from exc


def _hdr(headers: dict, name: str) -> str:
    lower = {k.lower(): v for k, v in headers.items()}
    return lower.get(name.lower(), "")


def run() -> int:
    if not BASE:
        print("Set LIVE_BASE_URL (e.g. https://ooneclickk.ru)", file=sys.stderr)
        return 2

    checks: List[Check] = []

    # Health (nginx proxies /health and /healthz to the API)
    c = Check("health")
    try:
        code, _, _ = _request(f"{BASE}/health")
        if code == 200:
            c.ok = True
            c.detail = "200 /health"
        else:
            code2, _, _ = _request(f"{BASE}/healthz")
            if code2 == 200:
                c.ok = True
                c.detail = "200 /healthz"
            else:
                c.detail = f"unexpected {code} / {code2}"
    except Exception as exc:  # noqa: BLE001
        c.detail = str(exc)
    checks.append(c)

    # Security headers on web root
    c = Check("web_security_headers")
    try:
        code, headers, _ = _request(f"{BASE}/")
        needed = ("x-frame-options", "x-content-type-options", "content-security-policy")
        missing = [h for h in needed if not _hdr(headers, h)]
        if code in (200, 304) and not missing:
            c.ok = True
            c.detail = f"{code}; headers ok"
        elif code in (200, 304):
            c.detail = f"{code}; missing {missing}"
        else:
            c.detail = f"status {code}; missing {missing}"
    except Exception as exc:  # noqa: BLE001
        c.detail = str(exc)
    checks.append(c)

    # Protected API without session
    c = Check("unauth_me_rejected")
    try:
        code, _, body = _request(f"{BASE}/api/v1/auth/me")
        if code in (401, 403):
            c.ok = True
            c.detail = str(code)
        else:
            c.detail = f"expected 401/403, got {code}: {body[:120]!r}"
    except Exception as exc:  # noqa: BLE001
        c.detail = str(exc)
    checks.append(c)

    # Cookie CSRF: state-changing with fake session cookie, no Origin
    c = Check("csrf_cookie_no_origin")
    try:
        code, _, body = _request(
            f"{BASE}/api/v1/auth/logout",
            method="POST",
            headers={
                "Cookie": "nb_access=not-a-real-jwt",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        if code == 403 and b"CSRF" in body:
            c.ok = True
            c.detail = "403 CSRF"
        else:
            c.detail = f"expected 403 CSRF, got {code}: {body[:160]!r}"
    except Exception as exc:  # noqa: BLE001
        c.detail = str(exc)
    checks.append(c)

    # Storage console / minio blocked
    for path in ("/console", "/console/", "/minio", "/minio/"):
        c = Check(f"storage_block{path.rstrip('/') or '/root'}")
        try:
            code, _, _ = _request(f"{STORAGE}{path}")
            if code in (403, 404):
                c.ok = True
                c.detail = str(code)
            else:
                c.detail = f"expected 403/404, got {code}"
        except Exception as exc:  # noqa: BLE001
            c.detail = str(exc)
        checks.append(c)

    # Unsigned storage object GET should be denied
    c = Check("storage_unsigned_get_denied")
    try:
        code, _, _ = _request(f"{STORAGE}/nano-banana/images/does-not-exist.jpg")
        if code in (403, 404):
            c.ok = True
            c.detail = str(code)
        else:
            c.detail = f"expected 403/404, got {code}"
    except Exception as exc:  # noqa: BLE001
        c.detail = str(exc)
    checks.append(c)

    # Soft rate-limit probe (2 attempts only — never a flood)
    c = Check("login_rate_limit_soft")
    try:
        codes = []
        for _ in range(2):
            code, _, _ = _request(
                f"{BASE}/api/v1/auth/login",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Origin": BASE,
                },
                data=b'{"username_or_email":"__smoke_nonexistent__","password":"definitely-wrong-password"}',
            )
            codes.append(code)
        if 429 in codes:
            c.ok = True
            c.detail = f"got 429 among {codes}"
        elif all(x in (400, 401, 422) for x in codes):
            c.ok = True
            c.detail = f"skip (limit not hit in 2 tries): {codes}"
        else:
            c.detail = f"unexpected statuses {codes}"
    except Exception as exc:  # noqa: BLE001
        c.detail = str(exc)
    checks.append(c)

    failed = 0
    for item in checks:
        mark = "PASS" if item.ok else "FAIL"
        if not item.ok:
            failed += 1
        print(f"[{mark}] {item.name}: {item.detail}")

    print(f"\n{len(checks) - failed}/{len(checks)} passed against {BASE}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
