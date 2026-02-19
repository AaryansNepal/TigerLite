import asyncio
import logging
import os
import time

import httpx

from .scenarios import (
    BAD_DEPLOY,
    generate_bad_deploy_event,
    generate_normal_event,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
GO_INGESTION_URL = os.getenv("GO_INGESTION_URL", "")
INGEST_URL = GO_INGESTION_URL if GO_INGESTION_URL else BACKEND_URL
BAD_DEPLOY_DELAY = 60  # seconds before bad deploy starts


async def send_event(client: httpx.AsyncClient, event: dict):
    try:
        resp = await client.post(f"{INGEST_URL}/ingest", json=event, timeout=5.0)
        if resp.status_code not in (200, 202):
            logger.warning(f"Ingest returned {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to send event: {e}")


async def run_simulator():
    start_time = time.time()
    bad_deploy_active = False

    async with httpx.AsyncClient() as client:
        # Wait for backend to be ready
        for _ in range(30):
            try:
                resp = await client.get(f"{BACKEND_URL}/health", timeout=2.0)
                if resp.status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(2)

        logger.info("Simulator started - generating normal traffic")

        while True:
            elapsed = time.time() - start_time

            if elapsed > BAD_DEPLOY_DELAY and not bad_deploy_active:
                bad_deploy_active = True
                logger.info(
                    f"BAD DEPLOY triggered after {int(elapsed)}s "
                    "- Wonka Industries will degrade"
                )
                # Notify backend about the bad deploy
                try:
                    await client.post(
                        f"{BACKEND_URL}/api/scenario/trigger-bad-deploy",
                        timeout=5.0,
                    )
                except Exception:
                    pass

            # Generate 3-8 events per batch
            deploy_version = BAD_DEPLOY if bad_deploy_active else "v1.2.3"
            batch_size = 5

            tasks = []
            for _ in range(batch_size):
                if bad_deploy_active and time.time() % 3 < 1:
                    # ~1/3 of events are Wonka bad deploy events
                    event = generate_bad_deploy_event()
                else:
                    event = generate_normal_event(deploy_version)
                tasks.append(send_event(client, event))

            await asyncio.gather(*tasks)
            await asyncio.sleep(1)


def main():
    asyncio.run(run_simulator())


if __name__ == "__main__":
    main()
