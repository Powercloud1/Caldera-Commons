import os
import subprocess
import sys
from datetime import datetime

from database import SessionLocal
import models


def list_pending():
    db = SessionLocal()
    try:
        rows = db.query(models.SentinelActionQueue).filter(models.SentinelActionQueue.status == "pending").order_by(models.SentinelActionQueue.created_at.asc()).all()
        if not rows:
            print("No pending sentinel actions.")
            return
        for row in rows:
            print(f"[{row.id}] {row.created_at} | {row.action_type.upper()} | {row.ip_address or 'N/A'} | {row.summary}")
    finally:
        db.close()


def apply_pending(action_id: int):
    db = SessionLocal()
    try:
        row = db.query(models.SentinelActionQueue).filter(models.SentinelActionQueue.id == action_id).first()
        if not row:
            print(f"Action {action_id} not found.")
            return 1
        if row.action_type != "block" or not row.ip_address:
            print("Only block actions with an IP can be applied from this CLI.")
            row.status = "dismissed"
            row.reviewed_at = datetime.utcnow()
            db.commit()
            return 1
        subprocess.run(["sudo", "iptables", "-A", "INPUT", "-s", row.ip_address, "-j", "DROP"], check=True)
        row.status = "applied"
        row.reviewed_at = datetime.utcnow()
        db.commit()
        print(f"Applied block for {row.ip_address}")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Failed to apply firewall rule: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sentinel_cli.py list|apply <id>")
        sys.exit(1)
    command = sys.argv[1]
    if command == "list":
        list_pending()
    elif command == "apply" and len(sys.argv) >= 3:
        sys.exit(apply_pending(int(sys.argv[2])))
    else:
        print("Usage: python sentinel_cli.py list|apply <id>")
        sys.exit(1)
