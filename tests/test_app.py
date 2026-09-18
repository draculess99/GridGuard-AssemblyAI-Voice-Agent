import os
import json
import pytest
from backend.extraction import extract_incident_details
from backend.audit import save_audit_packet, AUDIT_DIR
from backend.assemblyai_integration import is_mock_mode, mock_transcribe_audio

def test_extraction_logic():
    transcript = "The Substation Alpha is experiencing a critical thermal overload. We need to deploy emergency crews."
    details = extract_incident_details(transcript)
    assert details["location"] == "Substation Alpha"
    assert details["severity"] == "Critical"
    assert details["affected_asset"] == "Thermal Overload"
    assert details["requested_action"] == "Deploy emergency crews"

def test_audit_packet_creation():
    transcript = mock_transcribe_audio()
    details = extract_incident_details(transcript)
    filepath = save_audit_packet(transcript, details, "Approve", "ESCALATION_APPROVED")
    
    assert os.path.exists(filepath)
    with open(filepath, 'r') as f:
        packet = json.load(f)
        
    assert packet["decision"] == "Approve"
    assert packet["outcome_state"] == "ESCALATION_APPROVED"
    assert packet["transcript"] == transcript
    
    # cleanup
    os.remove(filepath)

def test_audit_packet_other_outcomes():
    transcript = "Mock transcript"
    details = {"location": "A", "severity": "B", "affected_asset": "C", "requested_action": "D"}
    
    for decision, state in [("Hold", "REVIEWED_HOLD"), ("Reject", "REVIEWED_NOT_APPROVED")]:
        filepath = save_audit_packet(transcript, details, decision, state)
        with open(filepath, 'r') as f:
            packet = json.load(f)
        assert packet["decision"] == decision
        assert packet["outcome_state"] == state
        os.remove(filepath)

def test_mock_mode_active_by_default():
    # If no env var is set, it should be mock mode
    if not os.environ.get("ASSEMBLYAI_API_KEY"):
        assert is_mock_mode() == True

from backend.conversation import generate_conversation_timeline

def test_conversation_timeline_mock():
    transcript = "Mock"
    details = {"severity": "Critical", "location": "Alpha", "affected_asset": "Transformer", "requested_action": "Deploy"}
    timeline = generate_conversation_timeline(transcript, details, is_mock=True)
    
    assert len(timeline) == 7
    assert timeline[0]["speaker"] == "Caller"
    assert "Jordan Lee" in timeline[0]["text"]
    assert timeline[3]["speaker"] == "GridGuard Authorization Service"
    assert "Demo authorization lookup" in timeline[3]["text"]

def test_conversation_timeline_live():
    transcript = "Real live transcript of an event."
    details = {"severity": "Critical", "location": "Alpha", "affected_asset": "Transformer", "requested_action": "Deploy"}
    timeline = generate_conversation_timeline(transcript, details, is_mock=False)
    
    assert len(timeline) == 7
    assert timeline[0]["speaker"] == "Caller"
    assert timeline[0]["text"] == transcript
    assert timeline[3]["speaker"] == "GridGuard Authorization Service"
