"""Motor genérico para sincronizar relaciones intermedias auditables."""

from collections.abc import Iterable, Mapping
from typing import Any

from django.utils import timezone


def sync_auditable_relations(
    *,
    through_model,
    parent_lookup: Mapping[str, Any],
    related_field: str,
    desired_by_id: Mapping[Any, Mapping[str, Any]],
    user,
    delete_explanation: str,
    extra_fields: Iterable[str] = (),
    existing_links=None,
) -> bool:
    """Aplica remove/restore/create/update sin escribir cuando no hay cambios."""
    links = list(existing_links) if existing_links is not None else list(
        through_model.all_objects.filter(**parent_lookup)
    )
    active_by_id = {
        getattr(link, f"{related_field}_id"): link
        for link in links
        if link.deleted_at is None
    }
    archived_by_id = {
        getattr(link, f"{related_field}_id"): link
        for link in links
        if link.deleted_at is not None
    }
    current_ids = set(active_by_id)
    desired_ids = set(desired_by_id)
    now = timezone.now()
    changed = False

    for related_id in current_ids - desired_ids:
        link = active_by_id[related_id]
        link.deleted_by = user
        link.deleted_at = now
        link.delete_explanation = delete_explanation
        link.updated_by = user
        link.updated_at = now
        link.save(update_fields=[
            "deleted_by", "deleted_at", "delete_explanation",
            "updated_by", "updated_at",
        ])
        changed = True

    for related_id in desired_ids - current_ids:
        data = desired_by_id[related_id]
        archived = archived_by_id.get(related_id)
        if archived is not None:
            update_fields = [
                "deleted_by", "deleted_at", "delete_explanation",
                "updated_by", "updated_at",
            ]
            archived.deleted_by = None
            archived.deleted_at = None
            archived.delete_explanation = None
            archived.updated_by = user
            archived.updated_at = now
            for field_name in extra_fields:
                if field_name in data and getattr(archived, field_name) != data[field_name]:
                    setattr(archived, field_name, data[field_name])
                    update_fields.append(field_name)
            archived.save(update_fields=update_fields)
        else:
            related_value = data.get(related_field)
            relation_value = (
                {related_field: related_value}
                if related_value is not None
                else {f"{related_field}_id": related_id}
            )
            through_model.objects.create(
                **parent_lookup,
                **relation_value,
                **{
                    field_name: data[field_name]
                    for field_name in extra_fields
                    if field_name in data
                },
                created_by=user,
            )
        changed = True

    for related_id in current_ids & desired_ids:
        link = active_by_id[related_id]
        data = desired_by_id[related_id]
        update_fields = []
        for field_name in extra_fields:
            if field_name in data and getattr(link, field_name) != data[field_name]:
                setattr(link, field_name, data[field_name])
                update_fields.append(field_name)
        if update_fields:
            link.updated_by = user
            link.updated_at = now
            link.save(update_fields=[*update_fields, "updated_by", "updated_at"])
            changed = True

    return changed


def sync_auditable_relation_ids(
    *,
    through_model,
    parent_field: str,
    parent_id: int,
    related_field: str,
    desired_ids: Iterable[int],
    user,
    delete_explanation: str,
    existing_links=None,
) -> bool:
    """Adaptador compacto para relaciones simples expresadas solo con IDs."""
    return sync_auditable_relations(
        through_model=through_model,
        parent_lookup={f"{parent_field}_id": parent_id},
        related_field=related_field,
        desired_by_id={related_id: {} for related_id in set(desired_ids)},
        user=user,
        delete_explanation=delete_explanation,
        existing_links=existing_links,
    )

