"""Security hardening: Redis AUTH, rate-limit, bootstrap compare, presign TTL."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from nano_banana.config import apply_redis_password
from nano_banana.security import constant_time_secret_equal


class TestRedisUrl(unittest.TestCase):
    def test_injects_password(self):
        self.assertEqual(
            apply_redis_password("redis://redis:6379/0", "s3cret"),
            "redis://:s3cret@redis:6379/0",
        )

    def test_keeps_existing_password(self):
        url = "redis://:already@redis:6379/1"
        self.assertEqual(apply_redis_password(url, "other"), url)

    def test_empty_password_unchanged(self):
        self.assertEqual(apply_redis_password("redis://localhost:6379/0", ""), "redis://localhost:6379/0")

    def test_quotes_special_chars(self):
        out = apply_redis_password("redis://redis:6379/0", "p@ss:word")
        self.assertIn("@redis:6379/0", out)
        self.assertIn("p%40ss%3Aword", out)


class TestBootstrapCompare(unittest.TestCase):
    def test_match(self):
        self.assertTrue(constant_time_secret_equal("abc-secret", "abc-secret"))

    def test_mismatch(self):
        self.assertFalse(constant_time_secret_equal("abc-secret", "abc-secreX"))

    def test_empty_expected(self):
        self.assertFalse(constant_time_secret_equal("", "anything"))
        self.assertFalse(constant_time_secret_equal("   ", "x"))

    def test_missing_header(self):
        self.assertFalse(constant_time_secret_equal("abc-secret", None))


class TestPresignTtl(unittest.TestCase):
    def test_prod_clamps_to_300(self):
        from nano_banana.config import Settings

        s = Settings(
            SECRET_KEY="x" * 64,
            POSTGRES_PASSWORD="test-strong-postgres-password",
            MINIO_ACCESS_KEY="testminioaccess12",
            MINIO_SECRET_KEY="test-strong-minio-secret-key",
            API_URL="https://app.example.com",
            DATA_ENCRYPTION_KEY="y" * 64,
            REDIS_PASSWORD="test-redis-password-not-weak-xx",
            MINIO_PRESIGN_EXPIRES_SECONDS=900,
        )
        self.assertEqual(s.presign_ttl_seconds, 300)

    def test_prod_requires_redis_password(self):
        from nano_banana.config import Settings

        with self.assertRaises(Exception):
            Settings(
                SECRET_KEY="x" * 64,
                POSTGRES_PASSWORD="test-strong-postgres-password",
                MINIO_ACCESS_KEY="testminioaccess12",
                MINIO_SECRET_KEY="test-strong-minio-secret-key",
                API_URL="https://app.example.com",
                DATA_ENCRYPTION_KEY="y" * 64,
                REDIS_PASSWORD="",
                REDIS_URL="redis://redis:6379/0",
            )


class TestClientIp(unittest.TestCase):
    def test_trusts_x_real_ip_from_private_peer(self):
        from nano_banana.rate_limit import client_ip_from_request

        req = SimpleNamespace(
            client=SimpleNamespace(host="172.18.0.4"),
            headers={"x-real-ip": "203.0.113.10"},
        )
        self.assertEqual(client_ip_from_request(req), "203.0.113.10")

    def test_ignores_x_real_ip_from_public_peer(self):
        from nano_banana.rate_limit import client_ip_from_request

        req = SimpleNamespace(
            client=SimpleNamespace(host="203.0.113.99"),
            headers={"x-real-ip": "1.2.3.4"},
        )
        self.assertEqual(client_ip_from_request(req), "203.0.113.99")

    def test_ignores_garbage_x_real_ip(self):
        from nano_banana.rate_limit import client_ip_from_request

        req = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={"x-real-ip": "not-an-ip, 1.2.3.4"},
        )
        self.assertEqual(client_ip_from_request(req), "127.0.0.1")

    def test_ignores_xff(self):
        from nano_banana.rate_limit import client_ip_from_request

        req = SimpleNamespace(
            client=SimpleNamespace(host="10.0.0.8"),
            headers={"x-forwarded-for": "8.8.8.8"},
        )
        self.assertEqual(client_ip_from_request(req), "10.0.0.8")


class TestRateLimitFailClosed(unittest.TestCase):
    def test_redis_down_is_503(self):
        from nano_banana.rate_limit import check_rate_limit

        with patch("nano_banana.rate_limit.get_job_queue", side_effect=RuntimeError("redis down")):
            with self.assertRaises(HTTPException) as ctx:
                check_rate_limit("login-ip", "1.2.3.4", 10, 300)
        self.assertEqual(ctx.exception.status_code, 503)


class TestUsernameRules(unittest.TestCase):
    def test_plain_and_cyrillic_ok(self):
        from nano_banana.schemas import UserCreateRequest

        for name in ("serg", "nomad", "Анастасия", "nano_banana"):
            user = UserCreateRequest(username=name, email="user@example.com", password="1234567890")
            self.assertEqual(user.username, name)

    def test_html_payload_rejected(self):
        from pydantic import ValidationError

        from nano_banana.schemas import UserCreateRequest

        for bad in (
            "<img src=x onerror=1>",
            "a<script>x",
            "js:alert(1)",
            " ab",
            "_root",
            "x" * 33,
        ):
            with self.assertRaises(ValidationError):
                UserCreateRequest(
                    username=bad,
                    email="user@example.com",
                    password="1234567890",
                )


class TestBolaGenerationOwnership(unittest.TestCase):
    """BOLA: user A must not read/delete user B's generation by ID."""

    def test_get_and_delete_require_owner_filter(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "apps"
            / "api"
            / "nano_banana_api"
            / "routers"
            / "images.py"
        )
        text = src.read_text(encoding="utf-8")
        self.assertIn("async def get_generation_full", text)
        self.assertIn("async def delete_generation", text)
        # both owners lookups must bind generation to the caller
        self.assertGreaterEqual(
            text.count("Generation.user_id == user.user_id"),
            2,
            msg="get/delete must filter by owning user_id",
        )


class TestGenerationInputLimits(unittest.TestCase):
    def test_long_prompt_rejected(self):
        from pydantic import ValidationError

        from nano_banana.schemas import MAX_PROMPT_LENGTH, ImageGenerationRequest

        with self.assertRaises(ValidationError):
            ImageGenerationRequest(prompt="x" * (MAX_PROMPT_LENGTH + 1))

    def test_too_many_refs_rejected(self):
        from pydantic import ValidationError

        from nano_banana.schemas import ImageGenerationRequest

        with self.assertRaises(ValidationError):
            ImageGenerationRequest(prompt="cat", reference_images=["a", "b", "c", "d", "e"])

    def test_api_key_in_body_is_dropped(self):
        from nano_banana.schemas import ImageGenerationRequest

        body = ImageGenerationRequest(prompt="cat", api_key="sk-or-stolen")
        dumped = body.model_dump()
        self.assertNotIn("api_key", dumped)
        self.assertEqual(body.prompt, "cat")

    def test_bad_resolution_rejected(self):
        from pydantic import ValidationError

        from nano_banana.schemas import ImageGenerationRequest

        with self.assertRaises(ValidationError):
            ImageGenerationRequest(prompt="cat", resolution="8K")


class TestQueuePayloadNoSecrets(unittest.TestCase):
    def test_generate_router_does_not_enqueue_api_key(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "apps"
            / "api"
            / "nano_banana_api"
            / "routers"
            / "images.py"
        )
        text = src.read_text(encoding="utf-8")
        self.assertIn("def _queue_payload", text)
        self.assertNotIn("request.api_key", text)
        self.assertIn("check_rate_limit", text)
        self.assertIn("generate-user", text)
        self.assertIn("allow_any_owner", text)


class TestPublicValidationErrors(unittest.TestCase):
    def test_strips_input_and_ctx(self):
        from nano_banana.security import public_validation_errors

        raw = [
            {
                "loc": ["body", "password"],
                "msg": "too short",
                "type": "value_error",
                "input": "super-secret-password",
                "ctx": {"min_length": 10},
            }
        ]
        out = public_validation_errors(raw)
        self.assertEqual(out[0]["loc"], ["body", "password"])
        self.assertEqual(out[0]["msg"], "too short")
        self.assertNotIn("input", out[0])
        self.assertNotIn("ctx", out[0])


class TestSelectKeyIgnoresRequestOverride(unittest.TestCase):
    def test_stored_key_wins(self):
        from nano_banana.providers.models import select_api_key_for_model

        keys = {"replicate": "r8_stored", "bananalab": "", "openrouter": ""}
        self.assertEqual(
            select_api_key_for_model("nano-banana-pro-r8", keys, "r8_from_request"),
            "r8_stored",
        )


class TestResidualRemoteSurface(unittest.TestCase):
    def test_images_router_does_not_presign_to_clients(self):
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[1]
            / "apps"
            / "api"
            / "nano_banana_api"
            / "routers"
            / "images.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("refresh_access_url", text)
        self.assertIn("/{generation_id}/file", text)
        self.assertIn("client_result_url", text)

    def test_admin_router_does_not_presign_to_clients(self):
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[1]
            / "apps"
            / "api"
            / "nano_banana_api"
            / "routers"
            / "admin.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("refresh_access_url", text)
        self.assertIn("AdminPasswordRequest", text)
        self.assertIn("_verify_admin_password", text)
        self.assertIn("totp_enabled", text)

    def test_cookie_and_login_timing(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        auth_router = (root / "apps" / "api" / "nano_banana_api" / "routers" / "auth.py").read_text(
            encoding="utf-8"
        )
        auth_core = (root / "packages" / "core" / "nano_banana" / "auth.py").read_text(encoding="utf-8")
        self.assertIn('samesite="strict"', auth_router)
        self.assertNotIn('samesite="lax"', auth_router)
        self.assertNotIn("TOTP_REQUIRED", auth_router)
        self.assertIn("DUMMY_PASSWORD_HASH", auth_core)
        self.assertNotIn('"is_admin": user_data.is_admin', auth_core)
        self.assertNotIn('"email": user_data.email', auth_core)

    def test_client_media_urls_are_relative_proxy(self):
        from nano_banana.storage.media import client_reference_urls, client_result_url

        gen = SimpleNamespace(
            id=9,
            result_path="images/x.jpg",
            result_url="images/x.jpg",
            generation_metadata={"reference_image_urls": ["images/r.jpg"]},
        )
        self.assertEqual(client_result_url(gen), "/api/v1/images/9/file")
        self.assertEqual(client_reference_urls(gen), ["/api/v1/images/9/reference/0"])

    def test_http_reference_from_client_rejected(self):
        from nano_banana.generation.references import store_reference_images

        with self.assertRaises(ValueError):
            store_reference_images(object(), ["https://evil.example/a.png"], 1)

    def test_cloudflare_not_in_outbound_allowlist(self):
        from nano_banana.config import settings
        from nano_banana.security import assert_safe_outbound_image_url

        with self.assertRaises(ValueError):
            assert_safe_outbound_image_url("https://cdn.cloudflare.com/img.jpg", settings)

    def test_web_media_url_allowlist(self):
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "toast.js"
        ).read_text(encoding="utf-8")
        self.assertIn("export function isSafeMediaUrl", text)
        self.assertIn('credentials: "include"', text)
        self.assertIn("/api/v1/images/", text.replace("\\/", "/"))
        self.assertIn("file|reference", text)


class TestMediumHardening(unittest.TestCase):
    def test_unknown_model_rejected(self):
        from pydantic import ValidationError

        from nano_banana.schemas import ImageGenerationRequest

        body = ImageGenerationRequest(prompt="cat", model_name="nano-banana-pro")
        self.assertEqual(body.model_name, "nano-banana-pro")
        with self.assertRaises(ValidationError):
            ImageGenerationRequest(prompt="cat", model_name="google/flux-pro")

    def test_replicate_slug_no_passthrough(self):
        from nano_banana.providers.models import get_model_providers, replicate_slug

        self.assertEqual(replicate_slug("nano-banana-pro-r8"), "google/nano-banana-pro")
        self.assertIsNone(replicate_slug("google/flux-pro"))
        self.assertIsNone(replicate_slug("nano-banana-pro"))
        self.assertEqual(get_model_providers("google/flux-pro"), [])
        self.assertEqual(get_model_providers("nano-banana-pro"), ["bananalab"])

    def test_open_cloud_suffixes_blocked(self):
        from nano_banana.config import Settings
        from nano_banana.security import is_safe_outbound_image_url

        s = Settings(
            SECRET_KEY="x" * 64,
            POSTGRES_PASSWORD="test-strong-postgres-password",
            MINIO_ACCESS_KEY="testminioaccess12",
            MINIO_SECRET_KEY="test-strong-minio-secret-key",
            MINIO_PUBLIC_URL="https://storage.example.com",
            MINIO_BUCKET="nano-banana-images",
            API_URL="https://app.example.com",
            DATA_ENCRYPTION_KEY="y" * 64,
            REDIS_PASSWORD="test-redis-password-not-weak-xx",
        )
        self.assertFalse(is_safe_outbound_image_url("https://evil.r2.dev/img.jpg", s))
        self.assertFalse(is_safe_outbound_image_url("https://bucket.s3.amazonaws.com/img.jpg", s))
        self.assertFalse(is_safe_outbound_image_url("https://app.example.com/nano-banana-images/images/x.jpg", s))
        self.assertTrue(
            is_safe_outbound_image_url(
                "https://storage.example.com/nano-banana-images/images/results/a.jpg", s
            )
        )
        self.assertTrue(is_safe_outbound_image_url("https://pbxt.replicate.delivery/x.jpg", s))

    def test_materialize_rejects_foreign_object_path(self):
        from nano_banana.generation.references import materialize_reference_images

        class FakeMinio:
            def __init__(self):
                self.reads = []

            def extract_object_path(self, url_or_path):
                value = (url_or_path or "").strip()
                if value.startswith("images/") and ".." not in value:
                    return value.split("?", 1)[0]
                return None

            def get_object_bytes(self, path):
                self.reads.append(path)
                return b"x" * 600, "image/jpeg"

        minio = FakeMinio()
        with self.assertRaises(ValueError):
            materialize_reference_images(
                minio,
                ["images/other/secret.jpg"],
                allowed_sources=["images/mine/ref.jpg"],
            )
        self.assertEqual(minio.reads, [])
        out = materialize_reference_images(
            minio,
            ["images/mine/ref.jpg"],
            allowed_sources=["images/mine/ref.jpg"],
        )
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("data:image/jpeg;base64,"))
        self.assertEqual(minio.reads, ["images/mine/ref.jpg"])

    def test_register_rate_limit_before_bootstrap_403(self):
        from pathlib import Path

        auth_router = (
            Path(__file__).resolve().parents[1]
            / "apps"
            / "api"
            / "nano_banana_api"
            / "routers"
            / "auth.py"
        ).read_text(encoding="utf-8")
        self.assertLess(
            auth_router.find("check_rate_limit"),
            auth_router.find("Регистрация отключена"),
        )

    def test_nginx_forwards_client_ip_and_k8s_csp(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        compose = (root / "deploy" / "nginx" / "web.compose.conf").read_text(encoding="utf-8")
        k8s = (root / "deploy" / "nginx" / "web.conf").read_text(encoding="utf-8")
        self.assertIn("map $http_x_real_ip $nb_client_ip", compose)
        api_block = compose.split("location /api/")[1].split("location ")[0]
        self.assertIn("X-Real-IP $nb_client_ip", api_block)
        self.assertNotIn("X-Real-IP $remote_addr", api_block)
        self.assertIn("Content-Security-Policy", k8s)

    def test_providers_use_capped_download(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        replicate = (root / "packages" / "core" / "nano_banana" / "providers" / "replicate.py").read_text(
            encoding="utf-8"
        )
        moonez = (root / "packages" / "core" / "nano_banana" / "providers" / "moonez.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("requests.get(", replicate)
        self.assertIn("download_image_from_url", replicate)
        self.assertIn("download_image_from_url", moonez)


class TestIdleAccounts(unittest.TestCase):
    def test_never_generated_recent_is_not_idle(self):
        from datetime import datetime, timedelta

        from nano_banana.idle import is_generation_idle

        now = datetime(2026, 10, 5)
        created = now - timedelta(days=10)
        self.assertFalse(is_generation_idle(created, None, now=now))

    def test_never_generated_old_is_idle(self):
        from datetime import datetime, timedelta

        from nano_banana.idle import is_generation_idle

        now = datetime(2026, 10, 5)
        created = now - timedelta(days=61)
        self.assertTrue(is_generation_idle(created, None, now=now))

    def test_recent_generation_is_not_idle(self):
        from datetime import datetime, timedelta

        from nano_banana.idle import is_generation_idle

        now = datetime(2026, 10, 5)
        created = now - timedelta(days=200)
        last = now - timedelta(days=3)
        self.assertFalse(is_generation_idle(created, last, now=now))

    def test_old_generation_is_idle(self):
        from datetime import datetime, timedelta

        from nano_banana.idle import is_generation_idle

        now = datetime(2026, 10, 5)
        created = now - timedelta(days=200)
        last = now - timedelta(days=61)
        self.assertTrue(is_generation_idle(created, last, now=now))


class TestTotpQrIsLocal(unittest.TestCase):
    def test_otpauth_becomes_png_data_url(self):
        from nano_banana.totp_qr import otpauth_qr_data_url

        url = otpauth_qr_data_url("otpauth://totp/Nano%20Banana:serg?secret=JBSWY3DPEHPK3PXP&issuer=Nano%20Banana")
        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertGreater(len(url), 800)

    def test_rejects_non_otpauth(self):
        from nano_banana.totp_qr import otpauth_qr_data_url

        with self.assertRaises(ValueError):
            otpauth_qr_data_url("https://chart.googleapis.com/evil")

