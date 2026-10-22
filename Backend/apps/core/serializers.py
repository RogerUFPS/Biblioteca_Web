from dataclasses import dataclass
from datetime import date, time
from typing import Any

from .models import AuditableModel

from .relations import sync_auditable_relations


@dataclass(frozen=True)
class RelationConfig:
    """
    Configuración declarativa de una relación mediante tabla intermedia
    con soporte de borrado lógico.

    Una relación puede ser:

    - simple: extra_fields=()
    - enriquecida: extra_fields contiene los campos propios del vínculo
    """

    data_field: str
    through_model: type[AuditableModel]
    relation_field: str
    extra_fields: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()
    delete_explanation: str | None = None


class SoftDeleteRelationSyncMixin:
    """
    Mixin reutilizable para sincronizar relaciones mediante tablas
    intermedias auditables que implementan Soft Delete.

    Soporta relaciones simples y relaciones enriquecidas utilizando
    un único algoritmo de sincronización.

    Relación simple:

        Journal -> Language

        languages = [1, 2, 3]

    Relación enriquecida:

        Journal -> Platform

        platforms = [
            {
                "platform": 1,
                "start_period": "2026-01-01",
                "finish_period": "2026-12-31",
                "has_full_text": True,
            }
        ]

    La atomicidad de la operación completa debe garantizarla el
    serializer concreto mediante transaction.atomic().
    """

    relation_config: tuple[RelationConfig, ...] = ()
    relation_parent_field: str | None = None

    relation_delete_explanation = (
        "Relación eliminada durante la actualización."
    )

    def _get_parent_lookup(self, parent: Any) -> dict[str, Any]:
        """
        Construye el filtro utilizado para localizar las relaciones
        pertenecientes a la entidad principal.
        """
        if not self.relation_parent_field:
            raise NotImplementedError(
                "relation_parent_field debe estar definido."
            )

        return {
            self.relation_parent_field: parent,
        }

    def _get_relation_user(self, parent: Any) -> Any:
        """
        Obtiene el usuario responsable de la modificación de la relación.

        En una actualización se utiliza updated_by; durante una creación
        se utiliza created_by.
        """
        user = (
            getattr(parent, "updated_by", None)
            or getattr(parent, "created_by", None)
        )

        if user is None:
            raise ValueError(
                "No fue posible determinar el usuario responsable "
                "de la modificación de la relación."
            )

        return user

    def _get_delete_explanation(
        self,
        config: RelationConfig,
    ) -> str:
        """
        Obtiene la explicación específica de eliminación de la relación.
        """
        return (
            config.delete_explanation
            or self.relation_delete_explanation
        )

    def _extract_relation_data(
        self,
        validated_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Extrae únicamente las relaciones que fueron enviadas
        explícitamente en la petición.

        Esto permite distinguir correctamente entre:

        - campo omitido: no modificar la relación;
        - lista vacía: eliminar todas las relaciones activas.
        """
        relation_data = {}

        for config in self.relation_config:
            if config.data_field in validated_data:
                relation_data[config.data_field] = validated_data.pop(
                    config.data_field
                )

        return relation_data

    def _normalize_relation_data(
        self,
        relation_data: list[Any],
        config: RelationConfig,
    ) -> dict[Any, dict[str, Any]]:
        """
        Normaliza relaciones simples y enriquecidas al mismo formato:

            {
                related_id: data
            }

        Para relaciones simples, data contiene únicamente la entidad
        relacionada.

        Para relaciones enriquecidas, data conserva la entidad relacionada
        y los atributos propios de la relación.
        """
        normalized = {}

        if config.extra_fields:
            for item in relation_data:
                related_object = item[config.relation_field]

                normalized[related_object.pk] = item

            return normalized

        for related_object in relation_data:
            normalized[related_object.pk] = {
                config.relation_field: related_object,
            }

        return normalized

    def _sync_relation(
        self,
        parent: Any,
        relation_data: list[Any],
        config: RelationConfig,
    ) -> None:
        """
        Sincroniza una relación individual, independientemente de que
        sea simple o enriquecida.
        """
        parent_lookup = self._get_parent_lookup(parent)
        user = self._get_relation_user(parent)

        normalized_relation_data = self._normalize_relation_data(
            relation_data=relation_data,
            config=config,
        )

        sync_auditable_relations(
            through_model=config.through_model,
            parent_lookup=parent_lookup,
            related_field=config.relation_field,
            desired_by_id=normalized_relation_data,
            user=user,
            delete_explanation=self._get_delete_explanation(config),
            extra_fields=config.extra_fields,
        )

    def _sync_relations(
        self,
        parent: Any,
        relation_data: dict[str, Any],
    ) -> None:
        """
        Sincroniza todas las relaciones configuradas que hayan sido
        incluidas explícitamente en la petición.
        """
        for config in self.relation_config:
            if config.data_field not in relation_data:
                continue

            self._sync_relation(
                parent=parent,
                relation_data=relation_data[config.data_field],
                config=config,
            )

    @staticmethod
    def _represent_extra_value(value: Any) -> Any:
        """
        Convierte valores de fecha/hora a una representación JSON
        estándar sin depender de los campos internos del serializer.

        El resto de valores se devuelve sin modificar para que su
        representación siga dependiendo del serializer/renderer que
        consume el resultado.
        """
        if isinstance(value, (date, time)):
            return value.isoformat()

        return value

    def _represent_relations(
        self,
        instance: Any,
        representation: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Representa todas las relaciones activas configuradas.

        Relaciones simples:

            ["id1", "id2", ...]

        Relaciones enriquecidas:

            [
                {
                    "platform": 1,
                    "start_period": "2026-01-01",
                    "finish_period": "2026-12-31",
                    "has_full_text": True,
                }
            ]
        """
        parent_lookup = self._get_parent_lookup(instance)

        for config in self.relation_config:
            queryset = config.through_model.objects.filter(
                **parent_lookup
            )

            if config.ordering:
                queryset = queryset.order_by(*config.ordering)

            if not config.extra_fields:
                representation[config.data_field] = list(
                    queryset.values_list(
                        f"{config.relation_field}_id",
                        flat=True,
                    )
                )
                continue

            representation[config.data_field] = [
                {
                    config.relation_field: getattr(
                        link,
                        f"{config.relation_field}_id",
                    ),
                    **{
                        field_name: self._represent_extra_value(
                            getattr(link, field_name)
                        )
                        for field_name in config.extra_fields
                    },
                }
                for link in queryset
            ]

        return representation
