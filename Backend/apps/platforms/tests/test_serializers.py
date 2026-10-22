from unittest.mock import patch

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
    SharedAcademicProgramKnowledgeArea,
)
from apps.platforms import models, serializers


class PlatformSerializersTests(TestCase):
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

        cls.knowledge_area_secondary = KnowledgeArea.objects.create(
            name="Ciencias de la Computación",
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

        cls.academic_program_secondary = AcademicProgram.objects.create(
            name="Ingeniería Civil",
            created_by=cls.system,
        )

        SharedAcademicProgramKnowledgeArea.objects.create(
            academic_program=cls.academic_program,
            knowledge_area=cls.knowledge_area,
            created_by=cls.system,
        )

        SharedAcademicProgramKnowledgeArea.objects.create(
            academic_program=cls.academic_program_secondary,
            knowledge_area=cls.knowledge_area,
            created_by=cls.system,
        )

        SharedAcademicProgramKnowledgeArea.objects.create(
            academic_program=cls.academic_program_secondary,
            knowledge_area=cls.knowledge_area_secondary,
            created_by=cls.system,
        )

        cls.sintaxis = models.ValidSintaxis.objects.create(
            name="Sintaxis Estandar",
            booleans=["AND", "OR"],
            parenthesis=True,
            fields={"title": "ti"},
            created_by=cls.system,
        )

    def test_platform_serializer_create_with_api_key_and_relations(self):
        """Persiste la API Key cifrada y sincroniza relaciones."""
        data = {
            "name": "Redalyc",
            "public_url": "https://8.8.8.8/redalyc",
            "is_harvestable": True,
            "base_api_url": "https://www.redalyc.org",
            "api_key": "my-plain-text-key",
            "valid_sintaxis": self.sintaxis.pk,
            "institutions": [self.institution.pk],
            "languages": [self.language.pk],
            "countries": [self.country.pk],
            "material_types": [self.material_type.pk],
            "academic_programs": [self.academic_program.pk],
        }

        serializer = serializers.PlatformSerializer(data=data)

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        platform = serializer.save(
            created_by=self.system,
        )

        self.assertEqual(
            platform.status,
            models.Platform.Status.BORRADOR,
        )

        self.assertEqual(
            platform.get_api_key(),
            "my-plain-text-key",
        )

        self.assertEqual(
            platform.support_links.count(),
            1,
        )

        self.assertEqual(
            platform.country_links.count(),
            1,
        )

        self.assertEqual(
            platform.academic_program_links.count(),
            1,
        )

        self.assertEqual(
            platform.knowledge_area_links.count(),
            0,
        )

        self.assertEqual(
            list(
                platform.knowledge_area_links.values_list(
                    "knowledge_area_id",
                    flat=True,
                )
            ),
            [],
        )

    def test_platform_serializer_creates_manual_academic_classification(
        self,
    ):
        """Los programas pueden aportarse manualmente a la Platform."""
        data = {
            "name": "Scielo",
            "public_url": "https://8.8.8.8/scielo",
            "academic_programs": [
                self.academic_program.pk,
                self.academic_program_secondary.pk,
            ],
        }

        serializer = serializers.PlatformSerializer(
            data=data,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        platform = serializer.save(
            created_by=self.system,
        )

        self.assertEqual(
            set(
                platform.academic_program_links.values_list(
                    "academic_program_id",
                    flat=True,
                )
            ),
            {self.academic_program.pk, self.academic_program_secondary.pk},
        )

        self.assertEqual(
            set(
                platform.knowledge_area_links.values_list(
                    "knowledge_area_id",
                    flat=True,
                )
            ),
            set(),
        )

        data = serializers.PlatformSerializer(
            platform,
        ).data

        self.assertEqual(
            {item["id"] for item in data["knowledge_areas"]},
            set(),
        )

    def test_platform_serializer_accepts_knowledge_areas_as_manual_input(
        self,
    ):
        """Las áreas y programas pueden coexistir con fuentes derivadas."""
        data = {
            "name": "JSTOR",
            "public_url": "https://8.8.8.8/jstor",
            "knowledge_areas": [
                self.knowledge_area.pk,
            ],
            "academic_programs": [
                self.academic_program.pk,
            ],
        }

        serializer = serializers.PlatformSerializer(
            data=data,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        self.assertIn(
            "knowledge_areas",
            serializer.validated_data,
        )
        self.assertIn(
            "academic_programs",
            serializer.validated_data,
        )

        platform = serializer.save(
            created_by=self.system,
        )

        self.assertEqual(
            list(
                platform.knowledge_area_links.values_list(
                    "knowledge_area_id",
                    flat=True,
                )
            ),
            [self.knowledge_area.pk],
        )

    def test_platform_serializer_allows_null_api_key_without_base_api_url(
        self,
    ):
        """Una plataforma de referencia puede existir sin API ni API Key."""
        data = {
            "name": "Plataforma Referencia",
            "public_url": "https://8.8.8.8/reference",
            "base_api_url": None,
            "api_key": None,
        }

        serializer = serializers.PlatformSerializer(
            data=data,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        platform = serializer.save(
            created_by=self.system,
        )

        self.assertIsNone(
            platform.base_api_url,
        )

        self.assertFalse(platform.is_harvestable)
        self.assertFalse(serializer.data["is_harvestable"])

        self.assertIsNone(
            platform.encrypted_api_key,
        )

        self.assertEqual(
            platform.get_api_key(),
            "",
        )

    def test_platform_serializer_allows_base_api_url_without_api_key(
        self,
    ):
        """Una plataforma puede tener API sin requerir una API Key."""
        data = {
            "name": "API Publica",
            "public_url": "https://8.8.8.8/public-api",
            "is_harvestable": True,
            "base_api_url": "https://api.publica.org",
            "api_key": None,
        }

        serializer = serializers.PlatformSerializer(
            data=data,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        platform = serializer.save(
            created_by=self.system,
        )

        self.assertEqual(
            platform.base_api_url,
            "https://api.publica.org",
        )

        self.assertIsNone(
            platform.encrypted_api_key,
        )

    def test_platform_serializer_rejects_api_key_without_base_api_url(
        self,
    ):
        """Nunca debe existir una API Key asociada a ninguna API base."""
        data = {
            "name": "Configuracion Invalida",
            "public_url": "https://8.8.8.8/invalid-config",
            "base_api_url": None,
            "api_key": "orphan-key",
        }

        serializer = serializers.PlatformSerializer(
            data=data,
        )

        self.assertFalse(
            serializer.is_valid(),
        )

        self.assertIn(
            "base_api_url",
            serializer.errors,
        )

    def test_platform_serializer_clears_api_key_when_sent_as_null(
        self,
    ):
        """Enviar api_key=null elimina una API Key previamente configurada."""
        platform = models.Platform.objects.create(
            name="Plataforma Con API Key",
            is_harvestable=True,
            base_api_url="https://api.example.org",
            created_by=self.system,
        )

        platform.set_api_key(
            "secret-key",
        )

        platform.save()

        data = {
            "api_key": None,
        }

        serializer = serializers.PlatformSerializer(
            instance=platform,
            data=data,
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        updated = serializer.save(
            updated_by=self.system,
        )

        self.assertIsNone(
            updated.encrypted_api_key,
        )

        self.assertEqual(
            updated.get_api_key(),
            "",
        )

    def test_platform_serializer_rejects_removing_base_api_url_with_existing_api_key(
        self,
    ):
        """No se puede eliminar base_api_url mientras exista una API Key."""
        platform = models.Platform.objects.create(
            name="API Configurada",
            is_harvestable=True,
            base_api_url="https://api.example.org",
            created_by=self.system,
        )

        platform.set_api_key(
            "secret-key",
        )

        platform.save()

        data = {
            "base_api_url": None,
        }

        serializer = serializers.PlatformSerializer(
            instance=platform,
            data=data,
            partial=True,
        )

        self.assertFalse(
            serializer.is_valid(),
        )

        self.assertIn(
            "base_api_url",
            serializer.errors,
        )

    def test_platform_serializer_allows_removing_base_api_url_and_api_key_together(
        self,
    ):
        """Se pueden eliminar simultáneamente base_api_url y API Key."""
        platform = models.Platform.objects.create(
            name="API A Eliminar",
            is_harvestable=True,
            base_api_url="https://api.example.org",
            created_by=self.system,
        )

        platform.set_api_key(
            "secret-key",
        )

        platform.save()

        data = {
            "is_harvestable": False,
            "base_api_url": None,
            "api_key": None,
        }

        serializer = serializers.PlatformSerializer(
            instance=platform,
            data=data,
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        updated = serializer.save(
            updated_by=self.system,
        )

        self.assertIsNone(
            updated.base_api_url,
        )

        self.assertIsNone(
            updated.encrypted_api_key,
        )

    def test_platform_serializer_patch_preserves_manual_academic_relations(
        self,
    ):
        """Un PATCH posterior conserva las relaciones manuales no enviadas."""
        platform = models.Platform.objects.create(
            name="Plataforma Existente",
            created_by=self.system,
        )

        serializer = serializers.PlatformSerializer(
            instance=platform,
            data={
                "academic_programs": [
                    self.academic_program.pk,
                ],
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system,
        )

        serializer = serializers.PlatformSerializer(
            instance=platform,
            data={
                "name": "Plataforma Existente Actualizada",
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        updated = serializer.save(
            updated_by=self.system,
        )

        self.assertEqual(
            list(
                updated.academic_program_links.values_list(
                    "academic_program_id",
                    flat=True,
                )
            ),
            [self.academic_program.pk],
        )

        self.assertEqual(
            list(
                updated.knowledge_area_links.values_list(
                    "knowledge_area_id",
                    flat=True,
                )
            ),
            [],
        )

    def test_platform_serializer_empty_academic_programs_removes_manual_origin(
        self,
    ):
        """Una lista vacía retira solo la contribución manual."""
        platform = models.Platform.objects.create(
            name="Plataforma Clasificada",
            created_by=self.system,
        )

        serializer = serializers.PlatformSerializer(
            instance=platform,
            data={
                "academic_programs": [
                    self.academic_program.pk,
                ],
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system,
        )

        self.assertEqual(
            platform.academic_program_links.count(),
            1,
        )

        self.assertEqual(
            platform.knowledge_area_links.count(),
            0,
        )

        serializer = serializers.PlatformSerializer(
            instance=platform,
            data={
                "academic_programs": [],
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        updated = serializer.save(
            updated_by=self.system,
        )

        self.assertEqual(
            updated.academic_program_links.count(),
            0,
        )

        self.assertEqual(
            updated.knowledge_area_links.count(),
            0,
        )

    def test_sync_relations_deduplicates_repeated_ids(self):
        """Una lista con IDs repetidos no debe insertar relaciones duplicadas."""
        platform = models.Platform.objects.create(
            name="Test Duplicates",
            created_by=self.system,
        )

        data = {
            "institutions": [
                self.institution.pk,
                self.institution.pk,
            ],
        }

        serializer = serializers.PlatformSerializer(
            instance=platform,
            data=data,
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system,
        )

        self.assertEqual(
            platform.support_links.count(),
            1,
        )

    def test_archived_platform_restored_via_serializer_resets_to_draft(
        self,
    ):
        """Una plataforma archivada recreada por nombre debe volver a BORRADOR."""
        platform = models.Platform.objects.create(
            name="Plataforma Archivada",
            status=models.Platform.Status.PUBLICADO,
            validated_by=self.system,
            created_by=self.system,
        )

        platform.soft_delete(
            user=self.system,
            explanation="Eliminada para test",
        )

        data = {
            "name": "Plataforma Archivada",
            "public_url": "https://8.8.8.8/reactivated",
            "is_harvestable": True,
            "base_api_url": "https://reactivada.org",
        }

        serializer = serializers.PlatformSerializer(
            data=data,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        restored = serializer.save(
            created_by=self.system,
        )

        self.assertEqual(
            restored.pk,
            platform.pk,
        )

        self.assertFalse(
            restored.is_deleted,
        )

        self.assertEqual(
            restored.status,
            models.Platform.Status.BORRADOR,
        )

        self.assertIsNone(
            restored.validated_by,
        )

        self.assertIsNone(
            restored.validated_at,
        )

    def test_public_serializer_excludes_sensitive_and_audit_fields(
        self,
    ):
        """PlatformPublicSerializer no debe exponer información interna."""
        platform = models.Platform.objects.create(
            name="Plataforma Publica",
            is_harvestable=True,
            base_api_url="https://publica.org",
            created_by=self.system,
        )

        platform.set_api_key(
            "secret123",
        )

        platform.save()

        serializer = serializers.PlatformPublicSerializer(
            platform,
        )

        data = serializer.data

        self.assertNotIn(
            "encrypted_api_key",
            data,
        )

        self.assertNotIn(
            "api_key",
            data,
        )

        self.assertNotIn(
            "created_by",
            data,
        )

        self.assertNotIn(
            "delete_explanation",
            data,
        )

        self.assertNotIn(
            "validated_by",
            data,
        )

        self.assertIn(
            "link_status",
            data,
        )

        self.assertIsNone(
            data["link_status"]["is_active"],
        )

    def test_platform_urls_use_latest_non_deleted_general_log(self):
        platform = models.Platform.objects.create(
            name="URL pública",
            is_harvestable=True,
            base_api_url="https://api.example.org",
            created_by=self.system,
        )
        old_log = models.LinkCheckLog.objects.create(
            platform=platform,
            url="https://public.example.org/old",
            last_check=timezone.now(),
            created_by=self.system,
        )
        latest_log = models.LinkCheckLog.objects.create(
            platform=platform,
            url="https://public.example.org/current",
            last_check=timezone.now(),
            created_by=self.system,
        )
        latest_log.soft_delete(self.system, "Registro descartado")

        admin_data = serializers.PlatformSerializer(platform).data
        public_data = serializers.PlatformPublicSerializer(platform).data

        self.assertEqual(admin_data["public_url"], old_log.url)
        self.assertEqual(public_data["public_url"], old_log.url)
        self.assertNotEqual(public_data["public_url"], platform.base_api_url)

    def test_public_url_is_a_virtual_writable_field(self):
        serializer = serializers.PlatformSerializer(
            data={
                "name": "Solo lectura",
                "public_url": "https://8.8.8.8/public",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        platform = serializer.save(created_by=self.system)
        self.assertFalse(hasattr(platform, "public_url"))
        self.assertTrue(
            models.LinkCheckLog.objects.filter(
                platform=platform,
                journal_platform__isnull=True,
                url="https://8.8.8.8/public",
            ).exists()
        )

    def test_lifecycle_dates_are_read_only_and_reject_manual_input(self):
        serializer = serializers.PlatformSerializer(
            data={
                "name": "Fechas administradas",
                "public_url": "https://8.8.8.8/managed-dates",
                "start_period": "2000-01-01",
                "finish_period": "2001-01-01",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("start_period", serializer.errors)
        self.assertIn("finish_period", serializer.errors)
        self.assertTrue(serializer.fields["start_period"].read_only)
        self.assertTrue(serializer.fields["finish_period"].read_only)

    def test_harvestable_platform_requires_base_api_url(self):
        serializer = serializers.PlatformSerializer(
            data={
                "name": "Sin API",
                "public_url": "https://8.8.8.8/without-api",
                "is_harvestable": True,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("base_api_url", serializer.errors)

    def test_non_harvestable_platform_rejects_harvesting_configuration(self):
        serializer = serializers.PlatformSerializer(
            data={
                "name": "Configuración contradictoria",
                "public_url": "https://8.8.8.8/contradictory",
                "is_harvestable": False,
                "base_api_url": "https://api.example.org",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("is_harvestable", serializer.errors)

    def test_disabling_harvesting_clears_api_url_and_key(self):
        platform = models.Platform.objects.create(
            name="Cosecha a desactivar",
            is_harvestable=True,
            base_api_url="https://api.example.org",
            created_by=self.system,
        )
        platform.set_api_key("secret")
        platform.save(update_fields=["encrypted_api_key"])
        serializer = serializers.PlatformSerializer(
            platform,
            data={"is_harvestable": False},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save(updated_by=self.system)

        self.assertFalse(updated.is_harvestable)
        self.assertIsNone(updated.base_api_url)
        self.assertIsNone(updated.encrypted_api_key)

    def test_public_url_patch_preserves_history_without_duplicates(self):
        platform = models.Platform.objects.create(
            name="Historial público",
            created_by=self.system,
        )
        models.LinkCheckLog.objects.create(
            platform=platform,
            url="https://8.8.8.8/first",
            created_by=self.system,
        )

        unchanged = serializers.PlatformSerializer(
            platform,
            data={"public_url": "https://8.8.8.8/first"},
            partial=True,
        )
        self.assertTrue(unchanged.is_valid(), unchanged.errors)
        unchanged.save(updated_by=self.system)
        self.assertEqual(platform.link_check_logs.count(), 1)

        changed = serializers.PlatformSerializer(
            platform,
            data={"public_url": "https://8.8.8.8/second"},
            partial=True,
        )
        self.assertTrue(changed.is_valid(), changed.errors)
        changed.save(updated_by=self.system)

        self.assertEqual(platform.link_check_logs.count(), 2)
        self.assertEqual(
            serializers.PlatformSerializer(platform).data["public_url"],
            "https://8.8.8.8/second",
        )

    @patch(
        "apps.platforms.serializers.services.register_link_url",
        side_effect=RuntimeError("link log failed"),
    )
    def test_platform_creation_rolls_back_if_public_url_log_fails(self, _mock):
        serializer = serializers.PlatformSerializer(
            data={
                "name": "Creación atómica",
                "public_url": "https://8.8.8.8/atomic",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.assertRaises(RuntimeError):
            serializer.save(created_by=self.system)

        self.assertFalse(
            models.Platform.objects.filter(name="creación atómica").exists()
        )
