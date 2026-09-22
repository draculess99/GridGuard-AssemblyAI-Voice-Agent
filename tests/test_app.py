import os
import json
import pytest
from tempfile import TemporaryDirectory
from backend.extraction import extract_incident_details
from backend.audit import save_audit_packet
from backend.assemblyai_integration import is_mock_mode, mock_transcribe_audio
from backend.incident import build_synthetic_incident_record


@pytest.fixture
def audit_dir():
    with TemporaryDirectory(dir=os.getcwd()) as directory:
        yield directory

def test_extraction_logic():
    transcript = "The Substation Alpha is experiencing a critical thermal overload. We need to deploy emergency crews."
    details = extract_incident_details(transcript)
    assert details["location"] == "Substation Alpha"
    assert details["severity"] == "Critical"
    assert details["affected_asset"] == "Thermal Overload"
    assert details["requested_action"] == "Deploy emergency crews"


def test_extraction_operator_requests_pattern():
    """Test extraction of requested action using 'operator requests' pattern."""
    transcript = "The operator requests emergency crew standby and a controlled inspection."
    details = extract_incident_details(transcript)
    assert details["requested_action"] == "Emergency crew standby and a controlled inspection"
    assert details["requested_action"] != "Unknown"


def test_extraction_requests_pattern():
    """Test extraction using plain 'requests' pattern (existing request-style phrase)."""
    transcript = "North Grid is experiencing elevated conditions. We requests immediate shutdown of the transmission line."
    details = extract_incident_details(transcript)
    assert details["requested_action"] != "Unknown"
    assert "shutdown" in details["requested_action"].lower() or "transmission" in details["requested_action"].lower()


def test_extraction_live_microphone_transcript():
    """Regression test: extract requested action from full live microphone transcript."""
    transcript = "Hello, my name is William Lowe. This is a synthetic training incident. Substation Alpha is experiencing a critical thermal overload. The operator requests emergency cover standby and a controlled inspection. No automatic dispatch, isolation, or grid control is authorized. An authorized human reviewer must review the transcript and decide whether to approve, hold, reject, or escalate the proposed action."
    details = extract_incident_details(transcript)
    assert details["location"] == "Substation Alpha"
    assert details["severity"] == "Critical"
    assert details["affected_asset"] == "Thermal Overload"
    assert details["requested_action"] == "Emergency cover standby and a controlled inspection"
    assert details["requested_action"] != "Unknown"

def test_audit_packet_creation(audit_dir):
    record = build_synthetic_incident_record(mock_transcribe_audio(), "mock")
    filepath = save_audit_packet(record, "Approve", "ESCALATION_APPROVED", audit_dir)
    
    assert os.path.exists(filepath)
    with open(filepath, 'r') as f:
        packet = json.load(f)
        
    assert packet["reviewer_decision"] == "Approve"
    assert packet["outcome_state"] == "ESCALATION_APPROVED"
    assert packet["structured_incident_record"] == record
    assert packet["provenance"] == {"source": "mock", "input_channel": "unspecified"}
    assert packet["dry_run"] is True

def test_audit_packet_other_outcomes(audit_dir):
    record = build_synthetic_incident_record("Mock transcript", "mock")
    
    for decision, state in [("Hold", "REVIEWED_HOLD"), ("Reject", "REVIEWED_NOT_APPROVED")]:
        filepath = save_audit_packet(record, decision, state, audit_dir)
        with open(filepath, 'r') as f:
            packet = json.load(f)
        assert packet["reviewer_decision"] == decision
        assert packet["outcome_state"] == state

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
    assert "Unconfirmed" in timeline[3]["text"]

def test_conversation_timeline_live():
    transcript = "Real live transcript of an event."
    details = {"severity": "Critical", "location": "Alpha", "affected_asset": "Transformer", "requested_action": "Deploy"}
    timeline = generate_conversation_timeline(transcript, details, is_mock=False)
    
    assert len(timeline) == 7
    assert timeline[0]["speaker"] == "Caller"
    assert timeline[0]["text"] == transcript
    assert timeline[3]["speaker"] == "GridGuard Authorization Service"
    assert "OPS-4721" not in " ".join(message["text"] for message in timeline)

def test_post_decision_state_rendered_logic():
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "Dry-run recorded — no grid action executed" in content
    assert "Audit status:** Recorded successfully" in content
    assert "Caller identity:** Unconfirmed — never inferred from audio" in content
    assert "The API key was not rejected" in content
    assert "outbound TCP 443" in content


def test_app_wires_upload_and_microphone_through_shared_ingest():
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()
    # Both channels flow through the one ingest_audio -> handle_audio_input -> store_incident path.
    assert 'ingest_audio(uploaded_file.getvalue(), uploaded_file.name.split' in content
    assert 'ingest_audio(recorded_audio.getvalue(), "wav", "microphone")' in content
    assert "st.audio_input(" in content
    assert "not sent to" in content
    # A brand-new incident must reset the approval gate, not inherit a prior decision.
    assert "st.session_state.review_consent = False" in content
    assert "st.session_state.review_decision = None" in content
