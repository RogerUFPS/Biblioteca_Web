from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.account.models import User
from apps.harvesting.models import Harvest, Schedule, ScheduleEvent
from apps.platforms.models import Platform


class HarvestingModelsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
        )
        cls.platform = Platform.objects.create(
            name="OpenAlex Platform",
            base_api_url="https://api.openalex.org",
            created_by=cls.user,
        )

    def test_create_schedule_success(self):
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.DAILY,
            max_quantity=500,
            start_date=timezone.now(),
            created_by=self.user,
        )
        schedule.platforms.add(self.platform)
        self.assertIn(self.platform, schedule.platforms.all())
        self.assertEqual(schedule.frequency, "daily")
        self.assertIsNotNone(schedule.start_date)
        self.assertFalse(hasattr(schedule, "is_active"))
        self.assertIn("Schedule #", str(schedule))

    def test_schedule_event_is_unique_for_each_scheduled_occurrence(self):
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.ONCE,
            max_quantity=500,
            start_date=timezone.now(),
            created_by=self.user,
        )
        scheduled_for = timezone.now()
        ScheduleEvent.objects.create(
            schedule=schedule,
            scheduled_for=scheduled_for,
            created_by=self.user,
        )
        with self.assertRaises(IntegrityError):
            ScheduleEvent.objects.create(
                schedule=schedule,
                scheduled_for=scheduled_for,
                created_by=self.user,
            )

    def test_create_harvest_success(self):
        harvest = Harvest.objects.create(
            platform=self.platform,
            max_quantity=100,
            api_cursor="*",
            created_by=self.user,
        )
        self.assertEqual(harvest.platform, self.platform)
        self.assertEqual(harvest.state, Harvest.State.PENDING)
        self.assertEqual(harvest.records_added, 0)
        self.assertEqual(harvest.records_updated, 0)
        self.assertEqual(harvest.records_failed, 0)
        self.assertIn("Harvest #", str(harvest))

    def test_harvest_requires_max_quantity_or_stop_after_minutes(self):
        """Verifica que falle el CheckConstraint si ambos límites son nulos."""
        with self.assertRaises(IntegrityError):
            Harvest.objects.create(
                platform=self.platform,
                max_quantity=None,
                stop_after_minutes=None,
                created_by=self.user,
            )

    def test_unique_active_harvest_per_platform_constraint(self):
        """Verifica que no se puedan crear dos cosechas activas simultáneas para la misma plataforma."""
        Harvest.objects.create(
            platform=self.platform,
            max_quantity=100,
            state=Harvest.State.RUNNING,
            created_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            Harvest.objects.create(
                platform=self.platform,
                max_quantity=50,
                state=Harvest.State.PENDING,
                created_by=self.user,
            )

    def test_multiple_completed_harvests_allowed(self):
        """Verifica que múltiples cosechas en estado finalizado (COMPLETED) sí estén permitidas."""
        h1 = Harvest.objects.create(
            platform=self.platform,
            max_quantity=100,
            state=Harvest.State.COMPLETED,
            created_by=self.user,
        )
        h2 = Harvest.objects.create(
            platform=self.platform,
            max_quantity=200,
            state=Harvest.State.COMPLETED,
            created_by=self.user,
        )
        self.assertIsNotNone(h1.pk)
        self.assertIsNotNone(h2.pk)
