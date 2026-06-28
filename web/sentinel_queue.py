import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

import models


def enqueue_sentinel_decision(
    db_session: Session,
    decision: Dict[str, Any],
    summary: str,
    raw_ai_output: str,
) -> Optional[models.SentinelActionQueue]:
    if not decision:
        return None

    record = models.SentinelActionQueue(
        ip_address=decision.get("offending_ip"),
        action_type=decision.get("action_required") or "none",
        threat_detected=bool(decision.get("threat_detected")),
        summary=summary or decision.get("sentinel_summary") or "Sentinel decision queued for review",
        raw_ai_output=raw_ai_output,
        payload=json.dumps(decision, sort_keys=True),
        status="pending",
    )
    db_session.add(record)
    db_session.commit()
    return record
