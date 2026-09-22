import json
import os
from datetime import datetime, timezone
from typing import Dict

AUDIT_DIR = "audits"

def save_audit_packet(
    incident_record: Dict[str, object], decision: str, outcome_state: str, audit_dir: str = AUDIT_DIR
) -> str:
    """Persist a reviewer decision for a synthetic, dry-run incident record."""
    if not os.path.exists(audit_dir):
        os.makedirs(audit_dir)
        
    now_utc = datetime.now(timezone.utc)
    timestamp = now_utc.isoformat().replace("+00:00", "Z")
    packet = {
        "timestamp": timestamp,
        "structured_incident_record": incident_record,
        "provenance": {
            "source": incident_record["source"],
            "input_channel": incident_record.get("input_channel", "unspecified"),
        },
        "reviewer_decision": decision,
        "outcome_state": outcome_state,
        "dry_run": True,
    }
    
    filename = f"audit_{now_utc.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(audit_dir, filename)
    
    with open(filepath, 'w') as f:
        json.dump(packet, f, indent=2)
        
    return filepath
