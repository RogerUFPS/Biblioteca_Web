import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.decorators import (
    action,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework import status, viewsets
from rest_framework.response import Response

from apps.core.viewsets import AuditableViewSet, get_acting_user
from apps.journal.models import Journal
from apps.journal.serializers import JournalSerializer
from . import filters, models, serializers
from . import services

logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(
        summary="Listar programaciones de cosecha",
        tags=["Cosecha - Programaciones"],
    ),
    retrieve=extend_schema(
        summary="Consultar programación de cosecha",
        tags=["Cosecha - Programaciones"],
    ),
    create=extend_schema(
        summary="Crear programación de cosecha",
        tags=["Cosecha - Programaciones"],
    ),
    update=extend_schema(
        summary="Actualizar programación de cosecha",
        tags=["Cosecha - Programaciones"],
    ),
    partial_update=extend_schema(
        summary="Actualizar parcialmente programación de cosecha",
        tags=["Cosecha - Programaciones"],
    ),
    destroy=extend_schema(
        summary="Desactivar programación de cosecha",
        description=(
            "No necesita cuerpo si la programación puede eliminarse "
            "permanentemente. Si tiene registros dependientes, se debe enviar "
            "`delete_explanation` para archivarla."
        ),
        request=inline_serializer(
            name="ScheduleDeleteRequest",
            fields={
                "delete_explanation": drf_serializers.CharField(
                    required=False,
                    allow_blank=False,
                    max_length=500,
                ),
            },
        ),
        tags=["Cosecha - Programaciones"],
    ),
    restore=extend_schema(
        summary="Restaurar programación de cosecha",
        request=None,
        tags=["Cosecha - Programaciones"],
    ),
)
class ScheduleViewSet(AuditableViewSet):
    queryset = models.Schedule.objects.prefetch_related("platforms").all()
    serializer_class = serializers.ScheduleSerializer
    filterset_class = filters.ScheduleFilter
    search_fields = ["platforms__name"]
    ordering_fields = ["created_at", "start_date"]
    ordering = ["-created_at"]

    @extend_schema(
        summary="Procesar cosechas programadas vencidas",
        description=(
            "Evalúa las programaciones vencidas y encola sus cosechas para "
            "procesamiento asíncrono."
        ),
        request=None,
        responses={
            200: serializers.HarvestSerializer(many=True),
            202: serializers.HarvestSerializer(many=True),
            503: serializers.HarvestQueueErrorSerializer,
        },
        tags=["Cosecha - Programaciones"],
    )
    @action(detail=False, methods=["post"], url_path="run-due",authentication_classes=[],
    permission_classes=[AllowAny])
    def run_due(self, request):
        try:
            harvests = services.run_scheduled_harvests()
        except Exception as exc:
            logger.exception("No se pudieron encolar las cosechas vencidas.")
            return Response(
                {"detail": f"No se pudieron encolar las cosechas: {exc}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        response_status = status.HTTP_202_ACCEPTED if harvests else status.HTTP_200_OK
        return Response(
            serializers.HarvestSerializer(harvests, many=True).data,
            status=response_status,
        )


class ScheduleEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.ScheduleEvent.objects.select_related("schedule").prefetch_related(
        "harvests",
    )
    serializer_class = serializers.ScheduleEventSerializer
    filterset_fields = ["schedule", "state"]
    ordering_fields = ["scheduled_for", "started_at", "finished_at"]
    ordering = ["-scheduled_for"]


class HarvestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.Harvest.objects.select_related(
        "platform",
        "schedule",
        "event",
    ).all()
    serializer_class = serializers.HarvestSerializer
    filterset_class = filters.HarvestFilter
    search_fields = ["platform__name"]
    ordering_fields = ["created_at", "started_at", "finished_at", "records_added"]
    ordering = ["-created_at"]

    @extend_schema(
        summary="Listar revistas agregadas por una cosecha",
        description=(
            "Devuelve las revistas nuevas creadas por esta ejecución. "
            "Las revistas actualizadas no se incluyen."
        ),
        request=None,
        responses={200: JournalSerializer(many=True)},
        tags=["Cosecha - Ejecuciones"],
    )
    @action(detail=True, methods=["get"], url_path="journals")
    def journals(self, request, pk=None):
        harvest = self.get_object()
        journals = Journal.all_objects.filter(
            harvest_records__harvest=harvest,
            harvest_records__result=models.HarvestJournal.Result.ADDED,
        ).distinct().order_by("title", "pk")
        page = self.paginate_queryset(journals)
        if page is not None:
            return self.get_paginated_response(
                JournalSerializer(page, many=True).data,
            )
        return Response(JournalSerializer(journals, many=True).data)

    @extend_schema(
        summary="Pausar una cosecha",
        description=(
            "Solicita detener la cosecha después del registro que procesa el "
            "worker. Una cosecha pendiente se pausa inmediatamente."
        ),
        request=None,
        responses={200: serializers.HarvestSerializer, 202: serializers.HarvestSerializer},
        tags=["Cosecha - Ejecuciones"],
    )
    @action(detail=True, methods=["post"], url_path="pause")
    def pause(self, request, pk=None):
        with transaction.atomic():
            harvest = get_object_or_404(
                self.get_queryset().select_for_update(of=("self",)),
                pk=pk,
            )
            if harvest.state == models.Harvest.State.PENDING:
                harvest.state = models.Harvest.State.PAUSED
            elif harvest.state == models.Harvest.State.RUNNING:
                harvest.state = models.Harvest.State.PAUSING
            else:
                return Response(
                    {"detail": f"No se puede pausar una cosecha en estado '{harvest.state}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            harvest.updated_by = get_acting_user(request)
            harvest.updated_at = timezone.now()
            harvest.save(update_fields=["state", "updated_by", "updated_at"])

        response_status = (
            status.HTTP_202_ACCEPTED
            if harvest.state == models.Harvest.State.PAUSING
            else status.HTTP_200_OK
        )
        return Response(serializers.HarvestSerializer(harvest).data, status=response_status)

    @extend_schema(
        summary="Reanudar una cosecha pausada",
        description="Encola la continuación desde el checkpoint guardado en el Harvest.",
        request=None,
        responses={
            202: serializers.HarvestSerializer,
            400: serializers.HarvestQueueErrorSerializer,
            503: serializers.HarvestQueueErrorSerializer,
        },
        tags=["Cosecha - Ejecuciones"],
    )
    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, pk=None):
        with transaction.atomic():
            harvest = get_object_or_404(
                self.get_queryset().select_for_update(of=("self",)),
                pk=pk,
            )
            if harvest.state != models.Harvest.State.PAUSED:
                return Response(
                    {
                        "detail": (
                            "Solo se pueden reanudar cosechas en estado "
                            f"'{models.Harvest.State.PAUSED}'."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            harvest.state = models.Harvest.State.PENDING
            harvest.error_message = None
            harvest.updated_by = get_acting_user(request)
            harvest.updated_at = timezone.now()
            harvest.save(
                update_fields=[
                    "state",
                    "error_message",
                    "updated_by",
                    "updated_at",
                ]
            )

        try:
            harvest = services.dispatch_harvest_to_worker(harvest)
        except Exception as exc:
            logger.exception("Error al reanudar la cosecha #%s", harvest.pk)
            harvest.refresh_from_db()
            return Response(
                {
                    "detail": f"Error al encolar la cosecha: {exc}",
                    "harvest": serializers.HarvestSerializer(harvest).data,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            serializers.HarvestSerializer(harvest).data,
            status=status.HTTP_202_ACCEPTED,
        )
