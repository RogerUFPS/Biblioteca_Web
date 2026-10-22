from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog.models import (
    AcademicProgram,
    Country,
    Editorial,
    Language,
    MaterialType,
    SharedAcademicProgramKnowledgeArea,
)
from apps.platforms.models import Platform
from apps.platforms import services as platform_services

from . import models
from .classification import (
    recalculate_journals,
    related_platform_ids,
)
from apps.platforms.classification import recalculate_platforms


JOURNAL_RELATION_CONFIG = (
    # (
    #     input_field,
    #     through_model,
    #     relation_field,
    #     target_model,
    # )
    (
        "language_ids",
        models.SharedJournalLanguage,
        "language",
        Language,
    ),
    (
        "country_ids",
        models.SharedJournalCountry,
        "country",
        Country,
    ),
    (
        "material_type_ids",
        models.SharedJournalMaterialType,
        "material_type",
        MaterialType,
    ),
    (
        "academic_program_ids",
        models.SharedJournalAcademicProgram,
        "academic_program",
        AcademicProgram,
    ),
)


def validate_journal_for_publication(journal: models.Journal) -> None:
    """Valida el conjunto final de datos que hace publicable una Journal."""
    errors = {}
    if journal.is_deleted:
        errors["detail"] = "No se puede publicar una revista eliminada."
    for field in ("issn", "title"):
        if not getattr(journal, field, None):
            errors[field] = f"El campo {field} es obligatorio para publicar."
    if not journal.editorial_id or journal.editorial.is_deleted:
        errors["editorial"] = "La revista debe tener una editorial vigente."
    if not journal.publication_date:
        errors["publication_date"] = "La fecha de publicación es obligatoria."

    relation_specs = (
        ("languages", models.SharedJournalLanguage, "language"),
        ("countries", models.SharedJournalCountry, "country"),
        ("knowledge_areas", models.SharedJournalKnowledgeArea, "knowledge_area"),
        ("material_types", models.SharedJournalMaterialType, "material_type"),
        ("academic_programs", models.SharedJournalAcademicProgram, "academic_program"),
    )
    for field, through_model, relation_field in relation_specs:
        relation_query = through_model.objects.filter(
            journal=journal,
            **{f"{relation_field}__deleted_at__isnull": True},
        )
        if through_model is models.SharedJournalKnowledgeArea:
            relation_query = relation_query.filter(
                Q(is_manual=True) | Q(is_derived=True)
            )
        if not relation_query.exists():
            errors[field] = "La revista debe tener al menos un valor vigente."

    platform_links = models.SharedJournalPlatform.objects.filter(
        journal=journal,
        platform__deleted_at__isnull=True,
    )
    if not platform_links.exists():
        errors["platforms"] = "La revista no tiene plataformas asociadas."
    elif not platform_links.filter(platform__status=Platform.Status.PUBLICADO).exists():
        errors["platforms"] = (
            "La revista tiene plataformas asociadas, pero ninguna se encuentra publicada."
        )

    if not models.SharedJournalLicense.objects.filter(
        journal=journal,
        license__deleted_at__isnull=True,
    ).exists():
        errors["licenses"] = "La revista debe tener al menos una licencia vigente."
    if errors:
        raise ValidationError(errors)


def validate_platform_for_journal_association(
    platform: Platform,
    *,
    field_name: str = "platform_id",
) -> None:
    """
    Garantiza que una revista solo se asocie a una plataforma vigente.

    Esta validación se reutiliza tanto en el serializer administrativo
    como en el servicio interno de creación/cosecha.
    """
    if platform.is_deleted:
        raise ValidationError(
            {
                field_name: (
                    "La plataforma indicada no existe o se encuentra "
                    "eliminada."
                )
            }
        )


def validate_journal_platform_period(
    *,
    platform: Platform,
    start_period: date | None,
    finish_period: date | None,
    start_field: str = "start_period",
    finish_field: str = "finish_period",
) -> None:
    """Valida las fechas del ciclo de vida de una vinculación."""
    errors = {}
    if start_period is None:
        errors[start_field] = "La fecha de vinculación es obligatoria."
    if start_period and finish_period and finish_period < start_period:
        errors[finish_field] = (
            "La fecha de finalización no puede ser anterior "
            "a la fecha de vinculación."
        )
    if platform.start_period and start_period and start_period < platform.start_period:
        errors[start_field] = (
            "La fecha de vinculación no puede ser anterior "
            "a la fecha de registro de la plataforma."
        )
    if errors:
        raise ValidationError(errors)


def _normalize_issn(issn: str) -> str:
    """
    Normaliza el ISSN al formato XXXX-XXXX.

    Se admite como entrada con o sin guion y se normaliza
    la letra de control X a mayúscula.
    """

    if not issn or not issn.strip():
        raise ValidationError(
            {
                "issn": "El ISSN es obligatorio."
            }
        )

    compact_issn = (
        "".join(issn.split())
        .replace("-", "")
        .upper()
    )

    if (
        len(compact_issn) != 8
        or not compact_issn[:7].isdigit()
        or not (
            compact_issn[7].isdigit()
            or compact_issn[7] == "X"
        )
    ):
        raise ValidationError(
            {
                "issn": (
                    "El ISSN debe tener el formato XXXX-XXXX."
                )
            }
        )

    return (
        f"{compact_issn[:4]}-"
        f"{compact_issn[4:]}"
    )


def _validate_editorial(
    editorial_id: int | None,
) -> None:
    """
    Verifica que la editorial exista y se encuentre activa.
    """

    if editorial_id is None:
        return

    if not Editorial.objects.filter(
        pk=editorial_id
    ).exists():
        raise ValidationError(
            {
                "editorial_id": (
                    "La editorial indicada no existe "
                    "o se encuentra eliminada."
                )
            }
        )


def _sync_relation_ids(
    *,
    journal: models.Journal,
    ids: list[int],
    through_model,
    relation_field: str,
    target_model,
    input_field: str,
    user,
) -> None:
    """
    Sincroniza una relación simple de Journal mediante IDs.

    Permite:
    - eliminar relaciones mediante Soft Delete;
    - restaurar relaciones archivadas;
    - crear relaciones nuevas;
    - evitar IDs duplicados;
    - rechazar registros inexistentes o eliminados.
    """

    unique_ids = set(ids)

    existing_target_ids = set(
        target_model.objects
        .filter(
            pk__in=unique_ids
        )
        .values_list(
            "pk",
            flat=True,
        )
    )

    missing_ids = (
        unique_ids
        - existing_target_ids
    )

    if missing_ids:
        raise ValidationError(
            {
                input_field: (
                    "Los siguientes IDs no existen "
                    "o se encuentran eliminados: "
                    f"{sorted(missing_ids)}."
                )
            }
        )

    current_links = through_model.objects.filter(
        journal=journal
    )

    current_ids = set(
        current_links.values_list(
            f"{relation_field}_id",
            flat=True,
        )
    )

    ids_to_remove = (
        current_ids
        - unique_ids
    )

    ids_to_add = (
        unique_ids
        - current_ids
    )

    if ids_to_remove:
        links_to_remove = current_links.filter(
            **{
                f"{relation_field}_id__in": ids_to_remove,
            }
        )

        for link in links_to_remove:
            link.soft_delete(
                user=user,
                explanation=(
                    "Relación eliminada durante "
                    "la actualización de la revista."
                ),
            )

    for related_id in ids_to_add:
        lookup = {
            "journal": journal,
            f"{relation_field}_id": related_id,
        }

        archived_link = (
            through_model.all_objects
            .filter(
                deleted_at__isnull=False,
                **lookup,
            )
            .first()
        )

        if archived_link:
            archived_link.restore()

            archived_link.updated_by = user
            archived_link.updated_at = timezone.now()

            archived_link.save(
                update_fields=[
                    "updated_by",
                    "updated_at",
                ]
            )

        else:
            through_model.objects.create(
                journal=journal,
                **{
                    f"{relation_field}_id": related_id,
                },
                created_by=user,
            )


def _sync_source_platform(
    *,
    journal: models.Journal,
    platform_id: int,
    has_full_text: bool | None,
    user,
) -> models.SharedJournalPlatform:
    """
    Crea, actualiza o restaura la relación entre una revista
    y la plataforma desde la cual fue obtenida.

    Las fechas del ciclo de vida son administradas por el modelo.
    """

    platform = (
        Platform.objects
        .filter(
            pk=platform_id
        )
        .first()
    )

    if platform is None:
        raise ValidationError(
            {
                "platform_id": (
                    "La plataforma indicada no existe "
                    "o se encuentra eliminada."
                )
            }
        )

    validate_platform_for_journal_association(
        platform,
        field_name="platform_id",
    )

    active_link = (
        models.SharedJournalPlatform.objects
        .filter(
            journal=journal,
            platform=platform,
        )
        .first()
    )

    if active_link:
        update_fields = []

        if has_full_text is not None:
            active_link.has_full_text = has_full_text
            update_fields.append(
                "has_full_text"
            )

        active_link.updated_by = user
        active_link.updated_at = timezone.now()

        update_fields.extend(
            [
                "updated_by",
                "updated_at",
            ]
        )

        active_link.save(
            update_fields=update_fields
        )

        return active_link

    validate_platform_for_journal_association(
        platform,
        field_name="platform_id",
    )

    archived_link = (
        models.SharedJournalPlatform.all_objects
        .filter(
            journal=journal,
            platform=platform,
            deleted_at__isnull=False,
        )
        .first()
    )

    if archived_link:
        archived_link.restore()

        if has_full_text is not None:
            archived_link.has_full_text = has_full_text

        archived_link.updated_by = user
        archived_link.updated_at = timezone.now()

        archived_link.save(
            update_fields=[
                "has_full_text",
                "updated_by",
                "updated_at",
            ]
        )

        return archived_link

    return models.SharedJournalPlatform.objects.create(
        journal=journal,
        platform=platform,
        has_full_text=(
            has_full_text
            if has_full_text is not None
            else False
        ),
        created_by=user,
    )


@transaction.atomic
def create_journal(
    *,
    issn: str,
    title: str,
    user,
    platform_id: int,
    journal_url: str,
    editorial_id: int | None = None,
    publication_date: date | None = None,
    url_image: str | None = None,
    has_apc: bool | None = None,
    language_ids: list[int] | None = None,
    country_ids: list[int] | None = None,
    material_type_ids: list[int] | None = None,
    academic_program_ids: list[int] | None = None,
    has_full_text: bool | None = None,
) -> models.Journal:
    """
    Crea o actualiza una revista utilizando el ISSN como
    identificador principal.

    Comportamiento:

    - Si el ISSN no existe, crea una revista.
    - Si el ISSN ya existe, actualiza esa revista.
    - Si la revista con ese ISSN estaba eliminada, la restaura.
    - Sincroniza únicamente las clasificaciones suministradas.
    - Exige y registra la plataforma y URL contextual de procedencia.
    - Actualiza fetched_at.

    None en una colección significa "no modificar".
    Una lista vacía significa "eliminar todas las relaciones".

    Las áreas del conocimiento no se reciben como entrada: se derivan
    exclusivamente de ``academic_program_ids``.

    Este servicio está diseñado como punto de entrada interno para procesos
    backend. No recibe licencias ni controla la publicación: toda creación o
    actualización queda pendiente de la acción explícita de publicación.
    """

    normalized_issn = _normalize_issn(
        issn
    )
    if not journal_url or not journal_url.strip():
        raise ValidationError({"journal_url": "La URL contextual de la revista es obligatoria."})
    platform_services.validate_safe_http_url(journal_url, field_name="journal_url")

    normalized_title = (
        title.strip()
        if title
        else ""
    )

    if not normalized_title:
        raise ValidationError(
            {
                "title": (
                    "El título de la revista es obligatorio."
                )
            }
        )

    _validate_editorial(
        editorial_id
    )

    now = timezone.now()

    created = False

    journal = (
        models.Journal.all_objects
        .select_for_update()
        .filter(
            issn__iexact=normalized_issn
        )
        .first()
    )

    if journal is None:
        create_data = {
            "issn": normalized_issn,
            "title": normalized_title,
            "created_by": user,
            "active": False,
        }

        if editorial_id is not None:
            create_data["editorial_id"] = editorial_id

        if publication_date is not None:
            create_data["publication_date"] = publication_date

        if url_image is not None:
            create_data["url_image"] = url_image

        if has_apc is not None:
            create_data["has_apc"] = has_apc

        create_data["fetched_at"] = now

        try:
            # El bloque interno crea un savepoint.
            # Si otro proceso creó simultáneamente el mismo ISSN,
            # solo se revierte este intento de INSERT.
            with transaction.atomic():
                journal = models.Journal.objects.create(
                    **create_data
                )

            created = True

        except IntegrityError:
            journal = (
                models.Journal.all_objects
                .select_for_update()
                .filter(
                    issn__iexact=normalized_issn
                )
                .first()
            )

            if journal is None:
                raise

    if not created:
        was_deleted = journal.is_deleted

        if was_deleted:
            journal.restore()

        update_fields = []

        if journal.issn != normalized_issn:
            journal.issn = normalized_issn
            update_fields.append(
                "issn"
            )

        if journal.title != normalized_title:
            journal.title = normalized_title
            update_fields.append(
                "title"
            )

        if editorial_id is not None:
            journal.editorial_id = editorial_id
            update_fields.append(
                "editorial_id"
            )

        if publication_date is not None:
            journal.publication_date = publication_date
            update_fields.append("publication_date")

        if url_image is not None:
            journal.url_image = url_image
            update_fields.append(
                "url_image"
            )

        if has_apc is not None:
            journal.has_apc = has_apc
            update_fields.append(
                "has_apc"
            )

        journal.fetched_at = now
        update_fields.append("fetched_at")

        if was_deleted:
            journal.active = False
            # Una revista restaurada requiere una nueva validación.
            journal.validated_by = None
            journal.validated_at = None

            update_fields.extend(
                [
                    "active",
                    "validated_by",
                    "validated_at",
                ]
            )

        journal.updated_by = user
        journal.updated_at = now

        update_fields.extend(
            [
                "updated_by",
                "updated_at",
            ]
        )

        journal.save(
            update_fields=list(
                dict.fromkeys(
                    update_fields
                )
            )
        )

    relation_values = {
        "language_ids": language_ids,
        "country_ids": country_ids,
        "material_type_ids": material_type_ids,
        "academic_program_ids": academic_program_ids,
    }

    for (
        input_field,
        through_model,
        relation_field,
        target_model,
    ) in JOURNAL_RELATION_CONFIG:

        relation_ids = relation_values[
            input_field
        ]

        if relation_ids is None:
            continue

        _sync_relation_ids(
            journal=journal,
            ids=relation_ids,
            through_model=through_model,
            relation_field=relation_field,
            target_model=target_model,
            input_field=input_field,
            user=user,
        )

    journal_platform = _sync_source_platform(
        journal=journal,
        platform_id=platform_id,
        has_full_text=has_full_text,
        user=user,
    )
    platform_services.register_link_url(
        platform=journal_platform.platform,
        journal_platform=journal_platform,
        url=journal_url,
        user=user,
    )

    recalculate_journals(
        [journal.pk],
        user=user,
        invalidate_on_change=False,
    )

    if not created and (journal.active or journal.validated_at is not None):
        journal.active = False
        journal.validated_by = None
        journal.validated_at = None
        journal.updated_by = user
        journal.updated_at = now
        journal.save(update_fields=[
            "active", "validated_by", "validated_at", "updated_by", "updated_at",
        ])

    recalculate_platforms(related_platform_ids([journal.pk]), user=user)

    return journal
