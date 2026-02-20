"""Environment configuration — all external dependencies configured here.

Reads from env vars with sane defaults for local development.
Docker Compose sets production values via docker-compose.yml.
"""

import os

# MinIO (S3-compatible object storage)
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "password")

# Iceberg REST catalog + S3 backend
ICEBERG_REST_URI = os.getenv("ICEBERG_REST_URI", "http://localhost:8181")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "admin")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "password")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Gemini LLM for the agent
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# S3 bucket names
WAREHOUSE_BUCKET = "warehouse"    # Iceberg table data (Parquet files)
SNAPSHOTS_BUCKET = "snapshots"    # Agent reasoning chains (JSON objects)

# Ingestion tuning
FLUSH_INTERVAL_SECONDS = 5        # How often to flush buffered events to Iceberg
FLUSH_BATCH_SIZE = 100            # Max events before forcing an early flush
