"""Локальные проверки без реальных вызовов API."""
import unittest

from nano_banana.providers.prompt import enhance_prompt_for_image_generation
from nano_banana.providers.detect import infer_image_api_provider
from nano_banana.providers.errors import detail_from_response_body, find_image_in_json, humanize_api_error, is_content_policy_error, is_openrouter_security_policy, is_policy_block_error


class TestProvider(unittest.TestCase):
    def test_nb_prefix(self):
        self.assertEqual(infer_image_api_provider("nb_abc"), "bananalab")

    def test_bh_prefix(self):
        self.assertEqual(infer_image_api_provider("bh_abc"), "bananalab")
        self.assertEqual(infer_image_api_provider("BH_ABC"), "bananalab")

    def test_openrouter_prefix(self):
        self.assertEqual(infer_image_api_provider("sk-or-v1-abc"), "openrouter")

    def test_replicate_default(self):
        self.assertEqual(infer_image_api_provider("r8_xx"), "replicate")
        self.assertEqual(infer_image_api_provider(""), "replicate")


class TestImageModels(unittest.TestCase):
    def test_gpt_model_requires_openrouter(self):
        from nano_banana.providers.models import get_provider_for_model, select_api_key_for_model

        keys = {"replicate": "r8_x", "bananalab": "nb_x", "openrouter": ""}
        self.assertIsNone(get_provider_for_model("gpt-5-image", keys))

        keys["openrouter"] = "sk-or-v1-test"
        self.assertEqual(get_provider_for_model("gpt-5-image", keys), "openrouter")
        self.assertEqual(
            select_api_key_for_model("gpt-5-image", keys, None),
            "sk-or-v1-test",
        )

    def test_nano_models_use_single_provider(self):
        from nano_banana.providers.models import get_provider_for_model

        keys = {"replicate": "r8_x", "bananalab": "nb_x", "openrouter": "sk-or_x"}
        self.assertEqual(get_provider_for_model("nano-banana-pro", keys), "bananalab")
        self.assertEqual(get_provider_for_model("nano-banana-pro-r8", keys), "replicate")
        self.assertIsNone(get_provider_for_model("nano-banana-pro", {"replicate": "r8_x", "bananalab": "", "openrouter": ""}))
        self.assertIsNone(get_provider_for_model("nano-banana-pro-r8", {"replicate": "", "bananalab": "nb_x", "openrouter": ""}))

    def test_only_moonez_models_when_only_bh_key(self):
        from nano_banana.providers.models import MODEL_REGISTRY, models_available_with_keys

        keys = {"replicate": "", "bananalab": "bh_x", "openrouter": ""}
        unlocked = list(models_available_with_keys(keys))
        self.assertEqual(unlocked, ["nano-banana-2", "nano-banana", "nano-banana-pro"])
        self.assertGreater(len(MODEL_REGISTRY), len(unlocked))


class TestPromptSanitize(unittest.TestCase):
    def test_batman_ru(self):
        from nano_banana.providers.sanitize import sanitize_prompt

        result = sanitize_prompt("Фото бетмена")
        self.assertTrue(result["changed"])
        self.assertNotIn("бетмен", result["prompt"].lower())
        self.assertIn("плащ", result["prompt"].lower())

    def test_messi_ronaldo_ru(self):
        from nano_banana.providers.sanitize import sanitize_prompt

        result = sanitize_prompt("Леонель Месси пинает под зад Роналду")
        self.assertTrue(result["changed"])
        self.assertNotIn("месси", result["prompt"].lower())
        self.assertNotIn("роналду", result["prompt"].lower())
        self.assertNotIn("под зад", result["prompt"].lower())

    def test_plain_prompt_unchanged(self):
        from nano_banana.providers.sanitize import sanitize_prompt

        text = "закат над морем, масло"
        result = sanitize_prompt(text)
        self.assertFalse(result["changed"])
        self.assertEqual(result["prompt"], text)


class TestPrompt(unittest.TestCase):
    def test_text_to_image_prefix(self):
        p = enhance_prompt_for_image_generation("red apple", None, 0)
        self.assertIn("Generate an image", p)

    def test_ref_single(self):
        p = enhance_prompt_for_image_generation("add hat", ["x"], 1)
        self.assertIn("STRICT INSTRUCTIONS", p)


class TestSecurityHelpers(unittest.TestCase):
    def test_generate_storage_object_name(self):
        from nano_banana.security import generate_storage_object_name

        name = generate_storage_object_name("results", "jpg")
        self.assertTrue(name.startswith("images/results/"))
        self.assertTrue(name.endswith(".jpg"))
        self.assertEqual(len(name.split("/")[-1].split(".")[0]), 32)

    def test_allowed_reference_url(self):
        from nano_banana.config import Settings
        from nano_banana.security import is_allowed_reference_url

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
        ok = "https://storage.example.com/nano-banana-images/images/references/abc.jpg"
        legacy = "https://storage.example.com/nano-banana-images/images/references/ref_20260101_120000_abcd.jpg"
        bad = "https://evil.com/nano-banana-images/images/references/abc.jpg"
        self.assertTrue(is_allowed_reference_url(ok, s))
        self.assertTrue(is_allowed_reference_url(legacy, s))
        self.assertFalse(is_allowed_reference_url(bad, s))

    def test_localhost_reference_alias(self):
        from nano_banana.config import Settings
        from nano_banana.security import is_allowed_reference_url

        s = Settings(
            SECRET_KEY="x" * 64,
            POSTGRES_PASSWORD="test-strong-postgres-password",
            MINIO_ACCESS_KEY="testminioaccess12",
            MINIO_SECRET_KEY="test-strong-minio-secret-key",
            MINIO_PUBLIC_URL="http://localhost:9000",
            MINIO_BUCKET="nano-banana-images",
        )
        url = "http://127.0.0.1:9000/nano-banana-images/images/results/deadbeef.jpg"
        self.assertTrue(is_allowed_reference_url(url, s))

    def test_ssrf_blocks_private_and_evil(self):
        from nano_banana.config import Settings
        from nano_banana.security import is_safe_outbound_image_url

        s = Settings(
            SECRET_KEY="x" * 64,
            POSTGRES_PASSWORD="test-strong-postgres-password",
            MINIO_ACCESS_KEY="testminioaccess12",
            MINIO_SECRET_KEY="test-strong-minio-secret-key",
            MINIO_PUBLIC_URL="https://storage.example.com",
            MINIO_BUCKET="nano-banana-images",
        )
        self.assertFalse(is_safe_outbound_image_url("http://169.254.169.254/latest/meta-data/", s))
        self.assertFalse(is_safe_outbound_image_url("https://evil.example/x.jpg", s))
        self.assertTrue(
            is_safe_outbound_image_url(
                "https://storage.example.com/nano-banana-images/images/results/a.jpg", s
            )
        )


class TestResultStorage(unittest.TestCase):
    def test_persist_prefers_image_data(self):
        from unittest.mock import MagicMock
        from nano_banana.storage.results import persist_generation_result

        minio = MagicMock()
        minio.upload_image.return_value = {
            "url": "http://localhost:9000/bucket/images/results/abc.jpg",
            "path": "images/results/abc.jpg",
        }
        out = persist_generation_result(minio, {"image_data": b"x" * 600, "image_url": "https://evil.com/x.jpg"})
        self.assertIsNotNone(out)
        minio.upload_image.assert_called_once()


class TestBanalabJobUrl(unittest.TestCase):
    def test_absolute_status_url_from_path(self):
        from nano_banana.providers.errors import absolute_job_status_url

        u = absolute_job_status_url(
            "https://api.bananalab.pw",
            {"status_url": "/v1/jobs/923f3213-cda5-4e13-8e47-2ea73383aefb", "status": "queued"},
        )
        self.assertEqual(u, "https://api.bananalab.pw/v1/jobs/923f3213-cda5-4e13-8e47-2ea73383aefb")

    def test_bananahub_status_url_with_api_prefix(self):
        from nano_banana.providers.errors import absolute_job_status_url

        u = absolute_job_status_url(
            "https://api.moonez.ai/api",
            {
                "status_url": "/api/v1/jobs/019eb30e-1769-70ff-b648-e207a06b58d0",
                "status": "queued",
            },
        )
        self.assertEqual(
            u,
            "https://api.moonez.ai/api/v1/jobs/019eb30e-1769-70ff-b648-e207a06b58d0",
        )

    def test_bananahub_legacy_io_host_still_supported(self):
        from nano_banana.providers.errors import absolute_job_status_url

        u = absolute_job_status_url(
            "https://bananahub.app/api",
            {
                "status_url": "/api/v1/jobs/019eb30e-1769-70ff-b648-e207a06b58d0",
                "status": "queued",
            },
        )
        # Absolute status_url on legacy host gets rewritten to Moonez
        self.assertEqual(
            u,
            "https://api.moonez.ai/api/v1/jobs/019eb30e-1769-70ff-b648-e207a06b58d0",
        )

    def test_absolute_status_url_from_job_id(self):
        from nano_banana.providers.errors import absolute_job_status_url

        u = absolute_job_status_url("https://api.example.com", {"job_id": "abc-123", "status": "queued"})
        self.assertEqual(u, "https://api.example.com/v1/jobs/abc-123")


class TestBananalabParse(unittest.TestCase):
    def test_detail_string(self):
        self.assertEqual(
            detail_from_response_body({"detail": "bad"}),
            "bad",
        )

    def test_find_url(self):
        b, u = find_image_in_json({"result": {"url": "https://example.com/a.png"}})
        self.assertIsNone(b)
        self.assertEqual(u, "https://example.com/a.png")

    def test_find_bananalab_job_done_shape(self):
        """Как в ответе GET /v1/jobs после завершения."""
        sample = {
            "job_id": "923f3213-cda5-4e13-8e47-2ea73383aefb",
            "status": "done",
            "result": {
                "image_url": "https://api.bananalab.pw/nanobanana-results/results/923f3213.png?x=1"
            },
            "error": None,
        }
        b, u = find_image_in_json(sample)
        self.assertIsNone(b)
        self.assertTrue(u.startswith("https://api.bananalab.pw/"))


class TestHumanizeApiError(unittest.TestCase):
    _CF_521_HTML = """<!DOCTYPE html>
<html><head><title>bananahub.io | 521: Web server is down</title></head>
<body><div class="cf-error-details"><h1>Web server is down</h1>
<p>Error code 521</p></div></body></html>"""

    def test_cloudflare_521_html(self):
        msg = humanize_api_error(self._CF_521_HTML, 521)
        self.assertIn("521", msg)
        self.assertNotIn("<!DOCTYPE", msg)
        self.assertNotIn("cf-error-details", msg)

    def test_json_detail_unchanged(self):
        msg = humanize_api_error({"detail": "Invalid API key"})
        self.assertEqual(msg, "Invalid API key")

    def test_moonez_html_403_title(self):
        msg = humanize_api_error("Ошибка провайдера: 403 Forbidden", provider="bananalab")
        self.assertIn("ключ", msg.lower())
        self.assertIn("moonez", msg.lower())

    def test_moonez_http_403(self):
        msg = humanize_api_error("Forbidden", 403, provider="bananalab")
        self.assertIn("403", msg)

    def test_moonez_html_page_403(self):
        html = "<html><head><title>403 Forbidden</title></head><body>cloudflare</body></html>"
        msg = humanize_api_error(html, 403, provider="bananalab")
        self.assertIn("moonez", msg.lower())
        self.assertNotIn("<html", msg.lower())

    def test_storage_nginx_403_not_moonez(self):
        html = (
            "<html><head><title>403 Forbidden</title></head>"
            "<body><center><h1>403 Forbidden</h1></center>"
            "<hr><center>nginx/1.24.0 (Ubuntu)</center></body></html>"
        )
        msg = humanize_api_error(html, 403, provider="bananalab")
        self.assertIn("хранилищ", msg.lower())
        self.assertNotIn("whitelist", msg.lower())

    def test_model_paused_humanized(self):
        msg = humanize_api_error({"detail": "Model is paused due to high load"})
        self.assertIn("на паузе", msg.lower())
        self.assertNotIn("перегружен", msg.lower())

    def test_project_paused_503_not_overloaded(self):
        msg = humanize_api_error({"detail": "Project is paused."}, 503)
        self.assertIn("на паузе", msg.lower())
        self.assertNotIn("перегружен", msg.lower())

    def test_content_policy_error_hint(self):
        raw = "Request blocked by safety moderation filter"
        self.assertTrue(is_content_policy_error(raw))
        msg = humanize_api_error(raw)
        self.assertIn("фильтр безопасности", msg.lower())
        self.assertIn("переформулируйте", msg.lower())

    def test_openrouter_security_policy(self):
        raw = "OpenRouter: Access denied by security policy."
        self.assertTrue(is_openrouter_security_policy(raw))
        self.assertTrue(is_policy_block_error(raw))
        msg = humanize_api_error(raw, provider="openrouter")
        self.assertIn("openrouter", msg.lower())
        self.assertIn("ключ", msg.lower())
        humanized = humanize_api_error(raw, provider="openrouter")
        self.assertTrue(is_policy_block_error(humanized))

    def test_nested_detail_message(self):
        msg = humanize_api_error(
            {"detail": {"message": "Project is paused.", "field": None, "details": None}},
            503,
        )
        self.assertIn("на паузе", msg.lower())

    def test_is_bananalab_paused_message(self):
        from nano_banana.providers.errors import is_bananalab_paused_message

        self.assertTrue(is_bananalab_paused_message("Project is paused."))
        self.assertTrue(is_bananalab_paused_message("Проект Banana Lab на паузе."))
        self.assertFalse(is_bananalab_paused_message("rate limit exceeded"))

    def test_is_bananalab_unavailable_message(self):
        from nano_banana.providers.errors import (
            BANANALAB_PROVIDER_UNAVAILABLE_MESSAGE,
            is_bananalab_unavailable_message,
        )

        self.assertTrue(
            is_bananalab_unavailable_message(
                "HTTPSConnectionPool(host='bananahub.io', port=443): "
                "Failed to establish a new connection: [Errno 111] Connection refused"
            )
        )
        self.assertTrue(
            is_bananalab_unavailable_message(
                "Failed to resolve 'bananahub.io' ([Errno -2] Name or service not known)"
            )
        )
        self.assertFalse(is_bananalab_unavailable_message("Project is paused."))

        msg = humanize_api_error(
            "Failed to connect to bananahub.io port 443: Connection refused"
        )
        self.assertEqual(msg, BANANALAB_PROVIDER_UNAVAILABLE_MESSAGE)

    def test_is_bananalab_upstream_no_image_message(self):
        from nano_banana.providers.errors import (
            is_bananalab_upstream_no_image_message,
            humanize_api_error,
        )

        self.assertTrue(is_bananalab_upstream_no_image_message("Upstream returned no image"))
        self.assertTrue(
            is_bananalab_upstream_no_image_message("Исходный поток не вернул изображение.")
        )
        self.assertFalse(is_bananalab_upstream_no_image_message("Project is paused."))

        msg = humanize_api_error("Upstream returned no image")
        self.assertIn("повторяем автоматически", msg.lower())

    def test_is_bananalab_empty_done_message(self):
        from nano_banana.providers.errors import is_bananalab_empty_done_message

        self.assertTrue(
            is_bananalab_empty_done_message(
                "Неожиданный формат ответа Moonez: нет URL и base64 изображения (пустой done)."
            )
        )
        self.assertFalse(is_bananalab_empty_done_message("Upstream returned no image"))

    def test_upstream_no_image_retry_delay(self):
        from nano_banana.providers.errors import upstream_no_image_retry_delay_seconds

        self.assertEqual(upstream_no_image_retry_delay_seconds(0, 3), 3.0)
        self.assertEqual(upstream_no_image_retry_delay_seconds(1, 3), 5.0)
        self.assertEqual(upstream_no_image_retry_delay_seconds(4, 3), 11.0)
        self.assertEqual(upstream_no_image_retry_delay_seconds(10, 3), 15.0)

    def test_http_status_without_body(self):
        msg = humanize_api_error("", 503)
        self.assertIn("503", msg)

    def test_long_plain_text_truncated(self):
        msg = humanize_api_error("x" * 1000)
        self.assertLessEqual(len(msg), 520)
        self.assertTrue(msg.endswith("…"))

    def test_is_bananalab_upstream_internal_error_message(self):
        from nano_banana.providers.errors import is_bananalab_upstream_internal_error_message

        self.assertTrue(
            is_bananalab_upstream_internal_error_message(
                "Generation failed: upstream provider internal error"
            )
        )
        self.assertFalse(is_bananalab_upstream_internal_error_message("Project is paused."))

    def test_user_generation_status_upstream_streak(self):
        from nano_banana.status.user import build_user_generation_status

        status = build_user_generation_status(
            [
                {"id": 2, "status": "failed", "error": "Generation failed: upstream provider internal error"},
                {"id": 1, "status": "failed", "error": "Generation failed: upstream provider internal error"},
                {"id": 0, "status": "completed", "error": None},
            ]
        )
        self.assertEqual(status["state"], "degraded")
        self.assertEqual(status["fail_streak"], 2)
        self.assertIn("Google upstream", status["message"])

    def test_user_generation_status_last_success_ok(self):
        from nano_banana.status.user import build_user_generation_status

        status = build_user_generation_status(
            [
                {"id": 3, "status": "completed", "error": None},
                {"id": 2, "status": "failed", "error": "Generation failed: upstream provider internal error"},
            ]
        )
        self.assertEqual(status["state"], "ok")

    def test_google_gemini_status_filters_active_incident(self):
        from nano_banana.status import google as gcs

        sample = [
            {
                "id": "1",
                "external_desc": "Vertex AI Gemini API customers experienced increased error rates.",
                "begin": "2026-09-11T10:00:00+00:00",
                "end": None,
            },
            {
                "id": "2",
                "external_desc": "Cloud Storage bucket listing delays",
                "begin": "2026-09-11T10:00:00+00:00",
                "end": None,
            },
        ]

        def fake_fetch():
            return sample

        gcs._cache["checked_at"] = None
        original = gcs._fetch_incidents
        gcs._fetch_incidents = fake_fetch
        try:
            status = gcs.get_google_gemini_status(force_refresh=True)
        finally:
            gcs._fetch_incidents = original

        self.assertTrue(status["fetch_ok"])
        self.assertTrue(status["has_active_incident"])
        self.assertEqual(len(status["active_incidents"]), 1)
        self.assertIn("Gemini", status["active_incidents"][0]["title"])


class TestPublicServiceStatus(unittest.TestCase):
    def test_fallback_still_returns_service_cards(self):
        from unittest.mock import patch

        from nano_banana.status.services import build_public_service_status

        with patch(
            "nano_banana.status.services._build_public_service_status",
            side_effect=RuntimeError("boom"),
        ):
            payload = build_public_service_status(user_id=1)

        self.assertEqual(payload["state"], "unknown")
        ids = [svc["id"] for svc in payload["services"]]
        self.assertEqual(ids, ["moonez", "google_gemini"])


if __name__ == "__main__":
    unittest.main()
