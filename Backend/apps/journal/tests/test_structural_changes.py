from datetime import date

from django.core.exceptions import FieldDoesNotExist
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.account.models import User
from apps.journal import models, services
from apps.platforms.models import LinkCheckLog, Platform


class JournalStructuralModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0, full_name="Sistema estructural", email="structural@test.local"
        )

    def test_journal_uses_publication_date_not_global_periods(self):
        self.assertIsNotNone(models.Journal._meta.get_field("publication_date"))
        for field_name in ("start_period", "finish_period", "license"):
            with self.assertRaises(FieldDoesNotExist):
                models.Journal._meta.get_field(field_name)

    def test_license_is_many_to_many_through_auditable_relation(self):
        journal = models.Journal.objects.create(
            issn="9191-9191", title="Journal", created_by=self.user
        )
        first = models.License.objects.create(name="CC BY", created_by=self.user)
        second = models.License.objects.create(name="CC0", created_by=self.user)
        models.SharedJournalLicense.objects.create(
            journal=journal, license=first, created_by=self.user
        )
        models.SharedJournalLicense.objects.create(
            journal=journal, license=second, created_by=self.user
        )
        self.assertEqual(journal.license_links.count(), 2)

    def test_relation_dates_follow_independent_lifecycle_rules(self):
        platform = Platform.objects.create(
            name="Temporal", created_by=self.user,
        )
        today = timezone.localdate()
        services.validate_journal_platform_period(
            platform=platform,
            start_period=today,
            finish_period=None,
        )
        with self.assertRaises(ValidationError):
            services.validate_journal_platform_period(
                platform=platform,
                start_period=date(2000, 1, 1),
                finish_period=None,
            )
        with self.assertRaises(ValidationError):
            services.validate_journal_platform_period(
                platform=platform,
                start_period=today,
                finish_period=date(2000, 1, 1),
            )

    def test_create_journal_requires_context_and_registers_url(self):
        platform = Platform.objects.create(name="Origen", created_by=self.user)
        with self.assertRaises(TypeError):
            services.create_journal(
                issn="9696-9696", title="Sin contexto", user=self.user
            )

        journal = services.create_journal(
            issn="9696-9696",
            title="Con contexto",
            user=self.user,
            platform_id=platform.pk,
            journal_url="https://8.8.8.8/source",
        )
        link = journal.platform_links.get(platform=platform)
        log = LinkCheckLog.objects.get(journal_platform=link)
        self.assertEqual(log.platform_id, platform.pk)
        self.assertEqual(log.url, "https://8.8.8.8/source")


class JournalStructuralAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0,
            full_name="Sistema API",
            email="structural-api@test.local",
            is_superadmin=True,
        )
        cls.platform = Platform.objects.create(
            name="API estructural",
            created_by=cls.user,
        )
        cls.license_a = models.License.objects.create(name="CC BY", created_by=cls.user)
        cls.license_b = models.License.objects.create(name="CC0", created_by=cls.user)

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_new_journal_can_be_incomplete_but_new_platform_link_requires_url(self):
        response = self.client.post(
            "/api/journals/",
            {"issn": "9292-9292", "title": "Sin plataforma"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            "/api/journals/",
            {
                "issn": "9292-9293", "title": "Sin URL",
                "platforms": [{"platform": self.platform.pk}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_journal_url_is_stored_only_in_link_log(self):
        response = self.client.post(
            "/api/journals/",
            {
                "issn": "9393-9393", "title": "Con URL",
                "publication_date": "2020-02-01",
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/journal",
                }],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        journal = models.Journal.objects.get(pk=response.data["id"])
        link = journal.platform_links.get(platform=self.platform)
        self.assertTrue(LinkCheckLog.objects.filter(
            platform=self.platform,
            journal_platform=link,
            url="https://8.8.8.8/journal",
        ).exists())

    def test_api_rejects_manual_relation_dates(self):
        response = self.client.post(
            "/api/journals/",
            {
                "issn": "9393-9394",
                "title": "Fechas manuales",
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/manual-relation-dates",
                    "start_period": "2020-01-01",
                    "finish_period": "2021-01-01",
                }],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("platforms", response.data)

    def test_failed_publish_rolls_back_license_synchronization(self):
        journal = models.Journal.objects.create(
            issn="9494-9494", title="Licencias", created_by=self.user
        )
        response = self.client.post(
            f"/api/journals/{journal.pk}/publish/",
            {"licenses": [self.license_a.pk, self.license_b.pk]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(journal.license_links.count(), 0)

        response = self.client.post(
            f"/api/journals/{journal.pk}/publish/", {"licenses": []}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(journal.license_links.count(), 0)
