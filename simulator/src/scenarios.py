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
    """
    SQUARED pressure curve — this is the key design choice.

    Connection pool leaks are non-linear in reality: a few leaked connections
    are invisible, but once you cross ~70% pool capacity, everything cascades.
    The squared term models this:

    After 90 seconds of bad deploy:
      Wonka:   ~145 hits → (145/150)² = 0.93 → error 53%, p99 ~2500ms  → CRITICAL
      Weyland:  ~63 hits → (63/150)²  = 0.18 → error 12%, p99 ~500ms   → mild warning
      Stark:    ~40 hits → (40/150)²  = 0.07 → error  6%, p99 ~200ms   → barely visible
      Globex:   ~18 hits → (18/150)²  = 0.01 → error  3%, p99 ~75ms    → normal
      Initech:   ~5 hits → (5/150)²   = 0.00 → error  2%, p99 ~55ms    → normal

    Result: Wonka is clearly the outlier. Everyone else is mostly fine.
    """
    hits = _customer_hits.get(cid, 0)
    linear = min(1.0, hits / 150)
    return linear * linear  # squared — the magic


def _make_event(cid: str, endpoint: str, deploy: str, degraded: bool) -> dict:
    if degraded:
        _customer_hits[cid] = _customer_hits.get(cid, 0) + 1
        pressure = _customer_pressure(cid)

        error_rate = 0.02 + pressure * 0.55
        latency_multiplier = 1 + pressure * 50

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