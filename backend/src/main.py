import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .config import AGENT_CYCLE_INTERVAL, OPENAI_API_KEY
from .events import event_bus
from .iceberg_writer import connect_catalog, ensure_events_table
from .ingestion import EventBuffer, event_buffer, periodic_flush
from .query import query_customer_health, query_recent_telemetry
from .schema import TelemetryEvent
from .agent.runtime import AgentRuntime
from .agent.snapshot import SnapshotStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# Global state
catalog = None
iceberg_table = None
agent_runtime = None
bad_deploy_triggered = False
agent_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalog, iceberg_table, agent_runtime

    # Connect to Iceberg catalog with retries
    logger.info("Connecting to Iceberg REST catalog...")
    catalog = connect_catalog(max_retries=15, delay=2.0)
    iceberg_table = ensure_events_table(catalog)

    # Configure the event buffer
    event_buffer.set_table(iceberg_table)

    # Initialize agent runtime
    agent_runtime = AgentRuntime(catalog)

    def agent_event_callback(event_type: str, data: dict):
        event_bus.publish(f"agent:{event_type}", data)

    agent_runtime.set_event_callback(agent_event_callback)

    # Start background tasks
    flush_task = asyncio.create_task(periodic_flush(event_buffer))
    agent_task = asyncio.create_task(agent_background_loop())

    logger.info("TigerLite backend started")
    yield

    flush_task.cancel()
    agent_task.cancel()
    logger.info("TigerLite backend shutting down")


async def agent_background_loop():
    """Run the agent every AGENT_CYCLE_INTERVAL seconds."""
    global agent_running
    # Wait for some data to accumulate before first agent run
    await asyncio.sleep(AGENT_CYCLE_INTERVAL)

    while True:
        if OPENAI_API_KEY and not agent_running:
            try:
                agent_running = True
                event_bus.publish("agent:status", {"status": "running"})
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, agent_runtime.run_cycle)
                event_bus.publish("agent:status", {"status": "idle", "last_result": result})
            except Exception as e:
                logger.error(f"Agent cycle error: {e}")
                event_bus.publish("agent:status", {"status": "error", "error": str(e)})
            finally:
                agent_running = False

        await asyncio.sleep(AGENT_CYCLE_INTERVAL)


app = FastAPI(title="TigerLite", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health ---

@app.get("/health")
async def health():
    return {"status": "ok", "catalog": catalog is not None}


# --- Ingestion ---

@app.post("/ingest")
async def ingest(event: TelemetryEvent):
    await event_buffer.add(event)
    event_bus.publish("telemetry", {
        "customer_id": event.customer_id,
        "customer_name": event.customer_name,
        "endpoint": event.endpoint,
        "status_code": event.status_code,
        "latency_ms": event.latency_ms,
        "deploy_version": event.deploy_version,
    })
    return {"status": "accepted"}


# --- Query ---

@app.get("/api/customer-health")
async def customer_health():
    if not catalog:
        return {"error": "Catalog not ready"}
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, query_customer_health, catalog)
    return {"customers": result}


@app.get("/api/telemetry/recent")
async def recent_telemetry(limit: int = 50):
    if not catalog:
        return {"error": "Catalog not ready"}
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, query_recent_telemetry, catalog, limit)
    return {"events": result}


# --- Agent ---

@app.post("/api/agent/run")
async def trigger_agent_run(background_tasks: BackgroundTasks):
    global agent_running
    if not OPENAI_API_KEY:
        return {"error": "OpenAI API key not configured"}
    if agent_running:
        return {"error": "Agent is already running"}

    def run():
        global agent_running
        try:
            agent_running = True
            event_bus.publish("agent:status", {"status": "running"})
            result = agent_runtime.run_cycle()
            event_bus.publish("agent:status", {"status": "idle", "last_result": result})
        except Exception as e:
            logger.error(f"Manual agent run error: {e}")
            event_bus.publish("agent:status", {"status": "error", "error": str(e)})
        finally:
            agent_running = False

    background_tasks.add_task(run)
    return {"status": "agent_triggered"}


@app.get("/api/findings")
async def get_findings():
    if not agent_runtime:
        return {"findings": []}
    return {"findings": agent_runtime.findings}


@app.get("/api/snapshots/{session_id}")
async def get_session_snapshots(session_id: str):
    store = SnapshotStore()
    versions = store.list_versions(session_id)
    return {"session_id": session_id, "snapshots": versions}


@app.get("/api/snapshots/{session_id}/{version}")
async def get_snapshot(session_id: str, version: int):
    store = SnapshotStore()
    from .agent.object_store import ObjectStore
    obj_store = ObjectStore()
    snapshot = store.load(session_id, version)
    # Resolve descriptors to actual objects
    objects = [obj_store.get(sha) for sha in snapshot.descriptors]
    return {"snapshot": snapshot.to_dict(), "objects": objects}


@app.get("/api/sessions")
async def list_sessions():
    store = SnapshotStore()
    sessions = store.list_sessions()
    return {"sessions": sessions}


# --- Scenario Control ---

@app.post("/api/scenario/trigger-bad-deploy")
async def trigger_bad_deploy():
    global bad_deploy_triggered
    bad_deploy_triggered = True
    event_bus.publish("scenario", {"event": "bad_deploy_triggered", "deploy_version": "v1.2.4"})
    return {"status": "bad_deploy_triggered"}


@app.get("/api/scenario/status")
async def scenario_status():
    return {
        "bad_deploy_triggered": bad_deploy_triggered,
        "agent_running": agent_running,
        "total_events_ingested": event_buffer.total_ingested,
    }


# --- SSE ---

@app.get("/api/agent/stream")
async def agent_stream():
    return EventSourceResponse(event_bus.subscribe())
