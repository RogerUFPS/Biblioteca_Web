from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    Country,
    Institution,
    KnowledgeArea,
    Language,
    MaterialType,
)
from apps.platforms import models, services


class PlatformServicesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.system = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
        )

        cls.institution = Institution.objects.create(
            name="UFPS",
            created_by=cls.system,
        )

        cls.language = Language.objects.create(
            name="Español",
            abbreviation="es",
            created_by=cls.system,
        )

        cls.country = Country.objects.create(
            name="Colombia",
            abbreviation="co",
            emoji_flag="🇨🇴",
            created_by=cls.system,
        )

        cls.knowledge_area = KnowledgeArea.objects.create(
            name="Ingeniería",
            created_by=cls.system,
        )

        cls.material_type = MaterialType.objects.create(
            name="Artículos",
            created_by=cls.system,
        )

        cls.academic_program = AcademicProgram.objects.create(
            name="Ingeniería de Sistemas",
            created_by=cls.system,
        )

        cls.sintaxis = models.ValidSintaxis.objects.create(
            name="Sintaxis Estandar",
            booleans=["AND", "OR"],
            parenthesis=True,
            fields={"title": "ti"},
            created_by=cls.system,
        )

    def _setup_complete_platform(self):
        platform = models.Platform.objects.create(
            name="Plataforma Completa",
            url_image="https://example.org/platform.png",
            is_harvestable=True,
            base_api_url="https://api.completa.org",
            valid_sintaxis=self.sintaxis,
            created_by=self.system,
        )

        models.SharedPlatformSupport.objects.create(
            platform=platform,
            institution=self.institution,
            created_by=self.system,
        )

        models.SharedPlatformLanguage.objects.create(
            platform=platform,
            language=self.language,
            created_by=self.system,
        )

        models.SharedPlatformCountry.objects.create(
            platform=platform,
            country=self.country,
            created_by=self.system,
        )

        models.SharedPlatformKnowledgeArea.objects.create(
            platform=platform,
            knowledge_area=self.knowledge_area,
            created_by=self.system,
        )

        models.SharedPlatformMaterialType.objects.create(
            platform=platform,
            material_type=self.material_type,
            created_by=self.system,
        )

        models.SharedPlatformAcademicProgram.objects.create(
            platform=platform,
            academic_program=self.academic_program,
            created_by=self.system,
        )

        # La URL pública pertenece a LinkCheckLog,
        # no a Platform.
        models.LinkCheckLog.objects.create(
            platform=platform,
            url="https://www.plataforma-completa.org",
            fail_count=0,
            http_status_code=200,
            is_active=True,
            last_check=timezone.now(),
            created_by=self.system,
        )

        return platform

    def test_publish_platform_succeeds_when_complete(self):
        """Verifica que una plataforma con toda la ficha valida pase a PUBLICADO."""
        platform = self._setup_complete_platform()

        published = services.publish_platform(
            platform=platform,
            user=self.system,
        )

        self.assertEqual(
            published.status,
            models.Platform.Status.PUBLICADO,
        )

        self.assertEqual(
            published.validated_by,
            self.system,
        )

        self.assertIsNotNone(
            published.validated_at,
        )

    def test_non_harvestable_platform_can_be_published_without_api_url(self):
        platform = self._setup_complete_platform()
        platform.is_harvestable = False
        platform.base_api_url = None
        platform.save(update_fields=["is_harvestable", "base_api_url"])

        published = services.publish_platform(
            platform=platform,
            user=self.system,
        )

        self.assertEqual(published.status, models.Platform.Status.PUBLICADO)

    def test_harvestable_platform_cannot_be_published_without_api_url(self):
        platform = self._setup_complete_platform()
        platform.base_api_url = None
        platform.save(update_fields=["base_api_url"])

        with self.assertRaises(ValidationError) as context:
            services.publish_platform(platform=platform, user=self.system)

        self.assertIn("base_api_url", context.exception.detail)

    def test_publish_platform_fails_when_incomplete(self):
        """Verifica que la publicacion falle si faltan relaciones o campos obligatorios."""
        platform = models.Platform.objects.create(
            name="Plataforma Incompleta",
            created_by=self.system,
        )

        with self.assertRaises(ValidationError) as context:
            services.publish_platform(
                platform=platform,
                user=self.system,
            )

        errors = context.exception.detail

        # base_api_url ya no es obligatorio para publicar.
        self.assertNotIn(
            "base_api_url",
            errors,
        )

        # La URL pública sí es obligatoria y proviene
        # de LinkCheckLog.
        self.assertIn(
            "url",
            errors,
        )

        self.assertIn(
            "valid_sintaxis",
            errors,
        )

        self.assertIn(
            "institutions",
            errors,
        )

    def test_publish_requires_public_url_to_be_verified(self):
        platform = self._setup_complete_platform()
        services.register_link_url(
            platform=platform,
            url="https://example.org/pending",
            user=self.system,
        )

        with self.assertRaises(ValidationError) as context:
            services.publish_platform(platform=platform, user=self.system)

        self.assertIn("debe verificarse", str(context.exception.detail["url"]))

    def test_publish_rejects_unavailable_public_url(self):
        platform = self._setup_complete_platform()
        models.LinkCheckLog.objects.create(
            platform=platform,
            url="https://example.org/unavailable",
            is_active=False,
            last_check=timezone.now(),
            created_by=self.system,
        )

        with self.assertRaises(ValidationError) as context:
            services.publish_platform(platform=platform, user=self.system)

        self.assertIn("no se encuentra disponible", str(context.exception.detail["url"]))

    def test_registered_url_starts_unverified(self):
        platform = models.Platform.objects.create(
            name="Plataforma pendiente", created_by=self.system,
        )
        log = services.register_link_url(
            platform=platform,
            url="https://example.org/pending",
            user=self.system,
        )

        self.assertFalse(log.is_active)
        self.assertIsNone(log.last_check)
        self.assertEqual(services.link_verification_status(log), "unverified")

    def test_lifecycle_transitions_obsolete_and_reactivate(self):
        """Verifica la transicion de PUBLICADO a OBSOLETO y reactivacion a BORRADOR."""
        platform = self._setup_complete_platform()

        services.publish_platform(
            platform=platform,
            user=self.system,
        )
        original_start = platform.start_period

        obsolete = services.mark_platform_obsolete(
            platform=platform,
            user=self.system,
        )

        self.assertEqual(
            obsolete.status,
            models.Platform.Status.OBSOLETO,
        )

        self.assertIsNotNone(
            obsolete.validated_by,
        )
        self.assertEqual(obsolete.start_period, original_start)
        self.assertEqual(obsolete.finish_period, timezone.localdate())

        reactivated = services.reactivate_platform(
            platform=platform,
            user=self.system,
        )

        self.assertEqual(
            reactivated.status,
            models.Platform.Status.BORRADOR,
        )

        self.assertIsNone(
            reactivated.validated_by,
        )

        self.assertIsNone(
            reactivated.validated_at,
        )
        self.assertEqual(reactivated.start_period, original_start)
        self.assertIsNone(reactivated.finish_period)

    def test_validate_safe_http_url_blocks_internal_and_private_ips(self):
        """Verifica que la validacion SSRF rechace localhost y redes privadas."""
        with self.assertRaises(ValidationError):
            services._validate_safe_http_url(
                "http://localhost:8000/api"
            )

        with self.assertRaises(ValidationError):
            services._validate_safe_http_url(
                "http://127.0.0.1/test"
            )

        with self.assertRaises(ValidationError):
            services._validate_safe_http_url(
                "http://192.168.1.1/api"
            )

        with self.assertRaises(ValidationError):
            services.validate_safe_http_url(
                "http://metadata.google.internal/computeMetadata/v1/"
            )

    @patch("apps.platforms.services._perform_link_check")
    @patch("apps.platforms.services._validate_safe_http_url")
    def test_check_platform_link_records_consecutive_fail_count(
        self,
        mock_validate,
        mock_check,
    ):
        """Verifica el incremento y reinicio de fail_count en chequeos sucesivos."""
        platform = models.Platform.objects.create(
            name="Plataforma Link Test",
            created_by=self.system,
        )

        public_url = "https://www.plataforma-test.org"

        mock_check.return_value = (500, False)

        log1 = services.check_platform_link(
            platform=platform,
            user=self.system,
            url=public_url,
        )

        self.assertEqual(
            log1.fail_count,
            1,
        )

        self.assertFalse(
            log1.is_active,
        )

        self.assertEqual(
            log1.url,
            public_url,
        )

        log2 = services.check_platform_link(
            platform=platform,
            user=self.system,
            url=public_url,
        )

        self.assertEqual(
            log2.fail_count,
            2,
        )

        mock_check.return_value = (200, True)

        log3 = services.check_platform_link(
            platform=platform,
            user=self.system,
            url=public_url,
        )

        self.assertEqual(
            log3.fail_count,
            0,
        )

        self.assertTrue(
            log3.is_active,
        )
