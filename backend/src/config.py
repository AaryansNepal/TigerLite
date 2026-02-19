import os


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "password")

ICEBERG_REST_URI = os.getenv("ICEBERG_REST_URI", "http://localhost:8181")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "admin")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "password")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

WAREHOUSE_BUCKET = "warehouse"
SNAPSHOTS_BUCKET = "snapshots"

FLUSH_INTERVAL_SECONDS = 5
FLUSH_BATCH_SIZE = 100
AGENT_CYCLE_INTERVAL = 30
