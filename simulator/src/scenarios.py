"""
Telemetry simulator scenarios.

The bug is in a code path, not tied to a customer.
Whoever calls that path the most gets hurt the most.

The connection pool leak is quadratic — occasional users barely notice,
but heavy users hit cascading failures as connections pile up.
"""

import random
import uuid
from datetime import datetime, timezone

CUSTOMERS = {
    "cust_001": {"name": "Acme Corp",         "rps": (0, 1), "orders_pct": 5},
    "cust_002": {"name": "Globex Inc",         "rps": (0, 2), "orders_pct": 8},
    "cust_003": {"name": "Initech",            "rps": (0, 1), "orders_pct": 3},
    "cust_004": {"name": "Umbrella Corp",      "rps": (0, 2), "orders_pct": 10},
    "cust_005": {"name": "Stark Industries",   "rps": (1, 2), "orders_pct": 12},
    "cust_006": {"name": "Wayne Enterprises",  "rps": (1, 2), "orders_pct": 8},
    "cust_007": {"name": "Wonka Industries",   "rps": (2, 4), "orders_pct": 85},
    "cust_008": {"name": "Cyberdyne Systems",  "rps": (1, 2), "orders_pct": 6},
    "cust_009": {"name": "Soylent Corp",       "rps": (0, 2), "orders_pct": 7},
    "cust_010": {"name": "Weyland-Yutani",     "rps": (1, 3), "orders_pct": 10},
}

ENDPOINTS = ["/api/v1/orders", "/api/v1/users", "/api/v1/products", "/api/v1/health"]
METHODS = {"/api/v1/orders": "POST", "/api/v1/users": "GET", "/api/v1/products": "GET", "/api/v1/health": "GET"}
REGIONS = ["us-east-1", "us-west-2", "eu-west-1"]

NORMAL_DEPLOY = "v1.2.3"
BAD_DEPLOY = "v1.2.4"

_customer_hits: dict[str, int] = {}


def _pick_endpoint(orders_pct: int) -> str:
    if random.randint(1, 100) <= orders_pct:
        return "/api/v1/orders"
    return random.choice(ENDPOINTS[1:])


def _customer_pressure(cid: str) -> float:
    """Quadratic pressure: occasional users barely notice, heavy users cascade."""
    hits = _customer_hits.get(cid, 0)
    linear = min(1.0, hits / 150)  # normalize to 0-1 over 150 requests
    return linear * linear          # square it - degrade much faster


def _make_event(cid: str, endpoint: str, deploy: str, degraded: bool) -> dict:
    if degraded:
        _customer_hits[cid] = _customer_hits.get(cid, 0) + 1
        pressure = _customer_pressure(cid)

        error_rate = 0.02 + pressure * 0.55       # 2% baseline → up to 57% under full pressure
        latency_multiplier = 1 + pressure * 50    # 1x baseline → up to 51x under full pressure

        if random.random() < error_rate:
            status = random.choice([500, 502, 503])
            error = random.choice([
                "Database connection pool exhausted",
                "Circuit breaker open",
                "Connection timeout to orders-db",
            ])
        else:
            status, error = 200, None

        latency = random.gauss(50, 15) * latency_multiplier
        latency = max(50, latency)
    else:
        latency = random.gauss(50, 15)
        if random.random() < 0.01:
            status, error = 500, "Internal server error"
        else:
            status, error = 200, None

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": str(uuid.uuid4()),
        "customer_id": cid,
        "customer_name": CUSTOMERS[cid]["name"],
        "endpoint": endpoint,
        "method": METHODS[endpoint],
        "status_code": status,
        "latency_ms": round(max(5, latency), 1),
        "deploy_version": deploy,
        "region": random.choice(REGIONS),
        "error_message": error,
    }


def generate_batch(bad_deploy_active: bool = False) -> list[dict]:
    """One tick of events across all customers. Returns 5-25 events."""
    deploy = BAD_DEPLOY if bad_deploy_active else NORMAL_DEPLOY
    events = []

    for cid, profile in CUSTOMERS.items():
        for _ in range(random.randint(*profile["rps"])):
            endpoint = _pick_endpoint(profile["orders_pct"])
            degraded = bad_deploy_active and endpoint == "/api/v1/orders"
            events.append(_make_event(cid, endpoint, deploy, degraded))

    random.shuffle(events)
    return events


def reset():
    """Reset bug state."""
    global _customer_hits
    _customer_hits = {}