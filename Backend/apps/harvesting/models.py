from django.db import models

from apps.core.models import AuditableModel
from apps.platforms.models import Platform


class Schedule(AuditableModel):
    """
    Programación periódica de cosechas para una o más plataformas.

    El usuario define la fecha inicial, frecuencia y límites de las ejecuciones.
    """

    class Frequency(models.TextChoices):
        ONCE = "once", "ONCE"
        DAILY = "daily", "DAILY"
        WEEKLY = "weekly", "WEEKLY"
        MONTHLY = "monthly", "MONTHLY"

    platforms = models.ManyToManyField(
        Platform,
        related_name="schedules",
        help_text="Plataformas académicas incluidas en esta programación.",
    )

    frequency = models.CharField(
        max_length=20,
        choices=Frequency.choices,
        default=Frequency.ONCE,
        help_text="Frecuencia con la que se ejecutará la recolección.",
    )

    max_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    stop_after_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    start_date = models.DateTimeField(
        help_text="Fecha y hora de la primera ejecución programada.",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Schedule #{self.pk} ({self.get_frequency_display()})"


class ScheduleEvent(AuditableModel):
    class State(models.TextChoices):
        PENDING = "pending", "PENDING"
        RUNNING = "running", "RUNNING"
        COMPLETED = "completed", "COMPLETED"
        FAILED = "failed", "FAILED"

    schedule = models.ForeignKey(
        Schedule,
        on_delete=models.PROTECT,
        related_name="events",
    )
    scheduled_for = models.DateTimeField()
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.PENDING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-scheduled_for"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "scheduled_for"],
                name="unique_schedule_event_occurrence",
            ),
        ]

    def __str__(self):
        return f"Schedule event #{self.pk} - {self.scheduled_for}"


class Harvest(AuditableModel):

    class State(models.TextChoices):
        PENDING = "pending", "PENDING"
        RUNNING = "running", "RUNNING"
        PAUSING = "pausing", "PAUSING"
        COMPLETED = "completed", "COMPLETED"
        FAILED = "failed", "FAILED"
        CANCELLED = "cancelled", "CANCELLED"
        PAUSED = "paused", "PAUSED"

    platform = models.ForeignKey(
        Platform,
        on_delete=models.PROTECT,
        related_name="harvests",
        help_text="Plataforma de la cual se cosechan las revistas.",
    )

    schedule = models.ForeignKey(
        Schedule,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="harvests",
    )

    event = models.ForeignKey(
        ScheduleEvent,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="harvests",
    )

    api_cursor = models.CharField(
        max_length=2000,
        blank=True,
        default="",
        help_text="Cursor o token de paginación proporcionado por la API de la plataforma. Gestionado automáticamente.",
    )

    api_marker = models.PositiveIntegerField(
        default=0,
        help_text="Índice del registro siguiente dentro de la respuesta XML pendiente.",
    )

    api_page = models.TextField(
        blank=True,
        default="",
        help_text="Respuesta de página pendiente para continuar sin volver a solicitarla.",
    )

    worker_checkpoint = models.PositiveIntegerField(
        default=0,
        help_text="Versión del progreso procesada por los workers; evita pasos duplicados.",
    )

    worker_elapsed_milliseconds = models.PositiveBigIntegerField(
        default=0,
        help_text="Tiempo activo acumulado procesando pasos del worker.",
    )

    worker_dispatched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Último despacho o paso confirmado por el worker de cosecha.",
    )

    max_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Cantidad máxima de registros a procesar en esta ejecución.",
    )

    stop_after_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Tiempo máximo en minutos antes de detener la cosecha.",
    )

    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.PENDING,
        help_text="Estado actual del ciclo de vida de la cosecha. Gestionado automáticamente.",
    )

    records_added = models.PositiveIntegerField(
        default=0,
        help_text="Cantidad de revistas nuevas insertadas.",
    )

    records_updated = models.PositiveIntegerField(
        default=0,
        help_text="Cantidad de revistas existentes actualizadas.",
    )

    records_failed = models.PositiveIntegerField(
        default=0,
        help_text="Cantidad de registros que no pudieron ser procesados o fallaron validaciones.",
    )

    elapsed_seconds = models.PositiveIntegerField(
        default=0,
        help_text="Tiempo acumulado de ejecución activa, excluyendo los periodos pausados.",
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha y hora en la que inició la ejecución. Se registra automáticamente.",
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha y hora en la que finalizó o se detuvo la cosecha. Se registra automáticamente.",
    )

    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Detalle del error en caso de fallo. Se registra automáticamente.",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["platform"],
                condition=models.Q(state__in=["pending", "running", "pausing", "paused"]),
                name="unique_active_harvest_per_platform",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_quantity__isnull=False)
                    | models.Q(stop_after_minutes__isnull=False)
                ),
                name="harvest_requires_max_quantity_or_stop_after_minutes",
            ),
        ]

    def __str__(self):
        return f"Harvest #{self.pk} - {self.platform.name} [{self.get_state_display()}]"


class HarvestJournal(models.Model):
    class Result(models.TextChoices):
        ADDED = "added", "Added"
        UPDATED = "updated", "Updated"

    harvest = models.ForeignKey(
        Harvest,
        on_delete=models.CASCADE,
        related_name="journal_records",
    )
    journal = models.ForeignKey(
        "journal.Journal",
        on_delete=models.PROTECT,
        related_name="harvest_records",
    )
    result = models.CharField(
        max_length=10,
        choices=Result.choices,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["journal__title", "journal_id"]

    def __str__(self):
        return f"Harvest #{self.harvest_id}: Journal #{self.journal_id} ({self.result})"
