import datetime
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    Country,
    Institution,
    KnowledgeArea,
    Language,
    MaterialType,
)
from apps.platforms.models import (
    LinkCheckLog,
    Platform,
    SharedPlatformAcademicProgram,
    SharedPlatformCountry,
    SharedPlatformKnowledgeArea,
    SharedPlatformLanguage,
    SharedPlatformMaterialType,
    SharedPlatformSupport,
    ValidSintaxis,
)


class PlatformModelsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.system = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
        )

    def test_platform_encryption_and_decryption(self):
        """Verifica que la API Key se almacene cifrada y se descifre correctamente."""
        platform = Platform.objects.create(
            name="Scopus Test",
            is_harvestable=True,
            base_api_url="https://api.elsevier.com",
            created_by=self.system,
        )
        raw_key = "secret-super-api-key-12345"
        platform.set_api_key(raw_key)
        platform.save()

        platform.refresh_from_db()
        self.assertIsNotNone(platform.encrypted_api_key)
        self.assertNotEqual(platform.encrypted_api_key, raw_key)
        self.assertEqual(platform.get_api_key(), raw_key)

    def test_platform_name_normalized_to_lowercase(self):
        """Verifica que AuditableModel normalice el nombre a minúsculas."""
        platform = Platform.objects.create(
            name="  IEEE Xplore  ",
            created_by=self.system,
        )
        self.assertEqual(platform.name, "ieee xplore")

    def test_platform_name_case_insensitive_unique_constraint(self):
        """La base de datos debe rechazar nombres duplicados sin importar mayúsculas."""
        Platform.objects.create(
            name="springer link",
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Platform.objects.create(
                    name="SPRINGER LINK",
                    created_by=self.system,
                )

    def test_valid_sintaxis_creation_and_soft_delete(self):
        """Verifica ciclo de vida y campos semiestructurados de ValidSintaxis."""
        sintaxis = ValidSintaxis.objects.create(
            name="Sintaxis Booleana Estandar",
            booleans=["AND", "OR", "NOT"],
            parenthesis=True,
            fields={"title": "ti", "abstract": "ab"},
            created_by=self.system,
        )
        self.assertEqual(sintaxis.name, "sintaxis booleana estandar")
        self.assertTrue(sintaxis.parenthesis)

        sintaxis.soft_delete(user=self.system, explanation="Ya no se utiliza")
        self.assertTrue(sintaxis.is_deleted)
        self.assertFalse(ValidSintaxis.objects.filter(pk=sintaxis.pk).exists())
        self.assertTrue(ValidSintaxis.all_objects.filter(pk=sintaxis.pk).exists())

    def test_link_check_log_fail_count_and_ordering(self):
        """Verifica el registro de comprobaciones de enlace y su ordenamiento."""
        platform = Platform.objects.create(
            name="Dialnet Test",
            is_harvestable=True,
            base_api_url="https://dialnet.unirioja.es",
            created_by=self.system,
        )
        log1 = LinkCheckLog.objects.create(
            platform=platform,
            url=platform.base_api_url,
            fail_count=1,
            http_status_code=500,
            is_active=False,
            last_check=timezone.now() - datetime.timedelta(minutes=1),
            created_by=self.system,
        )
        log2 = LinkCheckLog.objects.create(
            platform=platform,
            url=platform.base_api_url,
            fail_count=0,
            http_status_code=200,
            is_active=True,
            last_check=timezone.now(),
            created_by=self.system,
        )
        logs = list(platform.link_check_logs.all())
        self.assertEqual(logs[0].pk, log2.pk)
        self.assertEqual(logs[1].pk, log1.pk)

    def test_link_check_log_cannot_be_active_without_check(self):
        platform = Platform.objects.create(
            name="Enlace sin verificar",
            created_by=self.system,
        )

        with self.assertRaises(ValidationError):
            LinkCheckLog.objects.create(
                platform=platform,
                url="https://example.org/pending",
                is_active=True,
                created_by=self.system,
            )

    def test_shared_platform_unique_constraint(self):
        """Verifica que no se dupliquen relaciones compuestas entre plataforma y catalogo."""
        platform = Platform.objects.create(
            name="Scielo Test",
            created_by=self.system,
        )
        country = Country.objects.create(
            name="colombia",
            abbreviation="co",
            emoji_flag="🇨🇴",
            created_by=self.system,
        )
        SharedPlatformCountry.objects.create(
            platform=platform,
            country=country,
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedPlatformCountry.objects.create(
                    platform=platform,
                    country=country,
                    created_by=self.system,
                )

    def test_platform_dates_are_automatic_and_domain_validated(self):
        platform = Platform.objects.create(
            name="Fechas automáticas",
            start_period=datetime.date(2000, 1, 1),
            finish_period=datetime.date(2001, 1, 1),
            created_by=self.system,
        )

        self.assertEqual(platform.start_period, timezone.localdate())
        self.assertIsNone(platform.finish_period)

        platform.finish_period = platform.start_period - datetime.timedelta(days=1)
        with self.assertRaises(ValidationError):
            platform.save(update_fields=["finish_period"])
