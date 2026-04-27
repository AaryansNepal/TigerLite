"""TigerLite v2 agent runtime.

The snapshot loop. Pure-function `run_one_step(snapshot_id) → next_snapshot_id`
plus a long-running worker that consumes the queue. The lambda_handler.py
shim documents how to swap the worker for AWS Lambda + S3 events without
touching the step function — the same architectural property Firetiger
relies on.
"""

__version__ = "2.0.0.dev0"
