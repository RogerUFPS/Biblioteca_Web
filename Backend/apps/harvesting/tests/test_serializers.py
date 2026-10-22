from django.test import TestCase
from django.utils import timezone

from apps.account.models import User
from apps.harvesting.models import Harvest, Schedule, ScheduleEvent
from apps.harvesting.serializers import (
    HarvestSerializer,
    ScheduleEventSerializer,
    ScheduleSerializer,
)
from apps.platforms.models import Platform


class HarvestingSerializersTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
        )
        cls.platform = Platform.objects.create(
            name="OpenAlex",
            base_api_url="https://api.openalex.org",
            is_harvestable=True,
            created_by=cls.user,
        )

    def test_schedule_serializer_validates_and_saves_platforms_and_start(self):
        data = {
            "platforms": [self.platform.pk],
            "frequency": "daily",
            "max_quantity": 500,
            "start_date": timezone.now().isoformat(),
        }
        serializer = ScheduleSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        schedule = serializer.save(created_by=self.user)
        self.assertEqual(list(schedule.platforms.all()), [self.platform])
        self.assertIsNotNone(schedule.start_date)

    def test_schedule_serializer_requires_start_date(self):
        serializer = ScheduleSerializer(
            data={
                "platforms": [self.platform.pk],
                "frequency": "weekly",
                "max_quantity": 500,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("start_date", serializer.errors)

    def test_schedule_serializer_requires_at_least_one_limit(self):
        serializer = ScheduleSerializer(
            data={
                "platforms": [self.platform.pk],
                "frequency": "weekly",
                "start_date": timezone.now().isoformat(),
            }
        )
        self.assertFalse(serializer.is_valid())

    def test_schedule_serializer_requires_at_least_one_platform(self):
        serializer = ScheduleSerializer(
            data={
                "platforms": [],
                "frequency": "weekly",
                "max_quantity": 10,
                "start_date": timezone.now().isoformat(),
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("platforms", serializer.errors)

    def test_harvest_and_event_fields_are_read_only(self):
        schedule = Schedule.objects.create(
            frequency=Schedule.Frequency.ONCE,
            max_quantity=20,
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
            max_quantity=20,
            api_cursor="*",
            created_by=self.user,
        )
        harvest_data = HarvestSerializer(harvest).data
        event_data = ScheduleEventSerializer(event).data
        self.assertEqual(harvest_data["api_cursor"], "*")
        self.assertEqual(harvest_data["state"], Harvest.State.PENDING)
        self.assertEqual(event_data["harvests"], [harvest.pk])
