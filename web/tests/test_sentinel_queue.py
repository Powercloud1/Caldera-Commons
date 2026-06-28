import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from sentinel_queue import enqueue_sentinel_decision


def test_enqueue_sentinel_decision_creates_pending_record():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    decision = {
        "threat_detected": True,
        "offending_ip": "8.8.8.8",
        "action_required": "block",
        "sentinel_summary": "Threat queued for review",
    }

    record = enqueue_sentinel_decision(session, decision, "queued summary", "raw ai")

    assert record is not None
    assert record.status == "pending"
    assert record.ip_address == "8.8.8.8"
    assert record.action_type == "block"

    queued = session.query(models.SentinelActionQueue).first()
    assert queued is not None
    assert queued.status == "pending"
