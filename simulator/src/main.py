import asyncio
import logging
import os
import time

import httpx

from .scenarios import generate_batch, reset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
GO_INGESTION_URL = os.getenv("GO_INGESTION_URL", "")
INGEST_URL = GO_INGESTION_URL if GO_INGESTION_URL else BACKEND_URL
BAD_DEPLOY_DELAY = int(os.getenv("BAD_DEPLOY_DELAY", "60"))


async def send_event(client: httpx.AsyncClient, event: dict):
    try:
        resp = await client.post(f"{INGEST_URL}/ingest", json=event, timeout=5.0)
        if resp.status_code not in (200, 202):
            logger.warning(f"Ingest returned {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to send event: {e}")


async def run_simulator():
    start = time.time()
    bad_deploy = False
    total = 0
    reset()

    async with httpx.AsyncClient() as client:
        # Wait for backend
        for attempt in range(30):
            try:
                r = await client.get(f"{BACKEND_URL}/health", timeout=2.0)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(2)

        logger.info(f"Simulator started — bad deploy in {BAD_DEPLOY_DELAY}s")

        while True:
            elapsed = time.time() - start

            if not bad_deploy:
                try:
                    r = await client.get(f"{BACKEND_URL}/api/scenario/status", timeout=2.0)
                    if r.status_code == 200 and r.json().get("bad_deploy_triggered"):
                        bad_deploy = True
                        logger.info("══ BAD DEPLOY v1.2.4 ROLLED OUT (dashboard trigger) ══")
                except Exception:
                    pass

            if elapsed > BAD_DEPLOY_DELAY and not bad_deploy:
                bad_deploy = True
                logger.info("══ BAD DEPLOY v1.2.4 ROLLED OUT ══")
                try:
                    await client.post(f"{BACKEND_URL}/api/scenario/trigger-bad-deploy", timeout=5.0)
                except Exception:
                    pass

            batch = generate_batch(bad_deploy_active=bad_deploy)
            await asyncio.gather(*[send_event(client, e) for e in batch])
            total += len(batch)

            if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                logger.info(f"{'[BAD]' if bad_deploy else '[OK]'} {total} events sent ({elapsed:.0f}s)")

            await asyncio.sleep(1)


def main():
    asyncio.run(run_simulator())


if __name__ == "__main__":
    main()