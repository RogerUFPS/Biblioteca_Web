import logging
import time
import calendar
import re
import xml.etree.ElementTree as ElementTree
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
import httpx

from apps.account.models import User
from apps.catalog.models import Country, Editorial, Language, MaterialType
from apps.journal.models import Journal, License, SharedJournalLicense
from apps.journal.services import create_journal
from apps.platforms.models import Platform
from . import models

logger = logging.getLogger(__name__)
OAI_NAMESPACE = "http://www.openarchives.org/OAI/2.0/"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
ISSN_PATTERN = re.compile(r"^\s*(\d{4})-?(\d{3}[\dXx])\s*$")


class RetryableHarvestError(RuntimeError):
    """A provider or network error that should be retried by Celery."""


def get_latest_cursor_for_platform(platform: Platform) -> str:
    """
    Obtiene el api_cursor más reciente de cosechas previas de la plataforma.
    Prioriza cosechas que ya hayan avanzado con un cursor real devuelto por la API (distinto de '*').
    Si no existe ninguna cosecha con cursor previo, retorna '*' para iniciar la paginación en OpenAlex.
    """
    latest = (
        models.Harvest.objects
        .filter(platform=platform)
        .exclude(api_cursor="")
        .exclude(api_cursor="*")
        .exclude(api_cursor__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if latest and latest.api_cursor:
        return latest.api_cursor
    return "*"


def _is_doaj_platform(platform: Platform) -> bool:
    base_url = (platform.base_api_url or "").lower()
    platform_name = (platform.name or "").lower()
    return "doaj" in platform_name or (
        "doaj.org" in base_url and urlsplit(base_url).path.rstrip("/").endswith("/oai")
    )


def get_latest_harvest_progress(platform: Platform) -> dict[str, Any]:
    """Return the provider-specific continuation data for a new scheduled Harvest."""
    if not _is_doaj_platform(platform):
        return {"api_cursor": get_latest_cursor_for_platform(platform)}

    latest = (
        models.Harvest.objects.filter(platform=platform)
        .order_by("-created_at")
        .first()
    )
    if latest is None:
        return {"api_cursor": "", "api_marker": 0, "api_page": ""}
    return {
        "api_cursor": latest.api_cursor,
        "api_marker": latest.api_marker,
        "api_page": latest.api_page,
    }


def _source_has_apc(item: dict[str, Any]) -> bool | None:
    data_found = False
    apc_usd = item.get("apc_usd")
    if apc_usd is not None:
        try:
            amount = float(apc_usd)
            data_found = True
            if amount > 0:
                return True
        except (TypeError, ValueError):
            logger.warning("Valor apc_usd inválido de OpenAlex: %r", apc_usd)

    prices = item.get("apc_prices")
    if isinstance(prices, list):
        for price in prices:
            if not isinstance(price, dict):
                continue
            raw_amount = price.get("price", price.get("amount"))
            if raw_amount is None:
                continue
            try:
                data_found = True
                if float(raw_amount) > 0:
                    return True
            except (TypeError, ValueError):
                logger.warning("Precio APC inválido de OpenAlex: %r", raw_amount)
    return False if data_found else None


class OpenAlexHarvester:
    """
    Recolector especializado para la API pública de OpenAlex (fuentes de tipo revista).

    Implementa:
    - Paginación por cursor con guardado progresivo.
    - Límites de registros y tiempo de ejecución.
    - Deduplicación por ISSN integrando create_journal.
    - Sincronización automática con la tabla intermedia SharedJournalPlatform.
    """

    DEFAULT_BASE_URL = "https://api.openalex.org"

    def __init__(
        self,
        harvest: models.Harvest,
        client: httpx.Client | None = None,
        batch_size: int = 50,
        user: Any = None,
    ):
        self.harvest = harvest
        self.batch_size = min(max(batch_size, 1), 100)
        self._custom_client = client
        self.user = user or harvest.created_by or User.all_objects.get(code=0)

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        headers = {
            "User-Agent": "UFPS-Harvester/1.0",
            "Accept": "application/json",
        }
        api_key = self.harvest.platform.get_api_key()
        if self.harvest.platform.encrypted_api_key and not api_key:
            raise RuntimeError(
                "La API key de la plataforma está configurada, pero no se pudo "
                "descifrar. Verifica que PLATFORM_ENCRYPTION_KEY o "
                "DJANGO_SECRET_KEY sea el mismo que se usó al guardarla."
            )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return httpx.Client(
            headers=headers,
            timeout=30.0,
        )

    def harvest_records(self) -> models.Harvest:
        """
        Ejecuta el ciclo de recolección para la cosecha configurada.
        """
        if not self.harvest.platform.is_harvestable:
            raise ValueError(
                f"La plataforma '{self.harvest.platform.name}' "
                "no está habilitada para cosecha (is_harvestable=false)."
            )

        with transaction.atomic():
            harvest = models.Harvest.objects.select_for_update().get(pk=self.harvest.pk)
            if harvest.state != models.Harvest.State.PENDING:
                return harvest
            harvest.state = models.Harvest.State.RUNNING
            if harvest.started_at is None:
                harvest.started_at = timezone.now()
            harvest.save(update_fields=["state", "started_at"])
        self.harvest = harvest
        platform = harvest.platform

        # Recuperar o establecer cursor
        cursor = harvest.api_cursor or get_latest_cursor_for_platform(platform)
        if not cursor or not cursor.strip():
            cursor = "*"
        harvest.api_cursor = cursor
        harvest.save(update_fields=["api_cursor"])

        start_time = time.monotonic()
        base_url = (platform.base_api_url or self.DEFAULT_BASE_URL).rstrip("/")
        sources_url = f"{base_url}/sources"

        client = self._get_client()
        should_close_client = self._custom_client is None

        try:
            while True:
                # Comprobar si fue pausada o cancelada externamente
                harvest.refresh_from_db()
                if harvest.state in [
                    models.Harvest.State.CANCELLED,
                    models.Harvest.State.PAUSING,
                    models.Harvest.State.PAUSED,
                ]:
                    logger.info("Cosecha #%s interrumpida con estado: %s", harvest.pk, harvest.state)
                    break

                # Comprobar límite de registros alcanzado
                total_processed = (
                    harvest.records_added
                    + harvest.records_updated
                    + harvest.records_failed
                )
                if harvest.max_quantity and total_processed >= harvest.max_quantity:
                    logger.info("Límite de cantidad alcanzado en cosecha #%s (%s)", harvest.pk, total_processed)
                    break

                # Comprobar límite de tiempo transcurrido
                elapsed_minutes = (
                    harvest.elapsed_seconds + time.monotonic() - start_time
                ) / 60.0
                if harvest.stop_after_minutes and elapsed_minutes >= harvest.stop_after_minutes:
                    logger.info("Límite de tiempo alcanzado en cosecha #%s (%.2f min)", harvest.pk, elapsed_minutes)
                    break

                # Calcular tamaño del lote restante si hay max_quantity
                page_size = self.batch_size
                if harvest.max_quantity:
                    remaining = harvest.max_quantity - total_processed
                    page_size = min(page_size, remaining)

                params = {
                    "filter": "type:journal",
                    "cursor": cursor,
                    "per-page": page_size,
                }

                response = client.get(sources_url, params=params)
                if response.status_code != 200:
                    raise RuntimeError(
                        f"OpenAlex API respondió con código {response.status_code}: {response.text[:200]}"
                    )

                data = response.json()
                meta = data.get("meta", {})
                next_cursor = meta.get("next_cursor")
                results = data.get("results", [])

                if not results:
                    logger.info("No se encontraron más resultados para la cosecha #%s.", harvest.pk)
                    break

                page_complete = True
                for item in results:
                    # Chequeo de límites dentro del lote
                    current_processed = (
                        harvest.records_added
                        + harvest.records_updated
                        + harvest.records_failed
                    )
                    if harvest.max_quantity and current_processed >= harvest.max_quantity:
                        page_complete = False
                        break
                    elapsed_batch = (
                        harvest.elapsed_seconds + time.monotonic() - start_time
                    ) / 60.0
                    if harvest.stop_after_minutes and elapsed_batch >= harvest.stop_after_minutes:
                        page_complete = False
                        break

                    self._process_single_source(item)

                # Actualizar cursor y métricas de progreso de forma progresiva e inalterable
                if page_complete and next_cursor:
                    cursor = next_cursor
                    harvest.api_cursor = next_cursor

                harvest.save(
                    update_fields=[
                        "api_cursor",
                        "records_added",
                        "records_updated",
                        "records_failed",
                    ]
                )

                if not page_complete:
                    break

                # Si no hay más páginas, finalizar
                if not next_cursor:
                    break

            # Finalización con éxito si no fue cancelada ni pausada.
            # Una pausa no cierra la cosecha: no se registra finished_at ni duration.
            harvest.refresh_from_db()
            elapsed_seconds = harvest.elapsed_seconds + int(time.monotonic() - start_time)
            if harvest.state == models.Harvest.State.PAUSING:
                harvest.state = models.Harvest.State.PAUSED
                harvest.elapsed_seconds = elapsed_seconds
                harvest.save(update_fields=["state", "elapsed_seconds"])
            if harvest.state == models.Harvest.State.PAUSED:
                harvest.elapsed_seconds = elapsed_seconds
                harvest.save(
                    update_fields=[
                        "api_cursor",
                        "records_added",
                        "records_updated",
                        "records_failed",
                        "elapsed_seconds",
                    ]
                )
            else:
                if harvest.state != models.Harvest.State.CANCELLED:
                    harvest.state = models.Harvest.State.COMPLETED
                harvest.finished_at = timezone.now()
                harvest.elapsed_seconds = elapsed_seconds
                harvest.save(
                    update_fields=[
                        "state",
                        "finished_at",
                        "api_cursor",
                        "records_added",
                        "records_updated",
                        "records_failed",
                        "elapsed_seconds",
                    ]
                )

        except Exception as exc:
            logger.exception("Error durante la ejecución de la cosecha #%s: %s", harvest.pk, exc)
            harvest.state = models.Harvest.State.FAILED
            harvest.error_message = str(exc)
            harvest.finished_at = timezone.now()
            harvest.elapsed_seconds += int(time.monotonic() - start_time)
            harvest.save(
                update_fields=[
                    "state",
                    "error_message",
                    "finished_at",
                    "api_cursor",
                    "records_added",
                    "records_updated",
                    "records_failed",
                    "elapsed_seconds",
                ]
            )
            raise
        finally:
            if should_close_client:
                client.close()

        return harvest

    def _process_single_source(self, item: dict[str, Any]) -> None:
        """
        Procesa una entrada de OpenAlex, extrae los datos de la revista y
        utiliza apps.journal.services.create_journal para insertar/actualizar
        garantizando deduplicación por ISSN.
        """
        harvest = self.harvest

        # Obtener ISSN preferencial (issn_l o primer ISSN de la lista)
        issn_l = item.get("issn_l")
        issn_list = item.get("issn") or []
        issn = issn_l or (issn_list[0] if issn_list else None)

        if not issn:
            harvest.records_failed += 1
            return

        title = item.get("display_name") or ""
        journal_url = item.get("homepage_url")
        url_image = item.get("image_url") or item.get("image_thumbnail_url")
        has_apc = _source_has_apc(item)
        has_full_text = item.get("is_oa")

        # Gestionar Editorial en el catálogo
        editorial_name = item.get("host_organization_name") or item.get("publisher")
        editorial_id = None
        if editorial_name and editorial_name.strip():
            clean_name = editorial_name.strip().lower()
            editorial, _ = Editorial.all_objects.get_or_create(
                name=clean_name,
                defaults={"created_by": self.user},
            )
            if editorial.is_deleted:
                editorial.restore()
            editorial_id = editorial.id

        # Gestionar País en el catálogo
        country_ids = None
        country_code = item.get("country_code")
        if country_code and country_code.strip():
            country = Country.objects.filter(abbreviation__iexact=country_code.strip()).first()
            if country:
                country_ids = [country.id]

        # Verificar si la revista ya existe para determinar si se agrega o actualiza
        compact_issn = "".join(issn.split()).replace("-", "").upper()
        formatted_issn = f"{compact_issn[:4]}-{compact_issn[4:]}" if len(compact_issn) == 8 else issn
        is_existing = Journal.all_objects.filter(issn__iexact=formatted_issn).exists()

        try:
            with transaction.atomic():
                journal = create_journal(
                    issn=issn,
                    title=title,
                    user=self.user,
                    platform_id=harvest.platform_id,
                    journal_url=journal_url,
                    editorial_id=editorial_id,
                    url_image=url_image,
                    has_apc=has_apc,
                    country_ids=country_ids,
                    has_full_text=has_full_text,
                )
                models.HarvestJournal.objects.create(
                    harvest=harvest,
                    journal=journal,
                    result=(
                        models.HarvestJournal.Result.UPDATED
                        if is_existing
                        else models.HarvestJournal.Result.ADDED
                    ),
                )
            if is_existing:
                harvest.records_updated += 1
            else:
                harvest.records_added += 1
        except Exception as exc:
            logger.warning("Fallo al crear o actualizar revista %s: %s", issn, exc)
            harvest.records_failed += 1


class DoajHarvester:
    """Harvest DOAJ's OAI-PMH Dublin Core records, preserving incomplete pages."""

    DEFAULT_OAI_URL = "https://doaj.org/oai"

    def __init__(
        self,
        harvest: models.Harvest,
        client: httpx.Client | None = None,
        user: Any = None,
    ):
        self.harvest = harvest
        self._custom_client = client
        self.user = user or harvest.created_by or User.all_objects.get(code=0)

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(
            headers={
                "User-Agent": "UFPS-Harvester/1.0",
                "Accept": "application/xml, text/xml",
            },
            timeout=60.0,
        )

    def _get_endpoint(self) -> str:
        configured_url = self.harvest.platform.base_api_url or self.DEFAULT_OAI_URL
        parsed_url = urlsplit(configured_url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise ValueError("La URL OAI-PMH configurada para DOAJ no es válida.")
        return urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", ""))

    @staticmethod
    def _records_and_token(xml_payload: str):
        try:
            root = ElementTree.fromstring(xml_payload)
        except ElementTree.ParseError as exc:
            raise RuntimeError(f"DOAJ devolvió XML inválido: {exc}") from exc

        if root.tag != f"{{{OAI_NAMESPACE}}}OAI-PMH":
            raise RuntimeError("DOAJ devolvió una respuesta que no es OAI-PMH.")

        error = root.find(f"{{{OAI_NAMESPACE}}}error")
        if error is not None:
            code = error.get("code", "unknown")
            detail = (error.text or "").strip()
            raise RuntimeError(f"Error OAI-PMH de DOAJ ({code}): {detail}")

        list_records = root.find(f"{{{OAI_NAMESPACE}}}ListRecords")
        if list_records is None:
            raise RuntimeError("La respuesta OAI-PMH de DOAJ no contiene ListRecords.")

        records = list_records.findall(f"{{{OAI_NAMESPACE}}}record")
        token_element = list_records.find(f"{{{OAI_NAMESPACE}}}resumptionToken")
        next_token = (token_element.text or "").strip() if token_element is not None else ""
        return records, next_token

    @staticmethod
    def _dc_values(record, field: str) -> list[str]:
        metadata = record.find(f"{{{OAI_NAMESPACE}}}metadata")
        if metadata is None:
            return []
        dc_tag = f"{{{DC_NAMESPACE}}}{field}"
        return [
            text
            for element in metadata.iter(dc_tag)
            if (text := (element.text or "").strip())
        ]

    @staticmethod
    def _record_issn(identifiers: list[str]) -> str | None:
        for identifier in identifiers:
            match = ISSN_PATTERN.fullmatch(identifier)
            if match:
                return f"{match.group(1)}-{match.group(2).upper()}"
        return None

    @staticmethod
    def _journal_url(relations: list[str], identifiers: list[str], issn: str) -> str:
        http_relations = [
            relation
            for relation in relations
            if urlsplit(relation).scheme in {"http", "https"}
            and urlsplit(relation).netloc
        ]
        preferred = [
            relation
            for relation in http_relations
            if not any(
                path_term in urlsplit(relation).path.lower()
                for path_term in ("about", "submissions", "contact", "editorialteam")
            )
        ]
        if preferred:
            return preferred[0]
        if http_relations:
            return http_relations[0]

        toc_url = next(
            (
                identifier
                for identifier in identifiers
                if identifier.startswith("https://doaj.org/toc/")
            ),
            None,
        )
        return toc_url or f"https://doaj.org/toc/{issn}"

    def _get_editorial_id(self, publisher: str | None) -> int | None:
        if not publisher:
            return None
        editorial, _ = Editorial.all_objects.get_or_create(
            name=publisher.lower(),
            defaults={"created_by": self.user},
        )
        if editorial.is_deleted:
            editorial.restore()
        return editorial.pk

    def _sync_licenses(self, journal: Journal, rights: list[str]) -> None:
        if not rights:
            return

        license_ids = set()
        for right in dict.fromkeys(rights):
            license_obj = License.all_objects.filter(name__iexact=right).first()
            if license_obj is None:
                license_obj = License.objects.create(
                    name=right,
                    created_by=self.user,
                )
            elif license_obj.is_deleted:
                license_obj.restore()
            license_ids.add(license_obj.pk)

        current_links = SharedJournalLicense.objects.filter(journal=journal)
        current_license_ids = set(current_links.values_list("license_id", flat=True))
        for link in current_links.exclude(license_id__in=license_ids):
            link.soft_delete(
                user=self.user,
                explanation="Licencia retirada del registro fuente DOAJ.",
            )

        for license_id in license_ids - current_license_ids:
            archived_link = SharedJournalLicense.all_objects.filter(
                journal=journal,
                license_id=license_id,
                deleted_at__isnull=False,
            ).first()
            if archived_link:
                archived_link.restore()
            else:
                SharedJournalLicense.objects.create(
                    journal=journal,
                    license_id=license_id,
                    created_by=self.user,
                )

    def _process_record(self, record) -> None:
        harvest = self.harvest
        header = record.find(f"{{{OAI_NAMESPACE}}}header")
        if header is None or header.get("status") == "deleted":
            harvest.records_failed += 1
            logger.warning("Registro DOAJ eliminado o sin encabezado; se omite.")
            return

        identifiers = self._dc_values(record, "identifier")
        issn = self._record_issn(identifiers)
        titles = self._dc_values(record, "title")
        title = titles[0] if titles else ""
        if not issn or not title:
            harvest.records_failed += 1
            logger.warning(
                "Registro DOAJ sin ISSN o título (identifier=%s).",
                header.findtext(f"{{{OAI_NAMESPACE}}}identifier"),
            )
            return

        languages = [
            language.pk
            for code in self._dc_values(record, "language")
            if (
                language := Language.objects.filter(
                    abbreviation__iexact=code,
                ).first()
            )
        ]
        material_type_ids = [
            material_type.pk
            for value in self._dc_values(record, "type")
            if (
                material_type := MaterialType.objects.filter(
                    name__iexact=value,
                ).first()
            )
        ]
        publisher_values = self._dc_values(record, "publisher")
        editorial_id = self._get_editorial_id(publisher_values[0] if publisher_values else None)
        journal_url = self._journal_url(
            self._dc_values(record, "relation"),
            identifiers,
            issn,
        )

        existing_journal = Journal.all_objects.filter(issn__iexact=issn).first()
        is_existing = existing_journal is not None
        try:
            with transaction.atomic():
                journal = create_journal(
                    issn=issn,
                    title=title,
                    user=self.user,
                    platform_id=harvest.platform_id,
                    journal_url=journal_url,
                    editorial_id=editorial_id,
                    language_ids=languages or None,
                    material_type_ids=material_type_ids or None,
                )
                self._sync_licenses(journal, self._dc_values(record, "rights"))
                models.HarvestJournal.objects.create(
                    harvest=harvest,
                    journal=journal,
                    result=(
                        models.HarvestJournal.Result.UPDATED
                        if is_existing
                        else models.HarvestJournal.Result.ADDED
                    ),
                )
            if is_existing:
                harvest.records_updated += 1
            else:
                harvest.records_added += 1
        except Exception as exc:
            logger.warning("Fallo al crear o actualizar revista DOAJ %s: %s", issn, exc)
            harvest.records_failed += 1

    def harvest_records(self) -> models.Harvest:
        if not self.harvest.platform.is_harvestable:
            raise ValueError(
                f"La plataforma '{self.harvest.platform.name}' "
                "no está habilitada para cosecha (is_harvestable=false)."
            )

        with transaction.atomic():
            harvest = models.Harvest.objects.select_for_update().get(pk=self.harvest.pk)
            if harvest.state != models.Harvest.State.PENDING:
                return harvest
            harvest.state = models.Harvest.State.RUNNING
            if harvest.started_at is None:
                harvest.started_at = timezone.now()
            harvest.save(update_fields=["state", "started_at"])
        self.harvest = harvest

        client = None
        should_close_client = self._custom_client is None
        start_time = time.monotonic()

        try:
            endpoint = self._get_endpoint()
            client = self._get_client()
            while True:
                harvest.refresh_from_db()
                if harvest.state in {
                    models.Harvest.State.CANCELLED,
                    models.Harvest.State.PAUSING,
                    models.Harvest.State.PAUSED,
                }:
                    break

                elapsed_minutes = (
                    harvest.elapsed_seconds + time.monotonic() - start_time
                ) / 60
                if (
                    harvest.stop_after_minutes
                    and elapsed_minutes >= harvest.stop_after_minutes
                ):
                    break

                if not harvest.api_page:
                    total_processed = (
                        harvest.records_added
                        + harvest.records_updated
                        + harvest.records_failed
                    )
                    if harvest.max_quantity and total_processed >= harvest.max_quantity:
                        break
                    params = (
                        {
                            "verb": "ListRecords",
                            "metadataPrefix": "oai_dc",
                        }
                        if not harvest.api_cursor
                        else {
                            "verb": "ListRecords",
                            "resumptionToken": harvest.api_cursor,
                        }
                    )
                    response = client.get(endpoint, params=params)
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"DOAJ respondió con código {response.status_code}: "
                            f"{response.text[:200]}"
                        )
                    harvest.api_page = response.text
                    harvest.api_marker = 0
                    harvest.save(update_fields=["api_page", "api_marker"])

                records, next_token = self._records_and_token(harvest.api_page)
                if harvest.api_marker > len(records):
                    raise RuntimeError(
                        "El marcador del Harvest supera el número de registros "
                        "de la respuesta DOAJ almacenada."
                    )

                while harvest.api_marker < len(records):
                    harvest.refresh_from_db()
                    if harvest.state in {
                        models.Harvest.State.CANCELLED,
                        models.Harvest.State.PAUSING,
                        models.Harvest.State.PAUSED,
                    }:
                        break

                    elapsed_minutes = (
                        harvest.elapsed_seconds + time.monotonic() - start_time
                    ) / 60
                    if (
                        harvest.stop_after_minutes
                        and elapsed_minutes >= harvest.stop_after_minutes
                    ):
                        break

                    with transaction.atomic():
                        self._process_record(records[harvest.api_marker])
                        harvest.api_marker += 1
                        harvest.save(
                            update_fields=[
                                "api_marker",
                                "records_added",
                                "records_updated",
                                "records_failed",
                            ]
                        )

                if harvest.api_marker < len(records):
                    break

                harvest.api_cursor = next_token
                harvest.api_marker = 0
                harvest.api_page = ""
                harvest.save(
                    update_fields=["api_cursor", "api_marker", "api_page"],
                )
                total_processed = (
                    harvest.records_added
                    + harvest.records_updated
                    + harvest.records_failed
                )
                if not next_token or (
                    harvest.max_quantity and total_processed >= harvest.max_quantity
                ):
                    break

            harvest.refresh_from_db()
            elapsed_seconds = harvest.elapsed_seconds + int(time.monotonic() - start_time)
            harvest.elapsed_seconds = elapsed_seconds
            if harvest.state == models.Harvest.State.PAUSING:
                harvest.state = models.Harvest.State.PAUSED
                harvest.save(update_fields=["state", "elapsed_seconds"])
            elif harvest.state != models.Harvest.State.PAUSED:
                if harvest.state != models.Harvest.State.CANCELLED:
                    harvest.state = models.Harvest.State.COMPLETED
                harvest.finished_at = timezone.now()
                harvest.save(
                    update_fields=[
                        "state",
                        "finished_at",
                        "elapsed_seconds",
                        "api_cursor",
                        "api_marker",
                        "api_page",
                        "records_added",
                        "records_updated",
                        "records_failed",
                    ]
                )
        except Exception as exc:
            logger.exception("Error durante la cosecha DOAJ #%s: %s", harvest.pk, exc)
            harvest.state = models.Harvest.State.FAILED
            harvest.error_message = str(exc)
            harvest.finished_at = timezone.now()
            harvest.elapsed_seconds += int(time.monotonic() - start_time)
            harvest.save(
                update_fields=[
                    "state",
                    "error_message",
                    "finished_at",
                    "elapsed_seconds",
                ]
            )
            raise
        finally:
            if client is not None and should_close_client:
                client.close()

        return harvest


def get_harvester_for_platform(
    harvest: models.Harvest,
    **kwargs,
) -> OpenAlexHarvester | DoajHarvester:
    """
    Factoría que selecciona el recolector adecuado según la plataforma.
    """
    if not harvest.platform.is_harvestable:
        raise ValueError(
            f"La plataforma '{harvest.platform.name}' "
            "no está habilitada para cosecha (is_harvestable=false)."
        )

    platform_name = (harvest.platform.name or "").lower()
    base_url = (harvest.platform.base_api_url or "").lower()

    if _is_doaj_platform(harvest.platform):
        return DoajHarvester(harvest, **kwargs)
    if "openalex" in platform_name or "openalex.org" in base_url:
        return OpenAlexHarvester(harvest, **kwargs)

    raise ValueError(
        f"No existe un motor de recolección configurado para la plataforma '{harvest.platform.name}'. "
        "Actualmente se encuentran implementados los proveedores OpenAlex y DOAJ."
    )


def execute_harvest(harvest_id: int, **kwargs) -> models.Harvest:
    """
    Ejecuta el proceso de cosecha para el ID suministrado.
    """
    harvest = models.Harvest.objects.get(pk=harvest_id)
    harvester = get_harvester_for_platform(harvest, **kwargs)
    return harvester.harvest_records()


def _worker_result(harvest: models.Harvest, *, stale: bool = False) -> dict[str, Any]:
    return {
        "harvest_id": harvest.pk,
        "checkpoint": harvest.worker_checkpoint,
        "state": harvest.state,
        "has_more": (
            harvest.state in {models.Harvest.State.PENDING, models.Harvest.State.RUNNING}
            and not stale
        ),
        "stale": stale,
    }


def _finish_schedule_event(harvest: models.Harvest) -> None:
    if not harvest.event_id:
        return
    event = models.ScheduleEvent.objects.select_for_update().get(pk=harvest.event_id)
    harvest_states = list(event.harvests.values_list("state", flat=True))
    terminal_states = {
        models.Harvest.State.COMPLETED,
        models.Harvest.State.FAILED,
        models.Harvest.State.CANCELLED,
    }
    if not harvest_states or any(state not in terminal_states for state in harvest_states):
        return
    event.state = (
        models.ScheduleEvent.State.FAILED
        if models.Harvest.State.FAILED in harvest_states
        else models.ScheduleEvent.State.COMPLETED
    )
    event.finished_at = timezone.now()
    errors = list(
        event.harvests.exclude(error_message__isnull=True)
        .exclude(error_message="")
        .values_list("error_message", flat=True)
    )
    event.error_message = "\n".join(errors) or None
    event.save(update_fields=["state", "finished_at", "error_message"])


def _worker_openalex_step(harvest: models.Harvest, user: User) -> None:
    harvester = OpenAlexHarvester(harvest, user=user, batch_size=1)
    client = harvester._get_client()
    try:
        base_url = (harvest.platform.base_api_url or harvester.DEFAULT_BASE_URL).rstrip("/")
        response = client.get(
            f"{base_url}/sources",
            params={
                "filter": "type:journal",
                "cursor": harvest.api_cursor or "*",
                "per-page": 1,
            },
        )
        if response.status_code != 200:
            error_type = (
                RetryableHarvestError
                if response.status_code == 429 or response.status_code >= 500
                else RuntimeError
            )
            raise error_type(
                f"OpenAlex API respondió con código {response.status_code}: "
                f"{response.text[:200]}"
            )
        data = response.json()
        results = data.get("results", [])
        if not results:
            harvest.state = models.Harvest.State.COMPLETED
            return
        harvester._process_single_source(results[0])
        harvest.api_cursor = data.get("meta", {}).get("next_cursor") or ""
        if not harvest.api_cursor:
            harvest.state = models.Harvest.State.COMPLETED
    finally:
        client.close()


def _worker_doaj_step(harvest: models.Harvest, user: User) -> None:
    harvester = DoajHarvester(harvest, user=user)
    endpoint = harvester._get_endpoint()
    client = harvester._get_client()
    try:
        if not harvest.api_page:
            total_processed = (
                harvest.records_added
                + harvest.records_updated
                + harvest.records_failed
            )
            if harvest.max_quantity and total_processed >= harvest.max_quantity:
                harvest.state = models.Harvest.State.COMPLETED
                return
            params = (
                {"verb": "ListRecords", "metadataPrefix": "oai_dc"}
                if not harvest.api_cursor
                else {"verb": "ListRecords", "resumptionToken": harvest.api_cursor}
            )
            response = client.get(endpoint, params=params)
            if response.status_code != 200:
                error_type = (
                    RetryableHarvestError
                    if response.status_code == 429 or response.status_code >= 500
                    else RuntimeError
                )
                raise error_type(
                    f"DOAJ respondió con código {response.status_code}: "
                    f"{response.text[:200]}"
                )
            harvest.api_page = response.text
            harvest.api_marker = 0

        records, next_token = harvester._records_and_token(harvest.api_page)
        if harvest.api_marker > len(records):
            raise RuntimeError(
                "El marcador del Harvest supera el número de registros "
                "de la respuesta DOAJ almacenada."
            )
        if harvest.api_marker < len(records):
            harvester._process_record(records[harvest.api_marker])
            harvest.api_marker += 1

        if harvest.api_marker >= len(records):
            harvest.api_cursor = next_token
            harvest.api_marker = 0
            harvest.api_page = ""
            total_processed = (
                harvest.records_added
                + harvest.records_updated
                + harvest.records_failed
            )
            if not next_token or (
                harvest.max_quantity and total_processed >= harvest.max_quantity
            ):
                harvest.state = models.Harvest.State.COMPLETED
    finally:
        client.close()


def process_harvest_worker_step(
    harvest_id: int,
    checkpoint: int,
) -> dict[str, Any]:
    """Process one provider record, committing the journal and checkpoint atomically."""
    with transaction.atomic():
        harvest = (
            models.Harvest.objects.select_for_update(of=("self",))
            .select_related("platform", "created_by", "event")
            .get(pk=harvest_id)
        )
        if checkpoint != harvest.worker_checkpoint:
            return _worker_result(harvest, stale=True)
        if harvest.state in {
            models.Harvest.State.COMPLETED,
            models.Harvest.State.FAILED,
            models.Harvest.State.CANCELLED,
            models.Harvest.State.PAUSED,
        }:
            return _worker_result(harvest)
        if harvest.state == models.Harvest.State.PAUSING:
            harvest.state = models.Harvest.State.PAUSED
            harvest.save(update_fields=["state"])
            return _worker_result(harvest)

        if not harvest.platform.is_harvestable:
            harvest.state = models.Harvest.State.FAILED
            harvest.error_message = (
                f"La plataforma '{harvest.platform.name}' "
                "no está habilitada para cosecha (is_harvestable=false)."
            )
            harvest.finished_at = timezone.now()
            harvest.save(update_fields=["state", "error_message", "finished_at"])
            _finish_schedule_event(harvest)
            return _worker_result(harvest)

        if harvest.state == models.Harvest.State.PENDING:
            harvest.state = models.Harvest.State.RUNNING
            harvest.started_at = harvest.started_at or timezone.now()

        elapsed_milliseconds = max(
            harvest.worker_elapsed_milliseconds,
            harvest.elapsed_seconds * 1000,
        )
        if (
            harvest.stop_after_minutes
            and elapsed_milliseconds >= harvest.stop_after_minutes * 60_000
        ):
            harvest.state = models.Harvest.State.COMPLETED
            harvest.finished_at = timezone.now()
            harvest.save(update_fields=["state", "started_at", "finished_at"])
            _finish_schedule_event(harvest)
            return _worker_result(harvest)

        total_processed = (
            harvest.records_added
            + harvest.records_updated
            + harvest.records_failed
        )
        if (
            harvest.max_quantity
            and total_processed >= harvest.max_quantity
            and not (_is_doaj_platform(harvest.platform) and harvest.api_page)
        ):
            harvest.state = models.Harvest.State.COMPLETED
            harvest.finished_at = timezone.now()
            harvest.save(update_fields=["state", "started_at", "finished_at"])
            _finish_schedule_event(harvest)
            return _worker_result(harvest)

        started = time.monotonic()
        try:
            user = harvest.created_by or User.all_objects.get(code=0)
            if _is_doaj_platform(harvest.platform):
                _worker_doaj_step(harvest, user)
            elif (
                "openalex" in (harvest.platform.name or "").lower()
                or "openalex.org" in (harvest.platform.base_api_url or "").lower()
            ):
                _worker_openalex_step(harvest, user)
            else:
                raise ValueError(
                    "No existe un motor de recolección configurado para la plataforma "
                    f"'{harvest.platform.name}'."
                )
        except (httpx.TransportError, RetryableHarvestError):
            logger.warning(
                "Error transitorio procesando Harvest #%s; se delega el reintento a Queue.",
                harvest.pk,
                exc_info=True,
            )
            raise
        except Exception as exc:
            logger.exception("Error durante el paso de Harvest #%s", harvest.pk)
            harvest.state = models.Harvest.State.FAILED
            harvest.error_message = str(exc)
            harvest.finished_at = timezone.now()
        finally:
            step_milliseconds = max(1, int((time.monotonic() - started) * 1000))
            harvest.worker_elapsed_milliseconds = elapsed_milliseconds + step_milliseconds
            harvest.elapsed_seconds = harvest.worker_elapsed_milliseconds // 1000
            harvest.worker_dispatched_at = timezone.now()
            if harvest.state in {
                models.Harvest.State.COMPLETED,
                models.Harvest.State.FAILED,
            }:
                harvest.finished_at = harvest.finished_at or timezone.now()
            else:
                harvest.worker_checkpoint += 1
            harvest.save(
                update_fields=[
                    "state",
                    "started_at",
                    "finished_at",
                    "error_message",
                    "api_cursor",
                    "api_marker",
                    "api_page",
                    "records_added",
                    "records_updated",
                    "records_failed",
                    "elapsed_seconds",
                    "worker_elapsed_milliseconds",
                    "worker_checkpoint",
                    "worker_dispatched_at",
                ]
            )
            if harvest.state in {
                models.Harvest.State.COMPLETED,
                models.Harvest.State.FAILED,
            }:
                _finish_schedule_event(harvest)

        return _worker_result(harvest)


def _next_occurrence(schedule: models.Schedule):
    occurrences = schedule.events.count()
    if occurrences == 0:
        return schedule.start_date

    if schedule.frequency == models.Schedule.Frequency.ONCE:
        return None
    if schedule.frequency == models.Schedule.Frequency.DAILY:
        return schedule.start_date + timedelta(days=occurrences)
    if schedule.frequency == models.Schedule.Frequency.WEEKLY:
        return schedule.start_date + timedelta(weeks=occurrences)
    if schedule.frequency == models.Schedule.Frequency.MONTHLY:
        month_index = schedule.start_date.year * 12 + schedule.start_date.month - 1 + occurrences
        year, month_index = divmod(month_index, 12)
        month = month_index + 1
        day = min(schedule.start_date.day, calendar.monthrange(year, month)[1])
        return schedule.start_date.replace(year=year, month=month, day=day)
    return None


def run_scheduled_harvests(now=None) -> list[models.Harvest]:
    """Create due Harvests and dispatch bounded work to Celery."""
    now = now or timezone.now()
    retry_before = now - timedelta(minutes=5)
    schedule_ids = models.Schedule.objects.filter(
        deleted_at__isnull=True,
        start_date__lte=now,
    ).values_list("pk", flat=True)

    for schedule_id in schedule_ids:
        with transaction.atomic():
            schedule = models.Schedule.objects.select_for_update().get(pk=schedule_id)
            if schedule.events.filter(state=models.ScheduleEvent.State.RUNNING).exists():
                continue
            scheduled_for = _next_occurrence(schedule)
            if scheduled_for is None or scheduled_for > now:
                continue
            event, created = models.ScheduleEvent.objects.get_or_create(
                schedule=schedule,
                scheduled_for=scheduled_for,
                defaults={"created_by": schedule.created_by},
            )
            if not created:
                continue
            event.state = models.ScheduleEvent.State.RUNNING
            event.started_at = now
            event.save(update_fields=["state", "started_at"])
            for platform in schedule.platforms.all():
                platform = Platform.objects.select_for_update().get(pk=platform.pk)
                active_harvest = models.Harvest.objects.filter(
                    platform=platform,
                    state__in=[
                        models.Harvest.State.PENDING,
                        models.Harvest.State.RUNNING,
                        models.Harvest.State.PAUSING,
                        models.Harvest.State.PAUSED,
                    ],
                ).first()
                harvest = models.Harvest.objects.create(
                    platform=platform,
                    schedule=schedule,
                    event=event,
                    **get_latest_harvest_progress(platform),
                    max_quantity=schedule.max_quantity,
                    stop_after_minutes=schedule.stop_after_minutes,
                    created_by=schedule.created_by,
                    state=(
                        models.Harvest.State.FAILED
                        if active_harvest or not platform.is_harvestable
                        else models.Harvest.State.PENDING
                    ),
                    finished_at=(
                        timezone.now()
                        if active_harvest or not platform.is_harvestable
                        else None
                    ),
                    error_message=(
                        f"La plataforma ya tiene una cosecha activa (#{active_harvest.pk})."
                        if active_harvest
                        else (
                            f"La plataforma '{platform.name}' no está habilitada "
                            "para cosecha (is_harvestable=false)."
                            if not platform.is_harvestable
                            else None
                        )
                    ),
                )
            first_harvest = schedule.harvests.filter(event=event).first()
            if first_harvest:
                _finish_schedule_event(first_harvest)
            else:
                event.state = models.ScheduleEvent.State.FAILED
                event.finished_at = timezone.now()
                event.error_message = "La programación no tiene plataformas asociadas."
                event.save(update_fields=["state", "finished_at", "error_message"])

    candidates = list(models.Harvest.objects.filter(
        state__in=[
            models.Harvest.State.PENDING,
            models.Harvest.State.RUNNING,
            models.Harvest.State.PAUSING,
        ],
        event__isnull=False,
    ).filter(
        Q(worker_dispatched_at__isnull=True)
        | Q(worker_dispatched_at__lt=retry_before)
    ).order_by("created_at"))
    dispatched = []
    for harvest in candidates:
        dispatch_harvest_to_worker(harvest)
        dispatched.append(harvest)
    return dispatched


def dispatch_harvest_to_worker(harvest: models.Harvest) -> models.Harvest:
    from .tasks import process_harvest_step

    process_harvest_step.apply_async(
        args=(harvest.pk, harvest.worker_checkpoint),
    )
    harvest.worker_dispatched_at = timezone.now()
    harvest.save(update_fields=["worker_dispatched_at"])
    return harvest
