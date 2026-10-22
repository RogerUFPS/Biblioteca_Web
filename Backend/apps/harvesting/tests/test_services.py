from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.utils import timezone
import httpx

from apps.account.models import User
from apps.catalog.models import Country, Language, MaterialType
from apps.harvesting.models import Harvest, HarvestJournal, Schedule, ScheduleEvent
from apps.harvesting.services import (
    DoajHarvester,
    OpenAlexHarvester,
    _next_occurrence,
    get_harvester_for_platform,
    get_latest_harvest_progress,
    process_harvest_worker_step,
    run_scheduled_harvests,
)
from apps.journal.models import (
    Journal,
    License,
    SharedJournalLicense,
    SharedJournalPlatform,
)
from apps.platforms.models import LinkCheckLog, Platform


class HarvestingServicesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
        )
        cls.platform = Platform.objects.create(
            name="OpenAlex Services Test",
            status=Platform.Status.PUBLICADO,
            base_api_url="https://api.openalex.org",
            is_harvestable=True,
            created_by=cls.user,
        )
        cls.doaj_platform = Platform.objects.create(
            name="DOAJ",
            status=Platform.Status.PUBLICADO,
            base_api_url="https://doaj.org/oai?verb=ListRecords&metadataPrefix=oai_dc",
            is_harvestable=True,
            created_by=cls.user,
        )

    def _doaj_response(self, records: str, token: str = "") -> MagicMock:
        token_xml = f"<resumptionToken>{token}</resumptionToken>"
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.text = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/" '
            'xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<ListRecords>{records}{token_xml}</ListRecords>"
            "</OAI-PMH>"
        )
        return response

    @staticmethod
    def _doaj_record(
        issn: str = "1982-0003",
        title: str = "Para Onde!?",
    ) -> str:
        return (
            "<record><header><identifier>oai:doaj.org/journal:example</identifier>"
            "</header><metadata><oai_dc:dc>"
            f"<dc:title>{title}</dc:title>"
            f"<dc:identifier>{issn}</dc:identifier>"
            f"<dc:identifier>https://doaj.org/toc/{issn}</dc:identifier>"
            "<dc:language>PT</dc:language><dc:language>ES</dc:language>"
            "<dc:rights>CC BY-NC-SA</dc:rights>"
            "<dc:publisher>Programa de Pós Graduação em Geografia</dc:publisher>"
            "<dc:relation>https://journal.example.edu/index</dc:relation>"
            "<dc:relation>https://journal.example.edu/about</dc:relation>"
            "<dc:date>2026-09-18T19:30:23Z</dc:date>"
            "<dc:type>journal</dc:type>"
            "<dc:subject>geography</dc:subject>"
            "</oai_dc:dc></metadata></record>"
        )

    def test_doaj_factory_uses_oai_pmh_harvester(self):
        harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            stop_after_minutes=10,
            created_by=self.user,
        )
        self.assertIsInstance(get_harvester_for_platform(harvest), DoajHarvester)

    def test_doaj_harvester_normalizes_dublin_core_record(self):
        Language.objects.create(
            abbreviation="PT",
            name="Portuguese",
            created_by=self.user,
        )
        Language.objects.create(
            abbreviation="ES",
            name="Spanish",
            created_by=self.user,
        )
        MaterialType.objects.create(name="journal", created_by=self.user)
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = self._doaj_response(
            self._doaj_record(),
            token="next-page-token",
        )
        harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            max_quantity=1,
            created_by=self.user,
        )

        result = DoajHarvester(
            harvest,
            client=client,
            user=self.user,
        ).harvest_records()

        journal = Journal.objects.get(issn="1982-0003")
        self.assertEqual(result.state, Harvest.State.COMPLETED)
        self.assertEqual(result.records_added, 1)
        self.assertEqual(result.api_cursor, "next-page-token")
        self.assertEqual(result.api_marker, 0)
        self.assertEqual(result.api_page, "")
        self.assertEqual(journal.title, "Para Onde!?")
        self.assertEqual(journal.editorial.name, "programa de pós graduação em geografia")
        self.assertIsNone(journal.publication_date)
        self.assertEqual(
            set(journal.language_links.values_list("language__abbreviation", flat=True)),
            {"PT", "ES"},
        )
        self.assertTrue(journal.material_type_links.filter(material_type__name="journal").exists())
        self.assertTrue(
            SharedJournalLicense.objects.filter(
                journal=journal,
                license__name="cc by-nc-sa",
            ).exists()
        )
        self.assertEqual(
            client.get.call_args.args[0],
            "https://doaj.org/oai",
        )
        self.assertEqual(
            client.get.call_args.kwargs["params"],
            {"verb": "ListRecords", "metadataPrefix": "oai_dc"},
        )
        self.assertEqual(
            get_latest_harvest_progress(self.doaj_platform)["api_cursor"],
            "next-page-token",
        )

    def test_doaj_harvester_resumes_cached_response_at_marker(self):
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = self._doaj_response(
            self._doaj_record() + self._doaj_record("2532-1994", "Novecento"),
            token="page-two-token",
        )
        harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            max_quantity=10,
            stop_after_minutes=1,
            created_by=self.user,
        )
        clock = iter([0, 0, 0, 60, 60])
        with patch("apps.harvesting.services.time.monotonic", side_effect=lambda: next(clock)):
            DoajHarvester(
                harvest,
                client=client,
                user=self.user,
            ).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.COMPLETED)
        self.assertEqual(harvest.records_added, 1)
        self.assertEqual(harvest.api_marker, 1)
        self.assertTrue(harvest.api_page)
        self.assertEqual(client.get.call_count, 1)
        progress = get_latest_harvest_progress(self.doaj_platform)
        self.assertEqual(progress["api_cursor"], "")
        self.assertEqual(progress["api_marker"], 1)
        self.assertEqual(progress["api_page"], harvest.api_page)

        next_harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            max_quantity=1,
            api_cursor=progress["api_cursor"],
            api_marker=progress["api_marker"],
            api_page=progress["api_page"],
            created_by=self.user,
        )
        resumed_client = MagicMock(spec=httpx.Client)
        resumed = DoajHarvester(
            next_harvest,
            client=resumed_client,
            user=self.user,
        ).harvest_records()
        self.assertEqual(resumed.records_added, 1)
        self.assertEqual(resumed.api_cursor, "page-two-token")
        self.assertEqual(resumed.api_marker, 0)
        self.assertEqual(resumed.api_page, "")
        resumed_client.get.assert_not_called()
        self.assertTrue(Journal.objects.filter(issn="2532-1994").exists())

    @patch("apps.harvesting.services.DoajHarvester._get_client")
    def test_worker_step_is_checkpointed_and_duplicate_messages_are_ignored(
        self,
        get_client,
    ):
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = self._doaj_response(
            self._doaj_record() + self._doaj_record("2532-1994", "Novecento"),
            token="next-page-token",
        )
        get_client.return_value = client
        harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            max_quantity=2,
            created_by=self.user,
        )

        first = process_harvest_worker_step(harvest.pk, checkpoint=0)
        duplicate = process_harvest_worker_step(harvest.pk, checkpoint=0)
        second = process_harvest_worker_step(harvest.pk, checkpoint=1)

        harvest.refresh_from_db()
        self.assertEqual(first["checkpoint"], 1)
        self.assertTrue(first["has_more"])
        self.assertTrue(duplicate["stale"])
        self.assertFalse(duplicate["has_more"])
        self.assertEqual(second["state"], Harvest.State.COMPLETED)
        self.assertEqual(harvest.api_cursor, "next-page-token")
        self.assertEqual(harvest.records_added, 2)
        self.assertEqual(harvest.worker_checkpoint, 1)
        self.assertEqual(Journal.objects.count(), 2)

    @patch("apps.harvesting.services.DoajHarvester._get_client")
    def test_worker_retries_provider_timeout_without_advancing_checkpoint(
        self,
        get_client,
    ):
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.TimeoutException("provider timed out")
        get_client.return_value = client
        harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            stop_after_minutes=10,
            created_by=self.user,
        )

        with self.assertRaises(httpx.TimeoutException):
            process_harvest_worker_step(harvest.pk, checkpoint=0)

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.PENDING)
        self.assertEqual(harvest.worker_checkpoint, 0)
        self.assertEqual(harvest.api_marker, 0)
        self.assertEqual(harvest.api_page, "")
        client.close.assert_called_once()

    def test_doaj_finishes_page_before_quantity_limit_and_uses_resumption_token(self):
        first_client = MagicMock(spec=httpx.Client)
        first_client.get.return_value = self._doaj_response(
            self._doaj_record() + self._doaj_record("2532-1994", "Novecento"),
            token="page-two-token",
        )
        first_harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            max_quantity=1,
            created_by=self.user,
        )

        first_result = DoajHarvester(
            first_harvest,
            client=first_client,
            user=self.user,
        ).harvest_records()

        self.assertEqual(first_result.records_added, 2)
        self.assertEqual(first_result.api_cursor, "page-two-token")
        self.assertEqual(first_result.state, Harvest.State.COMPLETED)

        second_client = MagicMock(spec=httpx.Client)
        second_client.get.return_value = self._doaj_response(
            self._doaj_record("2050-0000", "Third journal"),
        )
        second_harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            max_quantity=1,
            created_by=self.user,
            **get_latest_harvest_progress(self.doaj_platform),
        )

        DoajHarvester(
            second_harvest,
            client=second_client,
            user=self.user,
        ).harvest_records()

        self.assertEqual(
            second_client.get.call_args.kwargs["params"],
            {"verb": "ListRecords", "resumptionToken": "page-two-token"},
        )

    def test_doaj_oai_error_is_reported_as_failed_harvest(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.text = (
            '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
            '<error code="badArgument">Invalid request</error></OAI-PMH>'
        )
        client.get.return_value = response
        harvest = Harvest.objects.create(
            platform=self.doaj_platform,
            stop_after_minutes=10,
            created_by=self.user,
        )

        with self.assertRaisesRegex(RuntimeError, "badArgument"):
            DoajHarvester(harvest, client=client, user=self.user).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.FAILED)
        self.assertIn("badArgument", harvest.error_message)

    def test_doaj_invalid_endpoint_marks_harvest_as_failed(self):
        platform = Platform.objects.create(
            name="DOAJ Invalid URL",
            status=Platform.Status.PUBLICADO,
            base_api_url="not-a-url",
            is_harvestable=True,
            created_by=self.user,
        )
        harvest = Harvest.objects.create(
            platform=platform,
            stop_after_minutes=10,
            created_by=self.user,
        )

        with self.assertRaisesRegex(ValueError, "no es válida"):
            DoajHarvester(harvest, user=self.user).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.FAILED)

    def test_default_openalex_client_does_not_advertise_email(self):
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=10,
            created_by=self.user,
        )
        client = OpenAlexHarvester(harvest=harvest, user=self.user)._get_client()
        try:
            self.assertEqual(
                client.headers["User-Agent"],
                "UFPS-Harvester/1.0",
            )
            self.assertNotIn("mailto:", client.headers["User-Agent"])
            self.assertEqual(client.headers["Accept"], "application/json")
        finally:
            client.close()

    def test_openalex_client_sends_platform_api_key_as_bearer_token(self):
        self.platform.set_api_key("openalex-test-key")
        self.platform.save(update_fields=["encrypted_api_key"])
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=10,
            created_by=self.user,
        )

        client = OpenAlexHarvester(harvest=harvest, user=self.user)._get_client()
        try:
            self.assertEqual(
                client.headers["Authorization"],
                "Bearer openalex-test-key",
            )
        finally:
            client.close()

    def test_openalex_client_rejects_api_key_that_cannot_be_decrypted(self):
        self.platform.encrypted_api_key = "encrypted-api-key"
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=10,
            created_by=self.user,
        )

        with patch.object(Platform, "get_api_key", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "no se pudo descifrar"):
                OpenAlexHarvester(
                    harvest=harvest,
                    user=self.user,
                )._get_client()

    def test_openalex_harvester_creates_and_deduplicates_journals(self):
        # Simular respuestas de OpenAlex
        mock_response_1 = MagicMock(spec=httpx.Response)
        mock_response_1.status_code = 200
        mock_response_1.json.return_value = {
            "meta": {"next_cursor": "cursor_page_2"},
            "results": [
                {
                    "id": "https://openalex.org/S1",
                    "display_name": "Revista Uno",
                    "issn_l": "1111-1111",
                    "issn": ["1111-1111"],
                    "homepage_url": "https://8.8.8.8/revista-uno",
                    "host_organization_name": "Editorial Uno",
                    "is_oa": True,
                },
                {
                    "id": "https://openalex.org/S2",
                    "display_name": "Revista Dos",
                    "issn_l": "2222-2222",
                    "issn": ["2222-2222"],
                    "homepage_url": "https://8.8.8.8/revista-dos",
                    "is_oa": False,
                },
            ],
        }

        mock_response_2 = MagicMock(spec=httpx.Response)
        mock_response_2.status_code = 200
        mock_response_2.json.return_value = {
            "meta": {"next_cursor": None},
            "results": [],
        }

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = [mock_response_1, mock_response_2]
        country = Country.objects.create(
            name="United States",
            abbreviation="US",
            emoji_flag="🇺🇸",
            created_by=self.user,
        )
        mock_response_1.json.return_value["results"][0].update({
            "country_code": "US",
            "image_thumbnail_url": "https://example.test/journal.png",
            "is_active": True,
            "apc_usd": 1400,
            "license": "CC-BY",
        })

        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=10,
            created_by=self.user,
        )

        harvester = OpenAlexHarvester(
            harvest=harvest,
            client=mock_client,
            user=self.user,
        )
        harvester.harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.COMPLETED)
        self.assertEqual(harvest.records_added, 2)
        self.assertEqual(harvest.records_updated, 0)
        self.assertEqual(harvest.api_cursor, "cursor_page_2")
        self.assertEqual(mock_client.get.call_args_list[0].kwargs["params"]["cursor"], "*")

        # Verificar que se crearon los Journals y los vínculos SharedJournalPlatform
        j1 = Journal.objects.get(issn="1111-1111")
        self.assertEqual(j1.title, "Revista Uno")
        self.assertEqual(j1.url_image, "https://example.test/journal.png")
        self.assertFalse(j1.active)
        self.assertTrue(j1.has_apc)
        journal_platform = SharedJournalPlatform.objects.get(
            journal=j1,
            platform=self.platform,
        )
        self.assertEqual(
            LinkCheckLog.objects.get(journal_platform=journal_platform).url,
            "https://8.8.8.8/revista-uno",
        )
        self.assertFalse(j1.license_links.exists())
        self.assertTrue(j1.country_links.filter(country=country).exists())
        self.assertTrue(journal_platform)
        self.assertTrue(
            HarvestJournal.objects.filter(
                harvest=harvest,
                journal=j1,
                result=HarvestJournal.Result.ADDED,
            ).exists()
        )

        # Probar deduplicación: Segunda cosecha con los mismos datos
        mock_response_dup = MagicMock(spec=httpx.Response)
        mock_response_dup.status_code = 200
        mock_response_dup.json.return_value = {
            "meta": {"next_cursor": None},
            "results": [
                {
                    "id": "https://openalex.org/S1",
                    "display_name": "Revista Uno Actualizada",
                    "issn_l": "1111-1111",
                    "homepage_url": "https://8.8.8.8/revista-uno-actualizada",
                    "is_oa": True,
                }
            ],
        }
        mock_client_dup = MagicMock(spec=httpx.Client)
        mock_client_dup.get.return_value = mock_response_dup

        harvest_2 = Harvest.objects.create(
            platform=self.platform,
            max_quantity=10,
            created_by=self.user,
        )

        harvester_2 = OpenAlexHarvester(
            harvest=harvest_2,
            client=mock_client_dup,
            user=self.user,
        )
        harvester_2.harvest_records()

        harvest_2.refresh_from_db()
        self.assertEqual(harvest_2.records_added, 0)
        self.assertEqual(harvest_2.records_updated, 1)
        self.assertEqual(harvest_2.api_cursor, "cursor_page_2")
        self.assertTrue(
            HarvestJournal.objects.filter(
                harvest=harvest_2,
                journal=j1,
                result=HarvestJournal.Result.UPDATED,
            ).exists()
        )

        # No se duplicó el registro en la BD
        self.assertEqual(Journal.objects.filter(issn="1111-1111").count(), 1)
        j1.refresh_from_db()
        self.assertEqual(j1.title, "Revista Uno Actualizada")
        self.assertFalse(j1.active)
        self.assertTrue(j1.has_apc)

    def test_harvest_records_runtime_timestamps(self):
        scheduled_for = timezone.now() - timedelta(minutes=1)
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.DAILY,
            max_quantity=10,
            start_date=scheduled_for,
            created_by=self.user,
        )
        schedule.platforms.add(self.platform)
        event = ScheduleEvent.objects.create(
            schedule=schedule,
            scheduled_for=scheduled_for,
            created_by=self.user,
        )
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "meta": {"next_cursor": None},
            "results": [
                {
                    "id": "https://openalex.org/S1",
                    "display_name": "Revista Timing",
                    "issn_l": "3333-3333",
                    "issn": ["3333-3333"],
                    "homepage_url": "https://8.8.8.8/revista-timing",
                }
            ],
        }
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = mock_response

        harvest = Harvest.objects.create(
            platform=self.platform,
            schedule=schedule,
            event=event,
            max_quantity=10,
            created_by=self.user,
        )
        OpenAlexHarvester(
            harvest=harvest,
            client=mock_client,
            user=self.user,
        ).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.COMPLETED)
        self.assertIsNotNone(harvest.started_at)
        self.assertIsNotNone(harvest.finished_at)

    @patch("apps.harvesting.services.dispatch_harvest_to_worker")
    def test_scheduled_event_creates_and_dispatches_one_harvest_per_platform(
        self,
        dispatch_harvest,
    ):
        second_platform = Platform.objects.create(
            name="Second Harvest Platform",
            status=Platform.Status.PUBLICADO,
            base_api_url="https://api.openalex.org",
            is_harvestable=True,
            created_by=self.user,
        )
        now = timezone.now()
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.DAILY,
            max_quantity=10,
            start_date=now - timedelta(days=2),
            created_by=self.user,
        )
        schedule.platforms.add(self.platform, second_platform)

        first_harvests = run_scheduled_harvests(now=now)
        self.assertEqual(len(first_harvests), 2)
        event = ScheduleEvent.objects.get(schedule=schedule)
        self.assertEqual(event.state, ScheduleEvent.State.RUNNING)
        self.assertEqual(event.harvests.count(), 2)
        self.assertEqual(dispatch_harvest.call_count, 2)
        self.assertTrue(
            all(harvest.state == Harvest.State.PENDING for harvest in first_harvests)
        )

        Harvest.objects.filter(event=event).update(state=Harvest.State.COMPLETED)
        event.state = ScheduleEvent.State.COMPLETED
        event.finished_at = timezone.now()
        event.save(update_fields=["state", "finished_at"])

        next_harvests = run_scheduled_harvests(now=now + timedelta(days=1))
        self.assertEqual(len(next_harvests), 2)
        self.assertEqual(schedule.events.count(), 2)
        self.assertEqual(dispatch_harvest.call_count, 4)

    @patch("apps.harvesting.services.dispatch_harvest_to_worker")
    def test_scheduled_harvest_fails_if_platform_was_disabled(self, dispatch_harvest):
        self.platform.is_harvestable = False
        self.platform.save(update_fields=["is_harvestable"])
        now = timezone.now()
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.ONCE,
            max_quantity=10,
            start_date=now - timedelta(minutes=1),
            created_by=self.user,
        )
        schedule.platforms.add(self.platform)

        harvests = run_scheduled_harvests(now=now)

        self.assertEqual(harvests, [])
        failed_harvest = Harvest.objects.get(event__schedule=schedule)
        self.assertEqual(failed_harvest.state, Harvest.State.FAILED)
        self.assertIn("no está habilitada para cosecha", failed_harvest.error_message)
        dispatch_harvest.assert_not_called()
        self.assertEqual(schedule.events.get().state, ScheduleEvent.State.FAILED)

    @patch("apps.harvesting.services.dispatch_harvest_to_worker")
    def test_repeated_scheduler_call_does_not_create_duplicate_event_or_harvest(
        self,
        dispatch_harvest,
    ):
        now = timezone.now()
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.ONCE,
            max_quantity=10,
            start_date=now - timedelta(minutes=1),
            created_by=self.user,
        )
        schedule.platforms.add(self.platform)

        first = run_scheduled_harvests(now=now)
        Harvest.objects.filter(pk=first[0].pk).update(
            worker_dispatched_at=now,
        )
        second = run_scheduled_harvests(now=now + timedelta(seconds=30))

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(schedule.events.count(), 1)
        self.assertEqual(Harvest.objects.filter(schedule=schedule).count(), 1)
        dispatch_harvest.assert_called_once()

    def test_non_harvestable_platform_has_no_harvester(self):
        self.platform.is_harvestable = False
        self.platform.save(update_fields=["is_harvestable"])
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=10,
            created_by=self.user,
        )

        with self.assertRaisesMessage(ValueError, "is_harvestable=false"):
            get_harvester_for_platform(harvest)

        with self.assertRaisesMessage(ValueError, "is_harvestable=false"):
            OpenAlexHarvester(harvest, user=self.user).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.PENDING)

    def test_max_quantity_counts_failed_records_too(self):
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {
            "meta": {"next_cursor": "cursor_page_2"},
            "results": [
                {"display_name": "No ISSN"},
                {
                    "display_name": "Should not be processed",
                    "issn_l": "4444-4444",
                },
            ],
        }
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = response
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=1,
            created_by=self.user,
        )

        OpenAlexHarvester(
            harvest=harvest,
            client=client,
            user=self.user,
        ).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.records_failed, 1)
        self.assertEqual(harvest.records_added, 0)
        self.assertEqual(harvest.api_cursor, "*")
        self.assertEqual(client.get.call_count, 1)

    def test_openalex_source_without_homepage_url_is_counted_as_failed(self):
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {
            "meta": {"next_cursor": None},
            "results": [
                {
                    "display_name": "Journal without homepage",
                    "issn_l": "7777-7777",
                }
            ],
        }
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = response
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=10,
            created_by=self.user,
        )

        OpenAlexHarvester(
            harvest=harvest,
            client=client,
            user=self.user,
        ).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.COMPLETED)
        self.assertEqual(harvest.records_added, 0)
        self.assertEqual(harvest.records_failed, 1)
        self.assertFalse(Journal.objects.filter(issn="7777-7777").exists())

    def test_pause_finishes_current_page_and_resume_uses_saved_cursor(self):
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {
            "meta": {"next_cursor": "resume-cursor"},
            "results": [
                {
                    "display_name": "Pause-safe journal",
                    "issn_l": "5555-5555",
                    "homepage_url": "https://8.8.8.8/pause-safe",
                }
            ],
        }
        client = MagicMock(spec=httpx.Client)

        def pause_during_request(*args, **kwargs):
            Harvest.objects.filter(pk=harvest.pk).update(
                state=Harvest.State.PAUSING,
            )
            return response

        client.get.side_effect = pause_during_request
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=10,
            created_by=self.user,
        )

        OpenAlexHarvester(
            harvest=harvest,
            client=client,
            user=self.user,
        ).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.PAUSED)
        self.assertEqual(harvest.api_cursor, "resume-cursor")
        self.assertEqual(harvest.records_added, 1)
        self.assertIsNone(harvest.finished_at)

        Harvest.objects.filter(pk=harvest.pk).update(state=Harvest.State.PENDING)
        resumed_response = MagicMock(spec=httpx.Response)
        resumed_response.status_code = 200
        resumed_response.json.return_value = {
            "meta": {"next_cursor": None},
            "results": [],
        }
        resumed_client = MagicMock(spec=httpx.Client)
        resumed_client.get.return_value = resumed_response
        OpenAlexHarvester(
            harvest=Harvest.objects.get(pk=harvest.pk),
            client=resumed_client,
            user=self.user,
        ).harvest_records()

        self.assertEqual(
            resumed_client.get.call_args.kwargs["params"]["cursor"],
            "resume-cursor",
        )

    def test_resumed_harvest_keeps_elapsed_time_limit(self):
        client = MagicMock(spec=httpx.Client)
        harvest = Harvest.objects.create(
            platform=self.platform,
            stop_after_minutes=1,
            elapsed_seconds=60,
            created_by=self.user,
        )
        OpenAlexHarvester(
            harvest=harvest,
            client=client,
            user=self.user,
        ).harvest_records()

        harvest.refresh_from_db()
        self.assertEqual(harvest.state, Harvest.State.COMPLETED)
        self.assertGreaterEqual(harvest.elapsed_seconds, 60)
        client.get.assert_not_called()

    def test_monthly_schedule_keeps_anchor_day_after_short_month(self):
        start_date = timezone.make_aware(datetime(2024, 1, 31, 9, 0))
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.MONTHLY,
            max_quantity=10,
            start_date=start_date,
            created_by=self.user,
        )
        ScheduleEvent.objects.create(
            schedule=schedule,
            scheduled_for=start_date,
            created_by=self.user,
        )
        february = _next_occurrence(schedule)
        self.assertEqual(february, timezone.make_aware(datetime(2024, 2, 29, 9, 0)))

        ScheduleEvent.objects.create(
            schedule=schedule,
            scheduled_for=february,
            created_by=self.user,
        )
        march = _next_occurrence(schedule)
        self.assertEqual(march, timezone.make_aware(datetime(2024, 3, 31, 9, 0)))
