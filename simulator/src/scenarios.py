import random
import uuid
from datetime import datetime, timezone

CUSTOMERS = [
    ("cust_001", "Acme Corp"),
    ("cust_002", "Globex Inc"),
    ("cust_003", "Initech"),
    ("cust_004", "Umbrella Corp"),
    ("cust_005", "Stark Industries"),
    ("cust_006", "Wayne Enterprises"),
    ("cust_007", "Wonka Industries"),
    ("cust_008", "Cyberdyne Systems"),
    ("cust_009", "Soylent Corp"),
    ("cust_010", "Weyland-Yutani"),
]

ENDPOINTS = [
    ("/api/v1/orders", "POST"),
    ("/api/v1/orders", "GET"),
    ("/api/v1/users", "GET"),
    ("/api/v1/products", "GET"),
    ("/api/v1/health", "GET"),
]

REGIONS = ["us-east-1", "us-west-2", "eu-west-1"]

NORMAL_DEPLOY = "v1.2.3"
BAD_DEPLOY = "v1.2.4"


def generate_normal_event(deploy_version: str = NORMAL_DEPLOY) -> dict:
    """Generate a normal telemetry event with healthy latency."""
    customer_id, customer_name = random.choice(CUSTOMERS)
    endpoint, method = random.choice(ENDPOINTS)

    latency = random.gauss(50, 15)
    latency = max(5, latency)

    status_code = random.choices([200, 201, 400, 500], weights=[85, 10, 4, 1])[0]
    error_message = None
    if status_code >= 500:
        error_message = "Internal server error"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": str(uuid.uuid4()),
        "customer_id": customer_id,
        "customer_name": customer_name,
        "endpoint": endpoint,
        "method": method,
        "status_code": status_code,
        "latency_ms": round(latency, 1),
        "deploy_version": deploy_version,
        "region": random.choice(REGIONS),
        "error_message": error_message,
    }


def generate_bad_deploy_event() -> dict:
    """Generate a degraded event for Wonka Industries after bad deploy."""
    endpoint, method = random.choice(ENDPOINTS)

    # Wonka Industries gets massively degraded on /api/v1/orders
    if endpoint == "/api/v1/orders":
        latency = random.gauss(2500, 500)
        status_code = random.choices([200, 500, 503], weights=[40, 35, 25])[0]
    else:
        latency = random.gauss(800, 200)
        status_code = random.choices([200, 500], weights=[70, 30])[0]

    latency = max(100, latency)
    error_message = None
    if status_code >= 500:
        error_message = random.choice([
            "Connection timeout to downstream service",
            "Database connection pool exhausted",
            "Service unavailable - circuit breaker open",
        ])

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": str(uuid.uuid4()),
        "customer_id": "cust_007",
        "customer_name": "Wonka Industries",
        "endpoint": endpoint,
        "method": method,
        "status_code": status_code,
        "latency_ms": round(latency, 1),
        "deploy_version": BAD_DEPLOY,
        "region": "us-east-1",
        "error_message": error_message,
    }
