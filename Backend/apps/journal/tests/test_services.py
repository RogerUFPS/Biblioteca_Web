from datetime import date

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

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
from apps.journal import models, services as journal_services
from apps.platforms.models import Platform


class _JournalServicesTestAdapter:
    """Adapta casos históricos al contrato contextual de create_journal."""

    @staticmethod
    def create_journal(**kwargs):
        kwargs.pop("license", None)
        kwargs.pop("active", None)
        kwargs.pop("start_period", None)
        kwargs.pop("finish_period", None)
        kwargs.setdefault("platform_id", Platform.objects.first().pk)
        compact_issn = str(kwargs.get("issn", "journal")).replace("-", "")
        kwargs.setdefault("journal_url", f"https://8.8.8.8/{compact_issn}")
        return journal_services.create_journal(**kwargs)


services = _JournalServicesTestAdapter()


class JournalServicesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.system = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
        )

        cls.editorial = Editorial.objects.create(
            name="Elsevier",
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

        SharedAcademicProgramKnowledgeArea.objects.create(
            academic_program=cls.academic_program,
            knowledge_area=cls.knowledge_area,
            created_by=cls.system,
        )

        cls.platform = Platform.objects.create(
            name="Scopus Test",
            is_harvestable=True,
            base_api_url="https://api.scopus.test",
            status=Platform.Status.PUBLICADO,
            created_by=cls.system,
        )

    # ==========================================================================
    # CREACIÓN
    # ==========================================================================

    def test_create_journal_success(self):
        """
        Verifica la creación exitosa de una revista mediante el servicio.
        """
        journal = services.create_journal(
            issn="1234-5678",
            title="IEEE Transactions on Neural Networks",
            editorial_id=self.editorial.pk,
            license="CC BY",
            has_apc=False,
            active=True,
            start_period=date(2020, 1, 1),
            language_ids=[self.language.pk],
            country_ids=[self.country.pk],
            material_type_ids=[self.material_type.pk],
            academic_program_ids=[
                self.academic_program.pk
            ],
            user=self.system,
        )

        self.assertIsNotNone(journal.pk)

        self.assertFalse(journal.active)
        self.assertIsNone(journal.validated_by)
        self.assertIsNone(journal.validated_at)

        self.assertEqual(
            journal.issn,
            "1234-5678",
        )

        self.assertEqual(
    journal.title,
    "IEEE Transactions on Neural Networks",
)

        self.assertEqual(
            journal.editorial_id,
            self.editorial.pk,
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

    # ==========================================================================
    # ISSN
    # ==========================================================================

    def test_create_journal_normalizes_issn(self):
        """
        El ISSN se normaliza al formato XXXX-XXXX.
        """
        journal = services.create_journal(
            issn=" 1234 567x ",
            title="Journal ISSN",
            user=self.system,
        )

        self.assertEqual(
            journal.issn,
            "1234-567X",
        )

    def test_create_journal_rejects_invalid_issn(self):
        """
        Rechaza un ISSN con formato inválido.
        """
        with self.assertRaises(ValidationError) as context:
            services.create_journal(
                issn="1234-56AB",
                title="ISSN Inválido",
                user=self.system,
            )

        self.assertIn(
            "issn",
            context.exception.detail,
        )

    def test_create_journal_requires_issn(self):
        """
        El ISSN es obligatorio.
        """
        with self.assertRaises(ValidationError) as context:
            services.create_journal(
                issn="",
                title="Journal Sin ISSN",
                user=self.system,
            )

        self.assertIn(
            "issn",
            context.exception.detail,
        )

    # ==========================================================================
    # DEDUPLICACIÓN / ACTUALIZACIÓN
    # ==========================================================================

    def test_create_journal_updates_existing_issn(self):
        """
        Si el ISSN ya existe, no crea otra revista:
        actualiza el registro existente.
        """
        journal = services.create_journal(
            issn="2233-4455",
            title="Journal Original",
            user=self.system,
        )

        original_pk = journal.pk

        updated = services.create_journal(
            issn="2233 4455",
            title="Journal Actualizado",
            license="CC BY",
            user=self.system,
        )

        self.assertEqual(
            updated.pk,
            original_pk,
        )

        self.assertEqual(
            models.Journal.objects.filter(
                issn="2233-4455"
            ).count(),
            1,
        )

        self.assertEqual(
    updated.title,
    "Journal Actualizado",
)

    # ==========================================================================
    # RESTAURACIÓN
    # ==========================================================================

    def test_create_journal_restores_archived_journal(self):
        """
        Si existe una revista eliminada con el mismo ISSN,
        el servicio la restaura en lugar de crear otra.
        """
        journal = services.create_journal(
            issn="3344-5566",
            title="Journal Para Archivar",
            user=self.system,
        )

        original_pk = journal.pk

        journal.soft_delete(
            user=self.system,
            explanation="Eliminada para prueba",
        )

        restored = services.create_journal(
            issn="3344-5566",
            title="Journal Restaurado",
            user=self.system,
        )

        self.assertEqual(
            restored.pk,
            original_pk,
        )

        self.assertFalse(
            restored.is_deleted
        )

        self.assertEqual(
            restored.title,
            "Journal Restaurado",
        )

    def test_restore_clears_validation(self):
        """
        Una revista restaurada pierde su estado de validación
        para requerir una nueva validación.
        """
        journal = services.create_journal(
            issn="4455-6677",
            title="Journal Validado",
            user=self.system,
        )

        journal.validated_by = self.system
        journal.validated_at = (
            journal.updated_at
        )

        journal.save(
            update_fields=[
                "validated_by",
                "validated_at",
            ]
        )

        journal.soft_delete(
            user=self.system,
            explanation="Eliminada para prueba",
        )

        restored = services.create_journal(
            issn="4455-6677",
            title="Journal Restaurado",
            user=self.system,
        )

        self.assertIsNone(
            restored.validated_by
        )

        self.assertIsNone(
            restored.validated_at
        )

        self.assertFalse(
            restored.active
        )

    # ==========================================================================
    # RELACIONES SIMPLES
    # ==========================================================================

    def test_create_journal_syncs_all_relations(self):
        """
        Sincroniza correctamente las cinco relaciones simples.
        """
        journal = services.create_journal(
            issn="5566-7788",
            title="Journal Relaciones",
            language_ids=[
                self.language.pk
            ],
            country_ids=[
                self.country.pk
            ],
            material_type_ids=[
                self.material_type.pk
            ],
            academic_program_ids=[
                self.academic_program.pk
            ],
            user=self.system,
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

    def test_create_journal_derives_knowledge_areas_from_academic_programs(self):
        journal = services.create_journal(
            issn="6767-8989",
            title="Journal Derivación",
            academic_program_ids=[self.academic_program.pk],
            user=self.system,
        )

        self.assertEqual(
            list(
                journal.knowledge_area_links.values_list(
                    "knowledge_area_id",
                    flat=True,
                )
            ),
            [self.knowledge_area.pk],
        )

    def test_empty_academic_programs_clears_derived_knowledge_areas(self):
        journal = services.create_journal(
            issn="6969-0101",
            title="Journal Clear Derived",
            academic_program_ids=[self.academic_program.pk],
            user=self.system,
        )

        services.create_journal(
            issn="6969-0101",
            title="Journal Clear Derived",
            academic_program_ids=[],
            user=self.system,
        )

        self.assertEqual(journal.academic_program_links.count(), 0)
        self.assertEqual(journal.knowledge_area_links.count(), 0)

    def test_create_journal_deduplicates_relation_ids(self):
        """
        IDs repetidos no generan relaciones duplicadas.
        """
        journal = services.create_journal(
            issn="6677-8899",
            title="Journal Duplicados",
            language_ids=[
                self.language.pk,
                self.language.pk,
                self.language.pk,
            ],
            user=self.system,
        )

        self.assertEqual(
            journal.language_links.count(),
            1,
        )

    def test_empty_relation_list_removes_existing_relations(self):
        """
        Una lista vacía elimina todas las relaciones
        de ese tipo mediante Soft Delete.
        """
        journal = services.create_journal(
            issn="7788-9900",
            title="Journal Soft Delete",
            language_ids=[
                self.language.pk
            ],
            user=self.system,
        )

        self.assertEqual(
            journal.language_links.count(),
            1,
        )

        services.create_journal(
            issn="7788-9900",
            title="Journal Soft Delete",
            language_ids=[],
            user=self.system,
        )

        self.assertEqual(
            journal.language_links.count(),
            0,
        )

        self.assertEqual(
            models.SharedJournalLanguage.all_objects.filter(
                journal=journal
            ).count(),
            1,
        )

    def test_none_relation_does_not_modify_existing_relations(self):
        """
        None significa que la relación no debe modificarse.
        """
        journal = services.create_journal(
            issn="8899-0011",
            title="Journal None",
            language_ids=[
                self.language.pk
            ],
            user=self.system,
        )

        services.create_journal(
            issn="8899-0011",
            title="Journal None Actualizado",
            user=self.system,
        )

        journal.refresh_from_db()

        self.assertEqual(
            journal.language_links.count(),
            1,
        )

        self.assertEqual(
    journal.title,
    "Journal None Actualizado",
)

    # ==========================================================================
    # VALIDACIÓN DE RELACIONES
    # ==========================================================================

    def test_create_journal_rejects_nonexistent_relation_id(self):
        """
        Rechaza IDs de relaciones que no existen.
        """
        with self.assertRaises(ValidationError) as context:
            services.create_journal(
                issn="9900-1122",
                title="Journal Invalid Relation",
                language_ids=[999999],
                user=self.system,
            )

        self.assertIn(
            "language_ids",
            context.exception.detail,
        )

    def test_create_journal_rejects_invalid_editorial(self):
        """
        Rechaza una editorial inexistente o eliminada.
        """
        with self.assertRaises(ValidationError) as context:
            services.create_journal(
                issn="1010-2233",
                title="Journal Editorial",
                editorial_id=999999,
                user=self.system,
            )

        self.assertIn(
            "editorial_id",
            context.exception.detail,
        )

    # ==========================================================================
    # PERIODOS
    # ==========================================================================

    def test_create_journal_does_not_accept_manual_periods(self):
        with self.assertRaises(TypeError):
            journal_services.create_journal(
                issn="1122-3344",
                title="Journal Period",
                platform_id=self.platform.pk,
                journal_url="https://8.8.8.8/11223344",
                platform_start_period=date(2026, 1, 1),
                user=self.system,
            )

    # ==========================================================================
    # PLATAFORMA DE PROCEDENCIA
    # ==========================================================================

    def test_create_journal_syncs_source_platform(self):
        """
        Crea correctamente la relación Journal <-> Platform
        con sus atributos propios.
        """
        journal = services.create_journal(
            issn="2233-4455",
            title="Journal Platform",
            platform_id=self.platform.pk,
            has_full_text=True,
            user=self.system,
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

        self.assertIsNotNone(
            journal.fetched_at
        )

    def test_source_platform_updates_existing_relation(self):
        """
        Actualiza los atributos de una relación
        Journal <-> Platform existente.
        """
        journal = services.create_journal(
            issn="3344-5566",
            title="Journal Platform Update",
            platform_id=self.platform.pk,
            has_full_text=False,
            user=self.system,
        )

        services.create_journal(
            issn="3344-5566",
            title="Journal Platform Update",
            platform_id=self.platform.pk,
            has_full_text=True,
            user=self.system,
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

    def test_source_platform_restores_archived_relation(self):
        """
        Restaura una relación Journal <-> Platform
        previamente eliminada.
        """
        journal = services.create_journal(
            issn="4455-6677",
            title="Journal Restore Platform",
            platform_id=self.platform.pk,
            user=self.system,
        )

        link = journal.platform_links.get(
            platform=self.platform
        )

        link.soft_delete(
            user=self.system,
            explanation="Eliminada para prueba",
        )
        original_start = link.start_period
        self.assertEqual(link.finish_period, timezone.localdate())
        self.platform.status = Platform.Status.BORRADOR
        self.platform.validated_by = None
        self.platform.validated_at = None
        self.platform.save(
            update_fields=["status", "validated_by", "validated_at"]
        )

        services.create_journal(
            issn="4455-6677",
            title="Journal Restore Platform",
            platform_id=self.platform.pk,
            has_full_text=True,
            user=self.system,
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

    def test_source_platform_rejects_manual_period(self):
        with self.assertRaises(TypeError):
            journal_services.create_journal(
                issn="5566-7788",
                title="Journal Invalid Platform Period",
                platform_id=self.platform.pk,
                journal_url="https://8.8.8.8/55667788",
                platform_start_period=date(2026, 1, 1),
                user=self.system,
            )

    def test_source_platform_rejects_invalid_platform(self):
        """
        Rechaza una plataforma inexistente.
        """
        with self.assertRaises(ValidationError) as context:
            services.create_journal(
                issn="6677-8899",
                title="Journal Invalid Platform",
                platform_id=999999,
                user=self.system,
            )

        self.assertIn(
            "platform_id",
            context.exception.detail,
        )

    def test_source_platform_allows_draft_platform(self):
        draft_platform = Platform.objects.create(
            name="Draft Source Platform",
            status=Platform.Status.BORRADOR,
            created_by=self.system,
        )

        journal = services.create_journal(
            issn="7070-1212",
            title="Journal Draft Platform",
            platform_id=draft_platform.pk,
            user=self.system,
        )

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

    def test_source_platform_allows_obsolete_platform(self):
        obsolete_platform = Platform.objects.create(
            name="Obsolete Source Platform",
            status=Platform.Status.OBSOLETO,
            created_by=self.system,
        )

        journal = services.create_journal(
            issn="7171-2323",
            title="Journal Obsolete Platform",
            platform_id=obsolete_platform.pk,
            user=self.system,
        )

        self.assertTrue(
            models.SharedJournalPlatform.objects.filter(
                journal=journal,
                platform=obsolete_platform,
            ).exists()
        )
        obsolete_platform.refresh_from_db()
        self.assertEqual(obsolete_platform.status, Platform.Status.OBSOLETO)

    def test_source_platform_rejects_soft_deleted_platform(self):
        deleted_platform = Platform.objects.create(
            name="Deleted Source Platform",
            created_by=self.system,
        )
        deleted_platform.soft_delete(
            user=self.system,
            explanation="Eliminada para prueba",
        )

        with self.assertRaises(ValidationError) as context:
            services.create_journal(
                issn="7272-3434",
                title="Journal Deleted Platform",
                platform_id=deleted_platform.pk,
                user=self.system,
            )

        self.assertIn("platform_id", context.exception.detail)
