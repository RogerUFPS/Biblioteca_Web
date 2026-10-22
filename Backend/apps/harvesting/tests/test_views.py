from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch

from apps.account.models import User
from apps.harvesting.models import Harvest, HarvestJournal, Schedule, ScheduleEvent
from apps.journal.models import Journal
from apps.platforms.models import Platform


class HarvestingViewsTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
            is_superadmin=True,
        )
        cls.platform = Platform.objects.create(
            name="OpenAlex Test",
            base_api_url="https://api.openalex.org",
            is_harvestable=True,
            created_by=cls.user,
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_schedule_crud_operations(self):
        payload = {
            "platforms": [self.platform.pk],
            "frequency": "weekly",
            "max_quantity": 250,
            "start_date": timezone.now().isoformat(),
        }
        response = self.client.post("/api/harvesting/schedules/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        schedule_id = response.data["id"]
        self.assertEqual(response.data["platforms"], [self.platform.pk])
        self.assertEqual(response.data["platform_names"], [self.platform.name])

        response = self.client.get(f"/api/harvesting/schedules/{schedule_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["frequency"], "weekly")

        response = self.client.patch(
            f"/api/harvesting/schedules/{schedule_id}/",
            {"frequency": "monthly"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["frequency"], "monthly")

    def test_schedule_requires_initial_datetime(self):
        response = self.client.post(
            "/api/harvesting/schedules/",
            {
                "platforms": [self.platform.pk],
                "frequency": "daily",
                "max_quantity": 10,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_date", response.data)

    def test_schedule_rejects_non_harvestable_platform(self):
        self.platform.is_harvestable = False
        self.platform.save(update_fields=["is_harvestable"])

        response = self.client.post(
            "/api/harvesting/schedules/",
            {
                "platforms": [self.platform.pk],
                "frequency": "daily",
                "max_quantity": 10,
                "start_date": timezone.now().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("platforms", response.data)
        self.assertIn(self.platform.name, str(response.data["platforms"]))
        self.assertEqual(Schedule.objects.count(), 0)

    @patch("apps.harvesting.views.services.run_scheduled_harvests", return_value=[])
    def test_run_due_executes_scheduled_harvests_without_token(self, run_scheduled):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/harvesting/schedules/run-due/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        run_scheduled.assert_called_once_with()

    def test_harvest_and_event_endpoints_are_read_only(self):
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.ONCE,
            max_quantity=100,
            start_date=timezone.now(),
            created_by=self.user,
        )
        schedule.platforms.add(self.platform)
        event = ScheduleEvent.objects.create(
            schedule=schedule,
            scheduled_for=timezone.now(),
            created_by=self.user,
        )
        harvest = Harvest.objects.create(
            platform=self.platform,
            schedule=schedule,
            event=event,
            max_quantity=100,
            created_by=self.user,
        )

        response = self.client.post(
            "/api/harvesting/harvests/",
            {"platform": self.platform.pk, "max_quantity": 100},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        response = self.client.get(f"/api/harvesting/harvests/{harvest.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event"], event.pk)

        response = self.client.post(
            f"/api/harvesting/harvests/{harvest.pk}/execute/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.post(
            f"/api/harvesting/events/{event.pk}/",
            {"state": "completed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_harvest_journals_returns_only_journals_added_by_that_harvest(self):
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=100,
            created_by=self.user,
        )
        added_journal = Journal.objects.create(
            issn="1234-5678",
            title="Revista nueva de cosecha",
            created_by=self.user,
        )
        updated_journal = Journal.objects.create(
            issn="2345-6789",
            title="Revista actualizada",
            created_by=self.user,
        )
        other_harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=100,
            state=Harvest.State.COMPLETED,
            created_by=self.user,
        )
        other_journal = Journal.objects.create(
            issn="3456-7890",
            title="Revista de otra cosecha",
            created_by=self.user,
        )
        HarvestJournal.objects.create(
            harvest=harvest,
            journal=added_journal,
            result=HarvestJournal.Result.ADDED,
        )
        HarvestJournal.objects.create(
            harvest=harvest,
            journal=updated_journal,
            result=HarvestJournal.Result.UPDATED,
        )
        HarvestJournal.objects.create(
            harvest=other_harvest,
            journal=other_journal,
            result=HarvestJournal.Result.ADDED,
        )

        response = self.client.get(
            f"/api/harvesting/harvests/{harvest.pk}/journals/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_items"], 1)
        self.assertEqual(
            [journal["id"] for journal in response.data["results"]],
            [added_journal.pk],
        )
        self.assertEqual(
            response.data["results"][0]["title"],
            added_journal.title,
        )

    def test_harvest_journals_returns_404_for_unknown_harvest(self):
        response = self.client.get("/api/harvesting/harvests/999999/journals/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_pending_harvest_can_be_paused_and_queued_to_resume(self):
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=100,
            api_cursor="openalex-cursor-123",
            created_by=self.user,
        )
        response = self.client.post(
            f"/api/harvesting/harvests/{harvest.pk}/pause/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"], Harvest.State.PAUSED)

        with patch(
            "apps.harvesting.views.services.dispatch_harvest_to_worker",
            side_effect=lambda item: item,
        ) as dispatch_harvest:
            response = self.client.post(
                f"/api/harvesting/harvests/{harvest.pk}/resume/",
                {},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["state"], Harvest.State.PENDING)
        self.assertEqual(dispatch_harvest.call_args.args[0].pk, harvest.pk)

    def test_running_harvest_pause_returns_accepted_while_page_finishes(self):
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=100,
            state=Harvest.State.RUNNING,
            created_by=self.user,
        )
        response = self.client.post(
            f"/api/harvesting/harvests/{harvest.pk}/pause/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["state"], Harvest.State.PAUSING)

    def test_resume_rejects_harvest_that_is_not_paused(self):
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=100,
            created_by=self.user,
        )
        response = self.client.post(
            f"/api/harvesting/harvests/{harvest.pk}/resume/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
