"""Clasificación derivada perteneciente al dominio Journal."""

from collections import defaultdict
from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import SharedAcademicProgramKnowledgeArea
from . import models


JOURNAL_DERIVED_DELETE = (
    "Área derivada retirada al recalcular la clasificación de la revista."
)
JOURNAL_MANUAL_DELETE = (
    "Área manual retirada durante la actualización de la revista."
)


def _set_origin(link, *, user, is_manual=None, is_derived=None):
    changed_fields = []
    if is_manual is not None and link.is_manual != is_manual:
        link.is_manual = is_manual
        changed_fields.append("is_manual")
    if is_derived is not None and link.is_derived != is_derived:
        link.is_derived = is_derived
        changed_fields.append("is_derived")
    if changed_fields:
        link.updated_by = user
        link.updated_at = timezone.now()
        link.save(update_fields=[*changed_fields, "updated_by", "updated_at"])
    return bool(changed_fields)


def _restore_with_origin(link, *, user, origin):
    link.deleted_by = None
    link.deleted_at = None
    link.delete_explanation = None
    link.is_manual = origin == "is_manual"
    link.is_derived = origin == "is_derived"
    link.updated_by = user
    link.updated_at = timezone.now()
    link.save(update_fields=[
        "deleted_by", "deleted_at", "delete_explanation",
        "is_manual", "is_derived", "updated_by", "updated_at",
    ])


def _sync_area_origin(*, journal, desired_ids, origin, user):
    desired_ids = set(desired_ids)
    links = {
        link.knowledge_area_id: link
        for link in models.SharedJournalKnowledgeArea.all_objects
        .select_for_update()
        .filter(journal=journal)
    }
    changed = False
    for area_id, link in links.items():
        wanted = area_id in desired_ids
        if origin == "is_manual" and not link.is_deleted and link.is_derived:
            # Una relación derivada no puede alterarse desde la selección manual.
            continue
        if wanted:
            if link.is_deleted:
                _restore_with_origin(link, user=user, origin=origin)
                changed = True
            else:
                changed |= _set_origin(link, user=user, **{origin: True})
        else:
            other_origin = (
                link.is_derived if origin == "is_manual" else link.is_manual
            )
            if not link.is_deleted and not other_origin:
                # El override de soft_delete limpia ambos orígenes y marca la
                # eliminación en una sola escritura, sin violar el constraint.
                link.soft_delete(
                    user=user,
                    explanation=(
                        JOURNAL_MANUAL_DELETE
                        if origin == "is_manual"
                        else JOURNAL_DERIVED_DELETE
                    ),
                )
                changed = True
            else:
                changed |= _set_origin(link, user=user, **{origin: False})
    for area_id in desired_ids - links.keys():
        models.SharedJournalKnowledgeArea.objects.create(
            journal=journal,
            knowledge_area_id=area_id,
            **{origin: True},
            created_by=user,
        )
        changed = True
    return changed


@transaction.atomic
def sync_manual_knowledge_areas(journal, knowledge_areas, *, user):
    """Sincroniza la procedencia manual sin eliminar aportes derivados."""
    return _sync_area_origin(
        journal=journal,
        desired_ids=(area.pk for area in knowledge_areas),
        origin="is_manual",
        user=user,
    )


def _area_ids_by_program(program_ids: set[int]) -> dict[int, set[int]]:
    result: dict[int, set[int]] = defaultdict(set)
    rows = SharedAcademicProgramKnowledgeArea.objects.filter(
        academic_program_id__in=program_ids,
        academic_program__deleted_at__isnull=True,
        knowledge_area__deleted_at__isnull=True,
    ).values_list("academic_program_id", "knowledge_area_id")
    for program_id, area_id in rows:
        result[program_id].add(area_id)
    return result


def related_platform_ids(journal_ids: Iterable[int]) -> set[int]:
    """Obtiene Platforms vinculadas sin conocer cómo se clasifican."""
    return set(
        models.SharedJournalPlatform.objects.filter(
            journal_id__in=set(journal_ids),
        ).values_list("platform_id", flat=True)
    )


@transaction.atomic
def recalculate_journals(
    journal_ids: Iterable[int],
    *,
    user,
    invalidate_on_change: bool = True,
) -> set[int]:
    """Materializa áreas y devuelve únicamente IDs de Journals cambiadas."""
    ids = set(journal_ids)
    if not ids:
        return set()

    program_ids_by_journal: dict[int, set[int]] = defaultdict(set)
    all_program_ids: set[int] = set()
    rows = models.SharedJournalAcademicProgram.objects.filter(
        journal_id__in=ids,
        journal__deleted_at__isnull=True,
        academic_program__deleted_at__isnull=True,
    ).values_list("journal_id", "academic_program_id")
    for journal_id, program_id in rows:
        program_ids_by_journal[journal_id].add(program_id)
        all_program_ids.add(program_id)

    areas_by_program = _area_ids_by_program(all_program_ids)
    changed_journal_ids: set[int] = set()
    journals = models.Journal.all_objects.select_for_update().filter(pk__in=ids)
    for journal in journals:
        program_ids = program_ids_by_journal.get(journal.pk, set())
        desired = (
            set().union(*(areas_by_program.get(pk, set()) for pk in program_ids))
            if program_ids else set()
        )
        changed = _sync_area_origin(
            journal=journal,
            desired_ids=desired,
            origin="is_derived",
            user=user,
        )
        if not changed:
            continue
        changed_journal_ids.add(journal.pk)
        if invalidate_on_change and (journal.active or journal.validated_at is not None):
            now = timezone.now()
            journal.active = False
            journal.validated_by = None
            journal.validated_at = None
            journal.updated_by = user
            journal.updated_at = now
            journal.save(update_fields=[
                "active", "validated_by", "validated_at", "updated_by", "updated_at",
            ])
    return changed_journal_ids


def propagate_catalog_change(program_ids: Iterable[int], *, user) -> set[int]:
    """Coordina Journal→Platform después de un cambio efectivo de catálogo."""
    ids = set(program_ids)
    journal_ids = set(
        models.SharedJournalAcademicProgram.objects.filter(
            academic_program_id__in=ids,
            journal__deleted_at__isnull=True,
        ).values_list("journal_id", flat=True)
    )
    changed_journal_ids = recalculate_journals(
        journal_ids, user=user, invalidate_on_change=True
    )
    platform_ids = related_platform_ids(changed_journal_ids)
    if platform_ids:
        from apps.platforms.classification import recalculate_platforms
        recalculate_platforms(platform_ids, user=user)
    return platform_ids
