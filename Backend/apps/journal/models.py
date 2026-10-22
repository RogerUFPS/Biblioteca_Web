from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.catalog.models import (
    AcademicProgram,
    Country,
    Editorial,
    KnowledgeArea,
    Language,
    MaterialType,
)
from apps.core.models import AuditableModel
from apps.platforms.models import Platform


class Journal(AuditableModel):
    """
    Revista académica o científica indexada en una o varias plataformas.

    La deduplicación se realiza exclusivamente por ISSN.
    El ISSN almacenado corresponde al ISSN digital de la revista.
    """

    issn = models.CharField(
        max_length=9,
        help_text="ISSN digital de la revista (formato esperado: XXXX-XXXX).",
    )

    title = models.CharField(
        max_length=500,
        help_text="Título completo de la revista.",
    )

    editorial = models.ForeignKey(
        Editorial,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journals",
        help_text="Editorial responsable de la publicación.",
    )

    url_image = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="URL de la imagen o logotipo de la revista.",
    )

    has_apc = models.BooleanField(
        default=False,
        help_text="Indica si la revista cobra cargos por procesamiento de artículos (APC).",
    )

    active = models.BooleanField(
        default=False,
        help_text="Indica si la revista se encuentra actualmente activa.",
    )

    publication_date = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha propia de publicación u origen de la revista.",
    )

    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="validated_journals",
    )

    validated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    fetched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha de la última obtención o actualización mediante cosecha.",
    )

    class Meta:
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                Lower("issn"),
                name="unique_journal_issn_ci",
            )
        ]

    def __str__(self):
        return f"{self.title} ({self.issn})"


class License(AuditableModel):
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="unique_journal_license_name_ci",
            )
        ]

    def __str__(self):
        return self.name


# ==============================================================================
# TABLAS INTERMEDIAS DE CLASIFICACIÓN (SharedJournal*)
# ==============================================================================


class SharedJournalLanguage(AuditableModel):

    journal = models.ForeignKey(
        Journal,
        on_delete=models.PROTECT,
        related_name="language_links",
    )

    language = models.ForeignKey(
        Language,
        on_delete=models.PROTECT,
        related_name="journal_links",
    )

    class Meta:
        ordering = ["journal_id", "language_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "language"],
                name="unique_journal_language",
            )
        ]

    def __str__(self):
        return f"{self.journal} <-> {self.language}"


class SharedJournalCountry(AuditableModel):

    journal = models.ForeignKey(
        Journal,
        on_delete=models.PROTECT,
        related_name="country_links",
    )

    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="journal_links",
    )

    class Meta:
        ordering = ["journal_id", "country_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "country"],
                name="unique_journal_country",
            )
        ]

    def __str__(self):
        return f"{self.journal} <-> {self.country}"


class SharedJournalKnowledgeArea(AuditableModel):

    is_manual = models.BooleanField(
        default=False,
        help_text="Indica si el área fue seleccionada manualmente en la revista.",
    )

    is_derived = models.BooleanField(
        default=False,
        help_text="Indica si el área proviene de programas académicos vigentes.",
    )

    journal = models.ForeignKey(
        Journal,
        on_delete=models.PROTECT,
        related_name="knowledge_area_links",
    )

    knowledge_area = models.ForeignKey(
        KnowledgeArea,
        on_delete=models.PROTECT,
        related_name="journal_links",
    )

    class Meta:
        ordering = ["journal_id", "knowledge_area_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "knowledge_area"],
                name="unique_journal_knowledge_area",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(deleted_at__isnull=False)
                    | models.Q(is_manual=True)
                    | models.Q(is_derived=True)
                ),
                name="journal_area_active_has_origin",
            ),
        ]

    def __str__(self):
        return f"{self.journal} <-> {self.knowledge_area}"

    @property
    def editable(self):
        return self.is_manual and not self.is_derived

    def soft_delete(self, user, explanation: str):
        if not explanation or not explanation.strip():
            raise ValueError("Se requiere una explicación para eliminar.")
        self.is_manual = False
        self.is_derived = False
        self.deleted_by = user
        self.deleted_at = timezone.now()
        self.delete_explanation = explanation.strip()
        self.save(update_fields=[
            "is_manual", "is_derived", "deleted_by", "deleted_at",
            "delete_explanation",
        ])

    def restore(self):
        raise ValueError(
            "SharedJournalKnowledgeArea debe restaurarse indicando su procedencia."
        )


class SharedJournalMaterialType(AuditableModel):

    journal = models.ForeignKey(
        Journal,
        on_delete=models.PROTECT,
        related_name="material_type_links",
    )

    material_type = models.ForeignKey(
        MaterialType,
        on_delete=models.PROTECT,
        related_name="journal_links",
    )

    class Meta:
        ordering = ["journal_id", "material_type_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "material_type"],
                name="unique_journal_material_type",
            )
        ]

    def __str__(self):
        return f"{self.journal} <-> {self.material_type}"


class SharedJournalAcademicProgram(AuditableModel):

    journal = models.ForeignKey(
        Journal,
        on_delete=models.PROTECT,
        related_name="academic_program_links",
    )

    academic_program = models.ForeignKey(
        AcademicProgram,
        on_delete=models.PROTECT,
        related_name="journal_links",
    )

    class Meta:
        ordering = ["journal_id", "academic_program_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "academic_program"],
                name="unique_journal_academic_program",
            )
        ]

    def __str__(self):
        return f"{self.journal} <-> {self.academic_program}"


class SharedJournalPlatform(AuditableModel):
    """
    Relación entre una revista y una plataforma.

    Indica que una determinada plataforma indexa la revista y
    almacena información específica de esa cobertura.
    """

    journal = models.ForeignKey(
        Journal,
        on_delete=models.PROTECT,
        related_name="platform_links",
    )

    platform = models.ForeignKey(
        Platform,
        on_delete=models.PROTECT,
        related_name="journal_links",
    )

    start_period = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha o período inicial de cobertura de la revista en la plataforma.",
    )

    finish_period = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Fecha o período final de cobertura de la revista "
            "en la plataforma."
        ),
    )

    has_full_text = models.BooleanField(
        default=False,
        help_text=(
            "Indica si la plataforma ofrece acceso al texto completo "
            "de la revista."
        ),
    )

    class Meta:
        ordering = ["journal_id", "platform_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "platform"],
                name="unique_journal_platform",
            )
        ]

    def __str__(self):
        return f"{self.journal} <-> {self.platform}"

    def clean(self):
        super().clean()
        errors = {}
        if self.start_period is None:
            errors["start_period"] = "La fecha de vinculación es obligatoria."
        if (
            self.start_period is not None
            and self.finish_period is not None
            and self.finish_period < self.start_period
        ):
            errors["finish_period"] = (
                "La fecha de finalización no puede ser anterior "
                "a la fecha de vinculación."
            )
        if (
            self.start_period is not None
            and self.platform_id is not None
            and self.platform.start_period is not None
            and self.start_period < self.platform.start_period
        ):
            errors["start_period"] = (
                "La fecha de vinculación no puede ser anterior "
                "a la fecha de registro de la plataforma."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        today = timezone.localdate()
        normalized_fields = []
        if self._state.adding:
            self.start_period = today
            self.finish_period = None
        elif self.start_period is None:
            self.start_period = (
                timezone.localtime(self.created_at).date()
                if self.created_at is not None
                else today
            )
            normalized_fields.append("start_period")

        if not self._state.adding:
            expected_finish = today if self.deleted_at is not None else None
            if self.finish_period != expected_finish:
                self.finish_period = expected_finish
                normalized_fields.append("finish_period")

        self.clean()
        if normalized_fields and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = list(dict.fromkeys([
                *kwargs["update_fields"],
                *normalized_fields,
            ]))
        return super().save(*args, **kwargs)

    def soft_delete(self, user, explanation: str):
        super().soft_delete(user=user, explanation=explanation)
        self.finish_period = timezone.localdate()
        self.save(update_fields=["finish_period"])

    def restore(self):
        super().restore()
        self.finish_period = None
        self.save(update_fields=["finish_period"])


class SharedJournalLicense(AuditableModel):
    journal = models.ForeignKey(
        Journal,
        on_delete=models.PROTECT,
        related_name="license_links",
    )
    license = models.ForeignKey(
        License,
        on_delete=models.PROTECT,
        related_name="journal_links",
    )

    class Meta:
        ordering = ["journal_id", "license_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "license"],
                name="unique_journal_license",
            )
        ]

    def __str__(self):
        return f"{self.journal} <-> {self.license}"
