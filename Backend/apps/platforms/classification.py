"""Procedencia manual y clasificación derivada del dominio Platform."""

from collections import defaultdict
from collections.abc import Iterable

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.journal import models as journal_models

from . import models


DERIVED_DELETE = "Relación derivada retirada al recalcular la plataforma."
MANUAL_DELETE = "Relación manual retirada durante la actualización de la plataforma."


SECTION_SPECS = (
    ("languages", models.SharedPlatformLanguage, "language", journal_models.SharedJournalLanguage),
    ("countries", models.SharedPlatformCountry, "country", journal_models.SharedJournalCountry),
    (
        "knowledge_areas",
        models.SharedPlatformKnowledgeArea,
        "knowledge_area",
        journal_models.SharedJournalKnowledgeArea,
    ),
    (
        "material_types",
        models.SharedPlatformMaterialType,
        "material_type",
        journal_models.SharedJournalMaterialType,
    ),
    (
        "academic_programs",
        models.SharedPlatformAcademicProgram,
        "academic_program",
        journal_models.SharedJournalAcademicProgram,
    ),
)

MANUAL_SECTION_SPECS = (
    ("institutions", models.SharedPlatformSupport, "institution"),
    *((name, model, field) for name, model, field, _ in SECTION_SPECS),
)


def _set_origin(link, *, user, is_manual=None, is_derived=None):
    changed = False
    if is_manual is not None and link.is_manual != is_manual:
        link.is_manual = is_manual
        changed = True
    if is_derived is not None and link.is_derived != is_derived:
        link.is_derived = is_derived
        changed = True
    if changed:
        link.updated_by = user
        link.updated_at = timezone.now()
        link.save(update_fields=["is_manual", "is_derived", "updated_by", "updated_at"])
    return changed


def _sync_origin(*, platform, desired_ids, through_model, relation_field, origin, user):
    desired_ids = set(desired_ids)
    links = {
        getattr(link, f"{relation_field}_id"): link
        for link in through_model.all_objects.select_for_update().filter(platform=platform)
    }
    changed = False
    for related_id, link in links.items():
        wanted = related_id in desired_ids
        if origin == "is_manual" and not link.is_deleted and link.is_derived:
            # Mientras exista una fuente derivada la relación está protegida:
            # tampoco se altera una contribución manual previa.
            continue
        if wanted:
            if link.is_deleted:
                link.restore()
                changed = True
            changed |= _set_origin(link, user=user, **{origin: True})
        else:
            changed |= _set_origin(link, user=user, **{origin: False})
            if not link.is_deleted and not (link.is_manual or link.is_derived):
                link.soft_delete(user=user, explanation=(
                    MANUAL_DELETE if origin == "is_manual" else DERIVED_DELETE
                ))
                changed = True
    for related_id in desired_ids - links.keys():
        through_model.objects.create(
            platform=platform,
            **{f"{relation_field}_id": related_id, origin: True},
            created_by=user,
        )
        changed = True
    return changed


@transaction.atomic
def sync_manual_platform_sections(platform, relation_data, *, user):
    """Sincroniza solo la contribución manual, conservando la derivada."""
    changed = False
    for data_field, through_model, relation_field in MANUAL_SECTION_SPECS:
        if data_field not in relation_data:
            continue
        changed |= _sync_origin(
            platform=platform,
            desired_ids=(item.pk for item in relation_data[data_field]),
            through_model=through_model,
            relation_field=relation_field,
            origin="is_manual",
            user=user,
        )
    return changed


@transaction.atomic
def recalculate_platforms(platform_ids: Iterable[int], *, user) -> set[int]:
    """Recalcula las cinco secciones compartidas desde todas las Journals elegibles."""
    ids = set(platform_ids)
    if not ids:
        return set()

    eligible = journal_models.SharedJournalPlatform.objects.filter(
        platform_id__in=ids,
        journal__deleted_at__isnull=True,
        journal__active=True,
        journal__validated_at__isnull=False,
    ).values_list("platform_id", "journal_id")
    journal_ids_by_platform = defaultdict(set)
    for platform_id, journal_id in eligible:
        journal_ids_by_platform[platform_id].add(journal_id)

    desired_by_section = {}
    all_eligible_journal_ids = set().union(*journal_ids_by_platform.values()) if journal_ids_by_platform else set()
    for data_field, _, relation_field, journal_through in SECTION_SPECS:
        by_platform = defaultdict(set)
        if all_eligible_journal_ids:
            rows = journal_through.objects.filter(
                journal_id__in=all_eligible_journal_ids,
                **{f"{relation_field}__deleted_at__isnull": True},
            )
            if journal_through is journal_models.SharedJournalKnowledgeArea:
                rows = rows.filter(Q(is_manual=True) | Q(is_derived=True))
            rows = rows.values_list("journal_id", f"{relation_field}_id")
            values_by_journal = defaultdict(set)
            for journal_id, related_id in rows:
                values_by_journal[journal_id].add(related_id)
            for platform_id, journal_ids in journal_ids_by_platform.items():
                for journal_id in journal_ids:
                    by_platform[platform_id].update(values_by_journal[journal_id])
        desired_by_section[data_field] = by_platform

    changed_platform_ids = set()
    for platform in models.Platform.all_objects.select_for_update().filter(pk__in=ids):
        for data_field, through_model, relation_field, _ in SECTION_SPECS:
            if _sync_origin(
                platform=platform,
                desired_ids=desired_by_section[data_field].get(platform.pk, set()),
                through_model=through_model,
                relation_field=relation_field,
                origin="is_derived",
                user=user,
            ):
                changed_platform_ids.add(platform.pk)

        if platform.status == models.Platform.Status.PUBLICADO:
            from .services import validate_platform_for_publication
            try:
                validate_platform_for_publication(platform, require_draft=False)
            except ValidationError:
                now = timezone.now()
                platform.status = models.Platform.Status.BORRADOR
                platform.validated_by = None
                platform.validated_at = None
                platform.updated_by = user
                platform.updated_at = now
                platform.save(update_fields=[
                    "status", "validated_by", "validated_at", "updated_by", "updated_at",
                ])
                changed_platform_ids.add(platform.pk)
    return changed_platform_ids
