from unittest.mock import patch

from rest_framework.test import APITestCase

from apps.account.models import User
from apps.journal.models import Journal, SharedJournalPlatform
from apps.platforms.models import LinkCheckLog, Platform
from apps.platforms.services import register_link_url


class PlatformStructuralLinksTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0,
            full_name="Sistema links",
            email="links@test.local",
            is_superadmin=True,
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_platform_creation_requires_public_url(self):
        response = self.client.post(
            "/api/platforms/", {"name": "Sin URL"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Platform.objects.filter(name="sin url").exists())

    def test_platform_creation_registers_public_url(self):
        response = self.client.post(
            "/api/platforms/",
            {"name": "Con URL", "public_url": "https://8.8.8.8/platform"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        log = LinkCheckLog.objects.get(
            platform_id=response.data["id"],
            journal_platform__isnull=True,
            url="https://8.8.8.8/platform",
        )
        self.assertFalse(log.is_active)
        self.assertIsNone(log.last_check)

    @patch("apps.platforms.services._perform_link_check", return_value=(200, True))
    @patch("apps.platforms.services._validate_safe_http_url")
    def test_check_links_checks_general_and_contextual_urls(self, _safe, _check):
        platform = Platform.objects.create(name="Masivo", created_by=self.user)
        journal = Journal.objects.create(
            issn="9595-9595", title="Journal masivo", created_by=self.user
        )
        link = SharedJournalPlatform.objects.create(
            journal=journal, platform=platform, created_by=self.user
        )
        register_link_url(
            platform=platform, url="https://8.8.8.8/platform", user=self.user
        )
        register_link_url(
            platform=platform, journal_platform=link,
            url="https://8.8.8.8/journal", user=self.user,
        )

        response = self.client.post(
            f"/api/platforms/{platform.pk}/check-links/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["checked"], 2)
        self.assertEqual(response.data["available"], 2)
        self.assertEqual(response.data["failed"], 0)
