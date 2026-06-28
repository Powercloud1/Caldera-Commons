import json
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Optional
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", os.path.join(os.path.dirname(__file__), "audit.log"))
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "api_key",
    "authorization",
    "cookie",
    "session",
    "email",
    "full_name",
    "first_name",
    "last_name",
    "phone",
    "address",
    "ssn",
    "dob",
}


def _normalize_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return path.split("?", 1)[0]


def sanitize_for_logging(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else sanitize_for_logging(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [sanitize_for_logging(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_logging(item) for item in value)
    return value


def build_audit_entry(
    *,
    action_type: str,
    user_id: Optional[int] = None,
    request=None,
    ip_address: Optional[str] = None,
    resource: Optional[str] = None,
    result: Optional[str] = None,
    status_code: Optional[int] = None,
    detail: Any = None,
    severity: str = "info",
) -> dict:
    if request is not None:
        if ip_address is None:
            ip_address = get_client_ip(request)
        if resource is None:
            resource = _normalize_path(request.url.path)

    entry = {
        "timestamp": datetime.now(LOCAL_TZ).isoformat(),
        "action_type": action_type,
        "user_id": user_id,
        "ip_address": ip_address,
        "resource": resource,
        "result": result,
        "status_code": status_code,
        "severity": severity,
    }
    if detail is not None:
        entry["details"] = sanitize_for_logging(detail)
    if request is not None:
        entry["method"] = request.method
        entry["path"] = _normalize_path(request.url.path)
        user_agent = request.headers.get("user-agent")
        if user_agent:
            entry["user_agent"] = user_agent
    return entry


def get_client_ip(request) -> Optional[str]:
    if request is None:
        return None
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return None


def get_audit_logger() -> logging.Logger:
    logger = logging.getLogger("security_audit")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stream_handler)

    if AUDIT_LOG_PATH:
        file_handler = RotatingFileHandler(AUDIT_LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(file_handler)

    return logger


def log_security_event(**kwargs) -> None:
    entry = build_audit_entry(**kwargs)
    get_audit_logger().info(json.dumps(entry, default=str, sort_keys=True))
