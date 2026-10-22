from unittest.mock import patch

from django.test import SimpleTestCase

from apps.harvesting.tasks import process_harvest_step


class HarvestingTaskTests(SimpleTestCase):
    @patch("apps.harvesting.tasks.process_harvest_step.apply_async")
    @patch("apps.harvesting.tasks.process_harvest_worker_step")
    def test_task_queues_next_checkpoint_when_work_remains(
        self,
        process_step,
        enqueue_task,
    ):
        process_step.return_value = {
            "harvest_id": 17,
            "checkpoint": 8,
            "state": "running",
            "has_more": True,
            "stale": False,
        }

        result = process_harvest_step.run(17, 7)

        process_step.assert_called_once_with(17, 7)
        enqueue_task.assert_called_once_with(args=(17, 8))
        self.assertEqual(result["checkpoint"], 8)

    @patch("apps.harvesting.tasks.process_harvest_step.apply_async")
    @patch("apps.harvesting.tasks.process_harvest_worker_step")
    def test_task_does_not_queue_a_terminal_harvest(
        self,
        process_step,
        enqueue_task,
    ):
        process_step.return_value = {
            "harvest_id": 17,
            "checkpoint": 8,
            "state": "completed",
            "has_more": False,
            "stale": False,
        }

        process_harvest_step.run(17, 7)

        enqueue_task.assert_not_called()
