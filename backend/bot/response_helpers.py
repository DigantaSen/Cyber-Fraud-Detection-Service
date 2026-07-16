"""Standard response envelope helpers (docs/api/_shared_contract.md)."""
import uuid
from datetime import datetime, timezone
from typing import Any


def success_response(data: Any, correlation_id: str = "") -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "success",
        "data": data,
    }


def error_response(
    error_code: str,
    message: str,
    correlation_id: str = "",
    details: Any = None,
) -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "error",
        "errorCode": error_code,
        "message": message,
        "details": details,
    }
