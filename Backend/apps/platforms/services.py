import ipaddress
import socket
from typing import cast
from urllib.parse import urlsplit

import httpx
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import models


LINK_CHECK_TIMEOUT_SECONDS = 10.0
SYNTAX_SIMILARITY_LIMIT = 5
SYNTAX_SIMILARITY_THRESHOLD = 70

# Estos códigos indican que el servidor/recurso existe,
# aunque requiera autenticación o restrinja el acceso.
LINK_ACTIVE_AUTH_STATUSES = {401, 403}
# El contexto vigente es siempre el evento más reciente. No se ordena por
# last_check porque NULL representa "sin verificar", no menor antigüedad.
LINK_LOG_ORDERING = ("-created_at", "-pk")
BLOCKED_METADATA_HOSTS = {
    "instance-data.ec2.internal",
    "metadata.azure.internal",
    "metadata.google.internal",
}


def _normalize_syntax_value(value):
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {key: _normalize_syntax_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_syntax_value(item) for item in value]
    return value


def normalized_syntax_configuration(data: dict) -> dict:
    return _normalize_syntax_value({
        "booleans": data.get("booleans", []),
        "parenthesis": data.get("parenthesis", False),
        "fields": data.get("fields", {}),
    })


def syntax_comparison(candidate: dict, existing: dict) -> dict:
    candidate = normalized_syntax_configuration(candidate)
    existing = normalized_syntax_configuration(existing)
    comparable = ["booleans", "parenthesis"]
    comparable.extend(
        f"fields.{key}"
        for key in sorted(set(candidate["fields"]) | set(existing["fields"]))
        if candidate["fields"].get(key) or existing["fields"].get(key)
    )
    matching = []
    different = []
    for field in comparable:
        if field.startswith("fields."):
            key = field.split(".", 1)[1]
            left = candidate["fields"].get(key)
            right = existing["fields"].get(key)
        else:
            left, right = candidate[field], existing[field]
        (matching if left == right else different).append(field)
    similarity = round((len(matching) / len(comparable)) * 100) if comparable else 0
    return {
        "similarity": similarity,
        "matching_fields": matching,
        "different_fields": different,
    }


def find_identical_syntax(configuration: dict, *, exclude_id=None):
    queryset = models.ValidSintaxis.objects.all()
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    for syntax in queryset:
        if syntax_comparison(configuration, {
            "booleans": syntax.booleans,
            "parenthesis": syntax.parenthesis,
            "fields": syntax.fields,
        })["similarity"] == 100:
            return syntax
    return None


def similar_syntaxes(configuration: dict) -> list[dict]:
    results = []
    for syntax in models.ValidSintaxis.objects.all():
        comparison = syntax_comparison(configuration, {
            "booleans": syntax.booleans,
            "parenthesis": syntax.parenthesis,
            "fields": syntax.fields,
        })
        if comparison["similarity"] >= SYNTAX_SIMILARITY_THRESHOLD:
            results.append({"id": syntax.pk, "name": syntax.name, **comparison})
    return sorted(results, key=lambda item: (-item["similarity"], item["id"]))[
        :SYNTAX_SIMILARITY_LIMIT
    ]


def latest_platform_link_log(platform):
    """Retorna el último log no eliminado de la URL general."""
    prefetched = getattr(platform, "_public_link_logs", None)
    if prefetched is not None:
        return prefetched[0] if prefetched else None

    return (
        models.LinkCheckLog.objects
        .filter(platform=platform, journal_platform__isnull=True)
        .order_by(*LINK_LOG_ORDERING)
        .first()
    )


def latest_journal_link_log(journal_platform):
    """Retorna el último log no eliminado de una revista-plataforma."""
    prefetched = getattr(journal_platform, "_journal_link_logs", None)
    if prefetched is not None:
        return prefetched[0] if prefetched else None

    return (
        models.LinkCheckLog.objects
        .filter(journal_platform=journal_platform)
        .order_by(*LINK_LOG_ORDERING)
        .first()
    )


def link_verification_status(link_log) -> str:
    if link_log.last_check is None:
        return "unverified"
    return "available" if link_log.is_active else "unavailable"


def register_link_url(
    *,
    platform: models.Platform,
    url: str,
    user,
    journal_platform=None,
) -> models.LinkCheckLog:
    """
    Registra una URL nueva sin sobrescribir el historial.

    Si la URL coincide con la vigente para el mismo contexto, reutiliza
    el log actual y evita crear un registro redundante.
    """
    validate_safe_http_url(url)

    if journal_platform is None:
        latest_log = (
            models.LinkCheckLog.objects
            .filter(platform=platform, journal_platform__isnull=True)
            .order_by(*LINK_LOG_ORDERING)
            .first()
        )
    else:
        if journal_platform.deleted_at is not None:
            raise ValidationError({
                "journal_url": (
                    "No se puede registrar una URL para una relación "
                    "revista-plataforma archivada."
                )
            })
        if journal_platform.platform_id != platform.pk:
            raise ValidationError({
                "journal_platform": (
                    "La relación revista-plataforma debe pertenecer a la "
                    "misma plataforma del enlace."
                )
            })
        latest_log = (
            models.LinkCheckLog.objects
            .filter(journal_platform=journal_platform)
            .order_by(*LINK_LOG_ORDERING)
            .first()
        )

    if latest_log is not None and latest_log.url == url:
        return latest_log

    link_log = models.LinkCheckLog.objects.create(
        platform=platform,
        journal_platform=journal_platform,
        url=url,
        is_active=False,
        last_check=None,
        created_by=user,
    )
    if hasattr(platform, "_public_link_logs"):
        delattr(platform, "_public_link_logs")
    if (
        journal_platform is not None
        and hasattr(journal_platform, "_journal_link_logs")
    ):
        delattr(journal_platform, "_journal_link_logs")
    return link_log


REQUIRED_PLATFORM_RELATIONS = (
    (
        "institutions",
        models.SharedPlatformSupport,
        "institution",
        "una institución responsable activa asociada",
    ),
    (
        "countries",
        models.SharedPlatformCountry,
        "country",
        "un país activo asociado",
    ),
    (
        "material_types",
        models.SharedPlatformMaterialType,
        "material_type",
        "un tipo de material activo asociado",
    ),
    (
        "languages",
        models.SharedPlatformLanguage,
        "language",
        "un idioma activo asociado",
    ),
    (
        "knowledge_areas",
        models.SharedPlatformKnowledgeArea,
        "knowledge_area",
        "un área de conocimiento activa asociada",
    ),
    (
        "academic_programs",
        models.SharedPlatformAcademicProgram,
        "academic_program",
        "un programa académico activo asociado",
    ),
)


def validate_platform_for_publication(
    platform: models.Platform,
    *,
    require_draft: bool = True,
) -> None:
    """
    Valida que la plataforma pueda pasar de borrador a publicado.
    """

    errors = {}

    if platform.is_deleted:
        errors["detail"] = (
            "No se puede publicar una plataforma que se encuentra eliminada."
        )

    if require_draft and platform.status != models.Platform.Status.BORRADOR:
        errors["status"] = (
            "Solo una plataforma en borrador puede publicarse."
        )

    if not platform.name or not platform.name.strip():
        errors["name"] = (
            "La plataforma debe tener un nombre."
        )

    # La URL pública es independiente de base_api_url. La URL vigente debe
    # tener una comprobación exitosa antes de publicar.
    current_link = latest_platform_link_log(platform)
    if current_link is None:
        errors["url"] = (
            "La plataforma debe tener una URL pública registrada "
            "en el historial de verificación de enlaces."
        )
    elif current_link.last_check is None:
        errors["url"] = (
            "La URL pública debe verificarse antes de publicar la plataforma."
        )
    elif not current_link.is_active:
        errors["url"] = (
            "La URL pública no se encuentra disponible. Corríjala o "
            "verifíquela nuevamente antes de publicar."
        )

    # Una API Key solamente tiene sentido si existe una API base.
    if platform.encrypted_api_key:
        if not platform.base_api_url or not platform.base_api_url.strip():
            errors["base_api_url"] = (
                "La plataforma debe tener una URL de API "
                "si tiene una API Key configurada."
            )

    if platform.is_harvestable and not platform.base_api_url:
        errors["base_api_url"] = (
            "Una plataforma cosechable debe tener una URL base de API."
        )

    if not platform.url_image:
        errors["url_image"] = (
            "La plataforma debe tener una URL de imagen para publicarse."
        )

    if not platform.is_harvestable and (
        platform.base_api_url or platform.encrypted_api_key
    ):
        errors["is_harvestable"] = (
            "Una plataforma no cosechable no puede conservar "
            "configuración técnica de cosecha."
        )

    # Si no tiene API Key, base_api_url es completamente opcional.

    if not platform.start_period:
        errors["start_period"] = (
            "La plataforma debe tener una fecha de registro administrada "
            "por el sistema."
        )

    if (
        platform.start_period
        and platform.finish_period
        and platform.finish_period < platform.start_period
    ):
        errors["finish_period"] = (
            "La fecha de obsolescencia no puede ser anterior "
            "a la fecha de registro."
        )

    if not platform.valid_sintaxis_id:
        errors["valid_sintaxis"] = (
            "La plataforma debe tener una sintaxis de búsqueda asociada."
        )

    elif not models.ValidSintaxis.objects.filter(
        pk=platform.valid_sintaxis_id,
    ).exists():
        errors["valid_sintaxis"] = (
            "La sintaxis de búsqueda asociada no se encuentra activa."
        )

    for (
        field_name,
        through_model,
        relation_field,
        label,
    ) in REQUIRED_PLATFORM_RELATIONS:

        has_active_relation = through_model.objects.filter(
            platform=platform,
            is_manual=True,
            **{
                f"{relation_field}__deleted_at__isnull": True,
            },
        ).exists() or through_model.objects.filter(
            platform=platform,
            is_derived=True,
            **{f"{relation_field}__deleted_at__isnull": True},
        ).exists()

        if not has_active_relation:
            errors[field_name] = (
                f"La plataforma debe tener al menos {label}."
            )

    if errors:
        raise ValidationError(errors)


def validate_platform_for_obsolete(
    platform: models.Platform,
) -> None:
    """
    Valida que una plataforma pueda pasar de publicado a obsoleto.
    """

    errors = {}

    if platform.is_deleted:
        errors["detail"] = (
            "No se puede modificar una plataforma que se encuentra eliminada."
        )

    if platform.status != models.Platform.Status.PUBLICADO:
        errors["status"] = (
            "Solo una plataforma publicada puede marcarse como obsoleta."
        )

    if errors:
        raise ValidationError(errors)


def validate_platform_for_reactivation(
    platform: models.Platform,
) -> None:
    """
    Valida que una plataforma pueda regresar de obsoleto a borrador.
    """

    errors = {}

    if platform.is_deleted:
        errors["detail"] = (
            "No se puede reactivar una plataforma que se encuentra eliminada."
        )

    if platform.status != models.Platform.Status.OBSOLETO:
        errors["status"] = (
            "Solo una plataforma obsoleta puede regresar a borrador."
        )

    if errors:
        raise ValidationError(errors)


def _is_successful_link_status(
    status_code: int,
) -> bool:
    """
    Determina si un código HTTP representa un enlace disponible.

    Se consideran disponibles:
    - 2xx: respuesta exitosa.
    - 3xx: recurso existente con redirección.
    - 401: recurso existente que requiere autenticación.
    - 403: recurso existente con acceso restringido.
    """

    return (
        200 <= status_code < 400
        or status_code in LINK_ACTIVE_AUTH_STATUSES
    )


def _is_public_ip_address(
    raw_address: str,
) -> bool:
    """
    Determina si una dirección IP es públicamente enrutable.

    Se utiliza como protección para evitar que la verificación
    de enlaces consulte recursos internos del servidor.
    """

    try:
        address = ipaddress.ip_address(
            raw_address.split("%", 1)[0]
        )
    except ValueError:
        return False

    return (
        address.is_global
        and not address.is_multicast
        and not address.is_unspecified
    )


def validate_safe_http_url(
    url: str,
    *,
    field_name: str = "url",
) -> None:
    """
    Valida que una URL pueda consultarse de forma segura.

    Solo admite HTTP/HTTPS y bloquea destinos locales,
    privados, reservados o no públicamente enrutables.
    """

    try:
        parsed_url = urlsplit(url)
        port = parsed_url.port
    except ValueError:
        raise ValidationError({
            field_name: (
                "La URL configurada no es válida."
            )
        })

    if parsed_url.scheme.lower() not in {"http", "https"}:
        raise ValidationError({
            field_name: (
                "La URL debe utilizar el protocolo HTTP o HTTPS."
            )
        })

    hostname = parsed_url.hostname

    if not hostname:
        raise ValidationError({
            field_name: (
                "La URL debe contener un nombre de host válido."
            )
        })

    if parsed_url.username or parsed_url.password:
        raise ValidationError({
            field_name: (
                "La URL no puede contener credenciales embebidas."
            )
        })

    hostname = hostname.rstrip(".").lower()

    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname in BLOCKED_METADATA_HOSTS
    ):
        raise ValidationError({
            field_name: (
                "La URL no puede apuntar a un recurso local."
            )
        })

    try:
        direct_ip = ipaddress.ip_address(hostname)
    except ValueError:
        direct_ip = None

    if direct_ip is not None:
        if not _is_public_ip_address(hostname):
            raise ValidationError({
                field_name: (
                    "La URL no puede apuntar a una dirección IP "
                    "privada, local o reservada."
                )
            })

        return

    if port is None:
        port = 443 if parsed_url.scheme.lower() == "https" else 80

    try:
        address_info = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, socket.herror, OSError):
        # Un fallo DNS representa indisponibilidad del enlace,
        # no necesariamente una URL insegura.
        # httpx registrará posteriormente el fallo de conexión.
        return

    resolved_addresses: set[str] = {
        cast(str, item[4][0])
        for item in address_info
    }

    for resolved_address in resolved_addresses:
        if not _is_public_ip_address(resolved_address):
            raise ValidationError({
                field_name: (
                    "La URL resuelve a una dirección de red "
                    "privada, local o reservada."
                )
            })


# Compatibilidad interna con el checker y sus pruebas existentes.
_validate_safe_http_url = validate_safe_http_url


def _get_next_fail_count(
    platform: models.Platform,
    *,
    url: str,
    is_active: bool,
    journal_platform=None,
) -> int:
    """
    Calcula la cantidad de fallos consecutivos para una URL específica.

    Una verificación exitosa reinicia el contador a cero.
    Si cambia la URL pública, la nueva URL inicia una secuencia independiente.
    """

    if is_active:
        return 0

    latest_log = (
        models.LinkCheckLog.objects
        .filter(
            platform=platform,
            journal_platform=journal_platform,
            url=url,
        )
        .order_by(*LINK_LOG_ORDERING)
        .first()
    )

    if (
        latest_log
        and latest_log.last_check is not None
        and not latest_log.is_active
    ):
        return latest_log.fail_count + 1

    return 1


def _perform_link_check(
    url: str,
) -> tuple[int | None, bool]:
    """
    Ejecuta la petición HTTP para comprobar la disponibilidad
    de un enlace.

    No sigue redirecciones automáticamente. Una respuesta 3xx
    ya demuestra que el servidor respondió y evita consultar
    destinos de redirección no validados.
    """

    try:
        with httpx.Client(
            timeout=LINK_CHECK_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            with client.stream(
                "GET",
                url,
                headers={
                    "User-Agent": "RABD-LinkChecker/1.0",
                },
            ) as response:
                status_code = response.status_code

        return (
            status_code,
            _is_successful_link_status(status_code),
        )

    except (
        httpx.HTTPError,
        Exception,
    ):
        return None, False


@transaction.atomic
def publish_platform(
    *,
    platform: models.Platform,
    user,
) -> models.Platform:
    """
    Publica una plataforma previamente validada.
    """

    platform = (
        models.Platform.all_objects
        .select_for_update()
        .get(pk=platform.pk)
    )

    validate_platform_for_publication(platform)

    now = timezone.now()

    platform.status = models.Platform.Status.PUBLICADO
    platform.validated_by = user
    platform.validated_at = now
    platform.updated_by = user
    platform.updated_at = now

    platform.save(
        update_fields=[
            "status",
            "validated_by",
            "validated_at",
            "updated_by",
            "updated_at",
        ]
    )

    return platform


@transaction.atomic
def mark_platform_obsolete(
    *,
    platform: models.Platform,
    user,
) -> models.Platform:
    """
    Marca como obsoleta una plataforma actualmente publicada.
    """

    platform = (
        models.Platform.all_objects
        .select_for_update()
        .get(pk=platform.pk)
    )

    validate_platform_for_obsolete(platform)

    now = timezone.now()

    platform.status = models.Platform.Status.OBSOLETO
    platform.finish_period = timezone.localdate()
    platform.updated_by = user
    platform.updated_at = now

    platform.save(
        update_fields=[
            "status",
            "finish_period",
            "updated_by",
            "updated_at",
        ]
    )

    return platform


@transaction.atomic
def reactivate_platform(
    *,
    platform: models.Platform,
    user,
) -> models.Platform:
    """
    Regresa una plataforma obsoleta a borrador para una nueva revisión.
    """

    platform = (
        models.Platform.all_objects
        .select_for_update()
        .get(pk=platform.pk)
    )

    validate_platform_for_reactivation(platform)

    now = timezone.now()

    platform.status = models.Platform.Status.BORRADOR
    platform.finish_period = None

    platform.validated_by = None
    platform.validated_at = None

    platform.updated_by = user
    platform.updated_at = now

    platform.save(
        update_fields=[
            "status",
            "finish_period",
            "validated_by",
            "validated_at",
            "updated_by",
            "updated_at",
        ]
    )

    return platform


def check_platform_link(
    *,
    platform: models.Platform,
    user,
    url: str | None = None,
) -> models.LinkCheckLog:
    """
    Verifica la disponibilidad de la URL pública de una plataforma
    y registra el resultado en LinkCheckLog.

    ``base_api_url`` representa la API utilizada para cosecha y no
    se utiliza como URL pública. Si no se suministra ``url``, se utiliza
    la URL del último registro del historial.
    """

    platform_snapshot = (
        models.Platform.all_objects
        .get(pk=platform.pk)
    )

    if platform_snapshot.is_deleted:
        raise ValidationError({
            "detail": (
                "No se puede verificar el enlace de "
                "una plataforma eliminada."
            )
        })

    if url is not None and str(url).strip():
        register_link_url(
            platform=platform_snapshot,
            url=str(url).strip(),
            user=user,
        )
    return check_link_context(platform=platform_snapshot, user=user)


def check_link_context(
    *,
    platform: models.Platform,
    user,
    journal_platform=None,
) -> models.LinkCheckLog:
    """Verifica la URL vigente de un contexto Platform o Journal-Platform."""
    if platform.is_deleted:
        raise ValidationError({"detail": "No se puede verificar una plataforma eliminada."})
    if journal_platform is None:
        latest_log = latest_platform_link_log(platform)
    else:
        if journal_platform.is_deleted or journal_platform.platform_id != platform.pk:
            raise ValidationError({"journal_platform": "La relación no está vigente."})
        latest_log = latest_journal_link_log(journal_platform)
    if latest_log is None:
        raise ValidationError({"url": "No existe una URL vigente para este contexto."})

    resolved_url = latest_log.url.strip()
    _validate_safe_http_url(resolved_url)
    status_code, is_active = _perform_link_check(resolved_url)
    with transaction.atomic():
        fail_count = _get_next_fail_count(
            platform,
            url=resolved_url,
            is_active=is_active,
            journal_platform=journal_platform,
        )
        return models.LinkCheckLog.objects.create(
            platform=platform,
            journal_platform=journal_platform,
            url=resolved_url,
            fail_count=fail_count,
            http_status_code=status_code,
            is_active=is_active,
            last_check=timezone.now(),
            created_by=user,
        )


def check_platform_links(*, platform: models.Platform, user) -> dict:
    """Verifica secuencialmente todas las URLs vigentes de una Platform."""
    if platform.is_deleted:
        raise ValidationError({"detail": "No se puede verificar una plataforma eliminada."})
    contexts = [("platform", None)]
    contexts.extend(
        ("journal", link)
        for link in platform.journal_links.filter(journal__deleted_at__isnull=True)
    )
    results = []
    for context_type, journal_platform in contexts:
        try:
            log = check_link_context(
                platform=platform,
                journal_platform=journal_platform,
                user=user,
            )
            result = {
                "type": context_type,
                "journal": getattr(journal_platform, "journal_id", None),
                "journal_platform": getattr(journal_platform, "pk", None),
                **models_to_link_result(log),
            }
        except Exception as exc:
            result = {
                "type": context_type,
                "journal": getattr(journal_platform, "journal_id", None),
                "journal_platform": getattr(journal_platform, "pk", None),
                "url": None,
                "is_active": False,
                "http_status_code": None,
                "last_check": None,
                "verification_status": "unverified",
                "error": str(exc),
            }
        results.append(result)
    return {
        "platform": platform.pk,
        "checked": len(results),
        "available": sum(item["is_active"] for item in results),
        "failed": sum(not item["is_active"] for item in results),
        "results": results,
    }


def check_all_current_links(*, user) -> None:
    """Verifica cada URL vigente sin envolver las peticiones en una transacción global."""
    platforms = models.Platform.objects.order_by("pk")
    for platform in platforms:
        contexts = [None]
        contexts.extend(
            platform.journal_links.filter(
                journal__deleted_at__isnull=True,
            ).select_related("journal")
        )
        for journal_platform in contexts:
            try:
                check_link_context(
                    platform=platform,
                    journal_platform=journal_platform,
                    user=user,
                )
            except Exception:
                # Cada contexto es independiente: una URL inválida o ausente no
                # impide comprobar las restantes.
                continue


def models_to_link_result(log: models.LinkCheckLog) -> dict:
    return {
        "url": log.url,
        "is_active": log.is_active,
        "http_status_code": log.http_status_code,
        "last_check": log.last_check,
        "verification_status": link_verification_status(log),
    }
