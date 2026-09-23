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
