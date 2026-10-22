from datetime import date
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    Country,
    Editorial,
    KnowledgeArea,
    Language,
    MaterialType,
    SharedAcademicProgramKnowledgeArea,
)
from apps.journal import models, serializers
from apps.platforms.models import LinkCheckLog, Platform


class JournalSerializersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.system = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
        )

        cls.editorial = Editorial.objects.create(
            name="Springer",
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

        cls.knowledge_area_secondary = KnowledgeArea.objects.create(
            name="Tecnología",
            created_by=cls.system,
        )

        cls.academic_program_secondary = AcademicProgram.objects.create(
            name="Ingeniería Electrónica",
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

        cls.platform = Platform.objects.create(
            name="Scopus Test",
            is_harvestable=True,
            base_api_url="https://api.scopus.test",
            status=Platform.Status.PUBLICADO,
            created_by=cls.system,
        )

    def _journal(self, **kwargs):
        data = {
            "issn": "1234-5678",
            "title": "Journal de Prueba",
            "created_by": self.system,
        }

        data.update(kwargs)

        return models.Journal.objects.create(
            **data
        )

    # ==========================================================================
    # CREACIÓN Y NORMALIZACIÓN
    # ==========================================================================

    def test_publication_fields_are_read_only(self):
        serializer = serializers.JournalSerializer()

        for field_name in ("active", "validated_by", "validated_at"):
            self.assertTrue(serializer.fields[field_name].read_only)

    def test_create_ignores_client_controlled_publication_fields(self):
        serializer = serializers.JournalSerializer(
            data={
                "issn": "1010-2020",
                "title": "Journal pendiente",
                "active": True,
                "validated_by": self.system.pk,
                "validated_at": timezone.now().isoformat(),
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/pending",
                }],
            },
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        journal = serializer.save(created_by=self.system)

        self.assertFalse(journal.active)
        self.assertIsNone(journal.validated_by)
        self.assertIsNone(journal.validated_at)

    def test_journal_serializer_create_with_all_relations(self):
        """
        Crea una revista y sincroniza las seis relaciones configuradas.
        """
        data = {
            "issn": "1234 567X",
            "title": "Journal de Ingeniería",
            "editorial": self.editorial.pk,
            "publication_date": "2020-01-01",
            "has_apc": False,
            "languages": [self.language.pk],
            "countries": [self.country.pk],
            "material_types": [self.material_type.pk],
            "academic_programs": [
                self.academic_program.pk
            ],
            "platforms": [
                {
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/engineering",
                    "has_full_text": True,
                }
            ],
        }

        serializer = serializers.JournalSerializer(
            data=data
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        journal = serializer.save(
            created_by=self.system
        )

        self.assertEqual(
            journal.issn,
            "1234-567X",
        )

        self.assertEqual(
            journal.language_links.count(),
            1,
        )

        self.assertEqual(
            journal.country_links.count(),
            1,
        )

        self.assertEqual(
            journal.knowledge_area_links.count(),
            1,
        )

        self.assertEqual(
            journal.material_type_links.count(),
            1,
        )

        self.assertEqual(
            journal.academic_program_links.count(),
            1,
        )

        self.assertEqual(
            journal.platform_links.count(),
            1,
        )

        platform_link = journal.platform_links.get(
            platform=self.platform
        )

        self.assertEqual(
            platform_link.start_period,
            timezone.localdate(),
        )

        self.assertEqual(
            platform_link.finish_period,
            None,
        )

        self.assertTrue(
            platform_link.has_full_text
        )

    def test_journal_serializer_normalizes_issn(self):
        """
        Normaliza espacios, guion y mayúsculas del ISSN.
        """
        serializer = serializers.JournalSerializer(
            data={
                "issn": " 1234 567x ",
                "title": "ISSN Normalizado",
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/normalized",
                }],
            }
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        self.assertEqual(
            serializer.validated_data["issn"],
            "1234-567X",
        )

    def test_journal_serializer_rejects_invalid_issn(self):
        """
        Rechaza ISSN con formato inválido.
        """
        serializer = serializers.JournalSerializer(
            data={
                "issn": "1234-56AB",
                "title": "ISSN Inválido",
            }
        )

        self.assertFalse(
            serializer.is_valid()
        )

        self.assertIn(
            "issn",
            serializer.errors,
        )

    # ==========================================================================
    # SINCRONIZACIÓN DE RELACIONES SIMPLES
    # ==========================================================================

    def test_sync_relations_deduplicates_repeated_ids(self):
        """
        IDs repetidos no generan relaciones duplicadas.
        """
        journal = self._journal(
            issn="2233-4455",
            title="Duplicates Test",
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "academic_programs": [
                    self.academic_program.pk,
                    self.academic_program.pk,
                ],
                "languages": [
                    self.language.pk,
                    self.language.pk,
                ],
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system
        )

        self.assertEqual(
            models.SharedJournalKnowledgeArea.objects.filter(
                journal=journal
            ).count(),
            1,
        )

        self.assertEqual(
            models.SharedJournalLanguage.objects.filter(
                journal=journal
            ).count(),
            1,
        )

    def test_knowledge_areas_are_derived_from_academic_programs(self):
        serializer = serializers.JournalSerializer(
            data={
                "issn": "2345-6789",
                "title": "Journal Derivación",
                "academic_programs": [
                    self.academic_program.pk,
                    self.academic_program_secondary.pk,
                ],
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/derived",
                }],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

        journal = serializer.save(created_by=self.system)

        self.assertEqual(
            set(
                journal.knowledge_area_links.values_list(
                    "knowledge_area_id",
                    flat=True,
                )
            ),
            {
                self.knowledge_area.pk,
                self.knowledge_area_secondary.pk,
            },
        )

    def test_knowledge_areas_accept_manual_selection(self):
        serializer = serializers.JournalSerializer(
            data={
                "issn": "3456-7890",
                "title": "Journal Read Only",
                "knowledge_areas": [self.knowledge_area_secondary.pk],
                "academic_programs": [self.academic_program.pk],
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/read-only",
                }],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        journal = serializer.save(created_by=self.system)

        self.assertEqual(
            set(journal.knowledge_area_links.values_list(
                "knowledge_area_id", flat=True,
            )),
            {self.knowledge_area.pk, self.knowledge_area_secondary.pk},
        )
        manual = journal.knowledge_area_links.get(
            knowledge_area=self.knowledge_area_secondary
        )
        self.assertTrue(manual.is_manual)
        self.assertFalse(manual.is_derived)

    def test_patch_without_academic_programs_preserves_derived_relations(self):
        journal = self._journal(
            issn="4567-8901",
            title="Journal Preserve",
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={"academic_programs": [self.academic_program.pk]},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.system)

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={"title": "Journal Preserve Updated"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.system)

        self.assertEqual(journal.academic_program_links.count(), 1)
        self.assertEqual(journal.knowledge_area_links.count(), 1)

    def test_empty_academic_programs_clears_derived_knowledge_areas(self):
        journal = self._journal(
            issn="5678-9012",
            title="Journal Clear",
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={"academic_programs": [self.academic_program.pk]},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.system)

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={"academic_programs": []},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.system)

        self.assertEqual(journal.academic_program_links.count(), 0)
        self.assertEqual(journal.knowledge_area_links.count(), 0)

    def test_changing_academic_programs_recalculates_knowledge_areas(self):
        journal = self._journal(
            issn="5789-0123",
            title="Journal Recalculate",
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={"academic_programs": [self.academic_program.pk]},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.system)

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "academic_programs": [
                    self.academic_program_secondary.pk,
                ]
            },
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.system)

        self.assertEqual(
            set(
                journal.knowledge_area_links.values_list(
                    "knowledge_area_id",
                    flat=True,
                )
            ),
            {
                self.knowledge_area.pk,
                self.knowledge_area_secondary.pk,
            },
        )

    def test_removed_relations_are_soft_deleted_and_hidden(self):
        """
        Una lista vacía elimina lógicamente las relaciones y
        las excluye de la representación activa.
        """
        journal = self._journal(
            issn="5566-7788",
            title="Soft Delete Relations",
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "languages": [
                    self.language.pk
                ],
                "platforms": [
                    {
                        "platform": self.platform.pk,
                        "has_full_text": True,
                        "journal_url": "https://8.8.8.8/soft-delete",
                    }
                ],
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system
        )

        language_link = (
            journal.language_links.get(
                language=self.language
            )
        )

        platform_link = (
            journal.platform_links.get(
                platform=self.platform
            )
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "languages": [],
                "platforms": [],
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system
        )

        language_link.refresh_from_db()
        platform_link.refresh_from_db()

        self.assertTrue(
            language_link.is_deleted
        )

        self.assertTrue(
            platform_link.is_deleted
        )

        self.assertFalse(
            models.SharedJournalLanguage.objects.filter(
                pk=language_link.pk
            ).exists()
        )

        self.assertFalse(
            models.SharedJournalPlatform.objects.filter(
                pk=platform_link.pk
            ).exists()
        )

        self.assertTrue(
            models.SharedJournalLanguage.all_objects.filter(
                pk=language_link.pk
            ).exists()
        )

        self.assertTrue(
            models.SharedJournalPlatform.all_objects.filter(
                pk=platform_link.pk
            ).exists()
        )

        representation = serializers.JournalSerializer(
            instance=journal
        ).data

        self.assertEqual(
            representation["languages"],
            [],
        )

        self.assertEqual(
            representation["platforms"],
            [],
        )

    def test_archived_relation_is_restored(self):
        """
        Una relación simple previamente eliminada se restaura.
        """
        journal = self._journal(
            issn="6677-8899",
            title="Restore Relation",
        )

        link = (
            models.SharedJournalLanguage.objects.create(
                journal=journal,
                language=self.language,
                created_by=self.system,
            )
        )

        link.soft_delete(
            user=self.system,
            explanation="Eliminada para prueba",
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "languages": [
                    self.language.pk
                ],
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system
        )

        link.refresh_from_db()

        self.assertFalse(
            link.is_deleted
        )

        self.assertTrue(
            models.SharedJournalLanguage.objects.filter(
                pk=link.pk
            ).exists()
        )

    # ==========================================================================
    # RELACIÓN ENRIQUECIDA JOURNAL <-> PLATFORM
    # ==========================================================================

    def test_platform_relation_updates_extra_fields(self):
        """
        Actualiza los atributos propios de SharedJournalPlatform.
        """
        journal = self._journal(
            issn="3344-5566",
            title="Platform Update Test",
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "platforms": [
                    {
                        "platform": self.platform.pk,
                        "has_full_text": False,
                        "journal_url": "https://8.8.8.8/platform-update",
                    }
                ]
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "platforms": [
                    {
                        "platform": self.platform.pk,
                        "has_full_text": True,
                    }
                ]
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system
        )

        link = journal.platform_links.get(
            platform=self.platform
        )

        self.assertEqual(
            link.start_period,
            timezone.localdate(),
        )

        self.assertEqual(
            link.finish_period,
            None,
        )

        self.assertTrue(
            link.has_full_text
        )

    def test_platform_relation_rejects_manual_periods(self):
        """
        Rechaza una cobertura de plataforma con período invertido.
        """
        serializer = serializers.JournalSerializer(
            data={
                "issn": "4455-6677",
                "title": "Invalid Platform Period",
                "platforms": [
                    {
                        "platform": self.platform.pk,
                        "start_period": "2026-01-01",
                        "finish_period": "2025-01-01",
                    }
                ],
            }
        )

        self.assertFalse(
            serializer.is_valid()
        )

        self.assertIn(
            "platforms",
            serializer.errors,
        )

    def test_archived_platform_relation_is_restored_and_updated(self):
        """
        Una relación plataforma archivada se restaura y actualiza
        mediante el mecanismo genérico de relaciones enriquecidas.
        """
        journal = self._journal(
            issn="7788-9900",
            title="Restore Platform Relation",
        )

        link = (
            models.SharedJournalPlatform.objects.create(
                journal=journal,
                platform=self.platform,
                has_full_text=False,
                created_by=self.system,
            )
        )

        link.soft_delete(
            user=self.system,
            explanation="Eliminada para prueba",
        )
        original_start = link.start_period
        self.platform.status = Platform.Status.BORRADOR
        self.platform.validated_by = None
        self.platform.validated_at = None
        self.platform.save(
            update_fields=["status", "validated_by", "validated_at"]
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "platforms": [
                    {
                        "platform": self.platform.pk,
                        "has_full_text": True,
                        "journal_url": "https://8.8.8.8/restored-link",
                    }
                ]
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system
        )

        link.refresh_from_db()

        self.assertFalse(
            link.is_deleted
        )

        self.assertEqual(
            link.start_period,
            original_start,
        )

        self.assertEqual(
            link.finish_period,
            None,
        )

        self.assertTrue(
            link.has_full_text
        )
        self.platform.refresh_from_db()
        self.assertEqual(self.platform.status, Platform.Status.BORRADOR)

    def test_duplicate_platforms_are_rejected(self):
        """
        La misma plataforma no puede aparecer dos veces
        en la misma petición.
        """
        serializer = serializers.JournalSerializer(
            data={
                "issn": "1010-2233",
                "title": "Duplicate Platforms",
                "platforms": [
                    {
                        "platform": self.platform.pk,
                    },
                    {
                        "platform": self.platform.pk,
                    },
                ],
            }
        )

        self.assertFalse(
            serializer.is_valid()
        )

        self.assertIn(
            "platforms",
            serializer.errors,
        )

    def test_platform_relation_allows_draft_platform(self):
        draft_platform = Platform.objects.create(
            name="Draft Association",
            status=Platform.Status.BORRADOR,
            created_by=self.system,
        )

        serializer = serializers.JournalSerializer(
            data={
                "issn": "6789-0123",
                "title": "Draft Association Journal",
                "platforms": [{
                    "platform": draft_platform.pk,
                    "journal_url": "https://8.8.8.8/draft",
                }],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        journal = serializer.save(created_by=self.system)
        self.assertTrue(
            models.SharedJournalPlatform.objects.filter(
                journal=journal,
                platform=draft_platform,
            ).exists()
        )
        draft_platform.refresh_from_db()
        self.assertEqual(draft_platform.status, Platform.Status.BORRADOR)
        self.assertIsNone(draft_platform.validated_by)
        self.assertIsNone(draft_platform.validated_at)

    def test_platform_relation_allows_obsolete_platform(self):
        obsolete_platform = Platform.objects.create(
            name="Obsolete Association",
            status=Platform.Status.OBSOLETO,
            created_by=self.system,
        )

        serializer = serializers.JournalSerializer(
            data={
                "issn": "7890-1234",
                "title": "Obsolete Association Journal",
                "platforms": [{
                    "platform": obsolete_platform.pk,
                    "journal_url": "https://8.8.8.8/obsolete",
                }],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        journal = serializer.save(created_by=self.system)
        self.assertTrue(
            models.SharedJournalPlatform.objects.filter(
                journal=journal,
                platform=obsolete_platform,
            ).exists()
        )
        obsolete_platform.refresh_from_db()
        self.assertEqual(obsolete_platform.status, Platform.Status.OBSOLETO)

    def test_platform_relation_allows_published_platform(self):
        serializer = serializers.JournalSerializer(
            data={
                "issn": "8901-2345",
                "title": "Published Association Journal",
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/published",
                }],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    # ==========================================================================
    # RESTAURACIÓN DE JOURNAL
    # ==========================================================================

    def test_archived_journal_restored_via_serializer(self):
        """
        Una revista archivada con el mismo ISSN se restaura.
        """
        journal = self._journal(
            issn="8899-0011",
            title="Revista Archivada",
        )

        journal.soft_delete(
            user=self.system,
            explanation="Archivada para prueba",
        )

        serializer = serializers.JournalSerializer(
            data={
                "issn": "8899 0011",
                "title": "Revista Restaurada",
            }
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        restored = serializer.save(
            created_by=self.system
        )

        self.assertEqual(
            restored.pk,
            journal.pk,
        )

        self.assertFalse(
            restored.is_deleted
        )

        self.assertEqual(
            restored.issn,
            "8899-0011",
        )

        self.assertEqual(
            restored.title,
            "Revista Restaurada",
        )

    def test_partial_update_without_relations_keeps_existing_relations(self):
        """
        Un PATCH que no envía relaciones no debe modificarlas.
        """
        journal = self._journal(
            issn="9900-1122",
            title="Partial Update",
        )

        models.SharedJournalLanguage.objects.create(
            journal=journal,
            language=self.language,
            created_by=self.system,
        )

        serializer = serializers.JournalSerializer(
            instance=journal,
            data={
                "title": "Título Actualizado",
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        serializer.save(
            updated_by=self.system
        )

        journal.refresh_from_db()

        self.assertEqual(
            journal.language_links.count(),
            1,
        )

        self.assertEqual(
            journal.title,
            "Título Actualizado",
        )

    # ==========================================================================
    # SERIALIZER PÚBLICO
    # ==========================================================================

    def test_public_serializer_excludes_audit_fields_and_includes_public_platform(self):
        """
        El serializer público oculta auditoría y representa
        únicamente plataformas publicadas.
        """
        journal = self._journal(
            issn="1122-3344",
            title="Public Journal",
        )

        models.SharedJournalKnowledgeArea.objects.create(
            journal=journal,
            knowledge_area=self.knowledge_area,
            is_derived=True,
            created_by=self.system,
        )

        models.SharedJournalPlatform.objects.create(
            journal=journal,
            platform=self.platform,
            has_full_text=True,
            created_by=self.system,
        )

        draft_platform = Platform.objects.create(
            name="Draft Platform",
            is_harvestable=True,
            base_api_url="https://api.draft.test",
            status=Platform.Status.BORRADOR,
            created_by=self.system,
        )

        models.SharedJournalPlatform.objects.create(
            journal=journal,
            platform=draft_platform,
            created_by=self.system,
        )

        data = serializers.JournalPublicSerializer(
            journal
        ).data

        self.assertNotIn(
            "created_by",
            data,
        )

        self.assertNotIn(
            "updated_by",
            data,
        )

        self.assertNotIn(
            "deleted_by",
            data,
        )

        self.assertNotIn(
            "delete_explanation",
            data,
        )

        self.assertEqual(
            data["issn"],
            "1122-3344",
        )

        self.assertEqual(
            data["knowledge_areas"],
            [
                {
                    "id": self.knowledge_area.pk,
                    "name": self.knowledge_area.name,
                }
            ],
        )

        self.assertEqual(
            len(data["platforms"]),
            1,
        )

        self.assertEqual(
            data["platforms"][0],
            {
                "id": self.platform.pk,
                "name": self.platform.name,
                "public_url": None,
                "journal_url": None,
                "start_period": timezone.localdate(),
                "finish_period": None,
                "has_full_text": True,
            },
        )

    def test_journal_platforms_expose_distinct_public_and_journal_urls(self):
        journal = self._journal(active=True)
        second_platform = Platform.objects.create(
            name="Otra plataforma",
            status=Platform.Status.PUBLICADO,
            is_harvestable=True,
            base_api_url="https://api.other.test",
            created_by=self.system,
        )
        first_link = models.SharedJournalPlatform.objects.create(
            journal=journal,
            platform=self.platform,
            created_by=self.system,
        )
        second_link = models.SharedJournalPlatform.objects.create(
            journal=journal,
            platform=second_platform,
            created_by=self.system,
        )
        for platform, public_url in (
            (self.platform, "https://public.first.test"),
            (second_platform, "https://public.second.test"),
        ):
            LinkCheckLog.objects.create(
                platform=platform,
                url=public_url,
                last_check=timezone.now(),
                created_by=self.system,
            )
        LinkCheckLog.objects.create(
            platform=self.platform,
            journal_platform=first_link,
            url="https://public.first.test/journal",
            last_check=timezone.now(),
            created_by=self.system,
        )
        LinkCheckLog.objects.create(
            platform=second_platform,
            journal_platform=second_link,
            url="https://public.second.test/journal",
            last_check=timezone.now(),
            created_by=self.system,
        )

        data = serializers.JournalPublicSerializer(journal).data
        urls = {
            item["id"]: (item["public_url"], item["journal_url"])
            for item in data["platforms"]
        }

        self.assertEqual(
            urls[self.platform.pk],
            ("https://public.first.test", "https://public.first.test/journal"),
        )
        self.assertEqual(
            urls[second_platform.pk],
            ("https://public.second.test", "https://public.second.test/journal"),
        )

    def test_link_log_rejects_mismatched_platform_relation(self):
        journal = self._journal()
        other_platform = Platform.objects.create(
            name="Plataforma inconsistente",
            status=Platform.Status.PUBLICADO,
            created_by=self.system,
        )
        link = models.SharedJournalPlatform.objects.create(
            journal=journal,
            platform=self.platform,
            created_by=self.system,
        )

        with self.assertRaises(ValidationError):
            LinkCheckLog.objects.create(
                platform=other_platform,
                journal_platform=link,
                url="https://invalid.example.org",
                created_by=self.system,
            )

    def test_journal_url_is_writable_and_public_url_is_read_only(self):
        field = serializers.JournalPlatformRelationSerializer().fields
        self.assertTrue(field["public_url"].read_only)
        self.assertFalse(field["journal_url"].read_only)

    def test_journal_url_creates_history_for_the_platform_relation(self):
        serializer = serializers.JournalSerializer(
            data={
                "issn": "2468-1357",
                "title": "Revista con URL contextual",
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.4.4/journal/first",
                }],
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        journal = serializer.save(created_by=self.system)
        link = models.SharedJournalPlatform.objects.get(
            journal=journal,
            platform=self.platform,
        )
        log = LinkCheckLog.objects.get(journal_platform=link)

        self.assertEqual(log.platform, self.platform)
        self.assertEqual(log.url, "https://8.8.4.4/journal/first")
        self.assertFalse(hasattr(journal, "journal_url"))
        self.assertFalse(hasattr(link, "journal_url"))

        same_url = serializers.JournalSerializer(
            journal,
            data={"platforms": [{
                "platform": self.platform.pk,
                "journal_url": "https://8.8.4.4/journal/first",
            }]},
            partial=True,
        )
        self.assertTrue(same_url.is_valid(), same_url.errors)
        same_url.save(updated_by=self.system)
        self.assertEqual(LinkCheckLog.objects.filter(journal_platform=link).count(), 1)

        new_url = serializers.JournalSerializer(
            journal,
            data={"platforms": [{
                "platform": self.platform.pk,
                "journal_url": "https://1.1.1.1/journal/second",
            }]},
            partial=True,
        )
        self.assertTrue(new_url.is_valid(), new_url.errors)
        new_url.save(updated_by=self.system)
        self.assertEqual(LinkCheckLog.objects.filter(journal_platform=link).count(), 2)

    def test_journal_url_rejects_unsafe_ssrf_destination(self):
        serializer = serializers.JournalSerializer(
            data={
                "issn": "1357-2468",
                "title": "Revista SSRF",
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "http://127.0.0.1/private",
                }],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("platforms", serializer.errors)

    def test_platform_relation_rejects_soft_deleted_platform(self):
        deleted_platform = Platform.objects.create(
            name="Deleted Association",
            created_by=self.system,
        )
        deleted_platform.soft_delete(
            user=self.system,
            explanation="Eliminada para prueba",
        )
        serializer = serializers.JournalSerializer(
            data={
                "issn": "9012-3456",
                "title": "Deleted Platform Journal",
                "platforms": [{"platform": deleted_platform.pk}],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("platforms", serializer.errors)

    def test_update_can_add_draft_platform(self):
        journal = self._journal(issn="9123-4567")
        draft_platform = Platform.objects.create(
            name="Draft Update Association",
            status=Platform.Status.BORRADOR,
            created_by=self.system,
        )
        serializer = serializers.JournalSerializer(
            journal,
            data={"platforms": [{
                "platform": draft_platform.pk,
                "journal_url": "https://8.8.8.8/draft-update",
            }]},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.system)
        self.assertTrue(
            models.SharedJournalPlatform.objects.filter(
                journal=journal,
                platform=draft_platform,
            ).exists()
        )
        draft_platform.refresh_from_db()
        self.assertEqual(draft_platform.status, Platform.Status.BORRADOR)
        self.assertIsNone(draft_platform.validated_by)
        self.assertIsNone(draft_platform.validated_at)

    def test_program_change_recalculates_journal_before_platform(self):
        journal = self._journal(issn="9234-5678")
        calls = []
        serializer = serializers.JournalSerializer(
            journal,
            data={"academic_programs": [self.academic_program.pk]},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with patch(
            "apps.journal.classification.recalculate_journals",
            side_effect=lambda *args, **kwargs: calls.append("journal"),
        ), patch(
            "apps.platforms.classification.recalculate_platforms",
            side_effect=lambda *args, **kwargs: calls.append("platform"),
        ):
            serializer.save(updated_by=self.system)

        self.assertEqual(calls, ["journal", "platform"])
