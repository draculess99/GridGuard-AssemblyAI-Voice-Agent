import json
import os
from datetime import datetime, timezone
from typing import Dict

AUDIT_DIR = "audits"

def save_audit_packet(transcript: str, extracted_details: Dict[str, str], decision: str, outcome_state: str) -> str:
    if not os.path.exists(AUDIT_DIR):
        os.makedirs(AUDIT_DIR)
        
    now_utc = datetime.now(timezone.utc)
    timestamp = now_utc.isoformat().replace("+00:00", "Z")
    packet = {
        "timestamp": timestamp,
        "transcript": transcript,
        "extracted_details": extracted_details,
        "decision": decision,
        "outcome_state": outcome_state
    }
    
    filename = f"audit_{now_utc.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(AUDIT_DIR, filename)
    
    with open(filepath, 'w') as f:
        json.dump(packet, f, indent=2)
        
    return filepath
