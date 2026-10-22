import httpx
from celery import shared_task

from .services import RetryableHarvestError, process_harvest_worker_step


@shared_task(
    bind=True,
    autoretry_for=(httpx.TransportError, RetryableHarvestError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    name="apps.harvesting.process_harvest_step",
)
def process_harvest_step(self, harvest_id: int, checkpoint: int) -> dict:
    result = process_harvest_worker_step(harvest_id, checkpoint)
    if result["has_more"]:
        self.apply_async(args=(harvest_id, result["checkpoint"]))
    return result
