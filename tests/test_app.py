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


def test_audit_packet_with_escalation_result(audit_dir):
    """Test audit packet includes Call-E escalation result when provided."""
    record = build_synthetic_incident_record("Critical incident. Deploy crews.", "mock", "microphone")
    escalation_result = {
        "status": "escalation_completed",
        "final_status": "ESCALATION_APPROVED",
        "auth_confirmed": True,
        "approval_decision": "approve",
    }

    filepath = save_audit_packet(
        record,
        "Escalate",
        "ESCALATION_APPROVED",
        escalation_result=escalation_result,
        audit_dir=audit_dir
    )

    with open(filepath, 'r') as f:
        packet = json.load(f)

    assert "escalation_result" in packet
    assert packet["escalation_result"]["final_status"] == "ESCALATION_APPROVED"
    assert packet["escalation_result"]["auth_confirmed"] is True
    assert packet["dry_run"] is True  # Still a dry-run even with escalation


def test_audit_packet_without_escalation_result_is_still_valid(audit_dir):
    """Test that audit packets without escalation result are still valid."""
    record = build_synthetic_incident_record("Test transcript", "mock")

    filepath = save_audit_packet(
        record,
        "Approve",
        "ESCALATION_APPROVED",
        escalation_result=None,
        audit_dir=audit_dir
    )

    with open(filepath, 'r') as f:
        packet = json.load(f)

    assert "escalation_result" not in packet
    assert packet["reviewer_decision"] == "Approve"
    assert packet["dry_run"] is True

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


def test_app_call_e_controls_only_after_escalate():
    """Test that Call-E controls appear only after Escalate decision."""
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()
    # Call-E escalation controls should only show when decision was "Escalate"
    assert 'if st.session_state.executed_decision == "Escalate"' in content
    assert "Call‑E Supervisor Escalation" in content
    assert "dry-run simulation" in content.lower()
    assert "no real call" in content.lower()


def test_app_clears_escalation_state_on_new_incident():
    """Test that new incidents clear previous Call-E state."""
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()
    # The store_incident function should clear escalation state
    assert "st.session_state.escalation_result = None" in content
    assert "st.session_state.escalation_scenario_executed = None" in content
    assert "st.session_state.escalation_consent = False" in content


def test_app_call_e_imports():
    """Test that app.py imports Call-E adapter."""
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "from backend.call_e_adapter import" in content
    assert "build_advisory" in content
    assert "build_dry_run_escalation" in content
    assert "DRY_RUN_SCENARIOS" in content


def test_audit_packet_escalation_result_includes_all_required_fields(audit_dir):
    """Test that Call-E escalation result in audit includes execution details."""
    record = build_synthetic_incident_record(
        "Critical incident. Deploy crews.",
        "assemblyai_live",
        "microphone"
    )

    escalation_result = {
        "status": "escalation_completed",
        "timestamp": "2026-09-22T18:03:38.123456Z",
        "final_status": "ESCALATION_APPROVED",
        "auth_confirmed": True,
        "review_confirmed": True,
        "approval_decision": "approve",
        "supervisor_outcome": "approved",
        "workflow_result_text": "Authorized supervisor approved escalation.",
        "transcript_summary": "Call-E: Hello, I'm Call-E...",
        "dry_run_scenario": "Authorized, reviewed, approve",
    }

    filepath = save_audit_packet(
        record,
        "Escalate",
        "ESCALATION_APPROVED",
        escalation_result=escalation_result,
        audit_dir=audit_dir
    )

    with open(filepath, 'r') as f:
        packet = json.load(f)

    assert "escalation_result" in packet
    assert packet["escalation_result"]["status"] == "escalation_completed"
    assert packet["escalation_result"]["final_status"] == "ESCALATION_APPROVED"
    assert packet["escalation_result"]["supervisor_outcome"] == "approved"
    assert packet["escalation_result"]["auth_confirmed"] is True
    assert "timestamp" in packet["escalation_result"]
    assert packet["dry_run"] is True
    assert packet["provenance"]["input_channel"] == "microphone"


def test_audit_packet_captures_failure_scenario(audit_dir):
    """Test that Call-E failure scenario is properly recorded in audit."""
    record = build_synthetic_incident_record("Test incident.", "mock")

    escalation_result = {
        "status": "failed",
        "timestamp": "2026-09-22T18:03:38.123456Z",
        "final_status": "CALL_EXECUTION_FAILED",
        "supervisor_outcome": "failed",
        "error_message": "Simulated Call-E provider error: unable to complete call.",
        "workflow_result_text": "Call-E execution failed.",
        "dry_run_scenario": "Call-E execution failure",
    }

    filepath = save_audit_packet(
        record,
        "Escalate",
        "ESCALATION_APPROVED",
        escalation_result=escalation_result,
        audit_dir=audit_dir
    )

    with open(filepath, 'r') as f:
        packet = json.load(f)

    assert packet["escalation_result"]["status"] == "failed"
    assert packet["escalation_result"]["supervisor_outcome"] == "failed"
    assert packet["escalation_result"]["error_message"] is not None
    assert packet["dry_run"] is True


def test_app_outcome_mapping_available_for_audit_save():
    """Regression test: outcome_mapping must be available to audit-save button (NameError fix)."""
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Verify outcome_mapping is defined at scope visible to both decision and audit-save paths
    # Should appear before the "Execute Decision" button (not nested inside it)
    decision_button_pos = content.find('if st.button("Execute Decision"')
    outcome_mapping_pos = content.find('outcome_mapping = {')

    assert outcome_mapping_pos > 0, "outcome_mapping dict not found"
    assert outcome_mapping_pos < decision_button_pos, (
        "outcome_mapping must be defined before Execute Decision button, "
        "not inside it, so it's available to audit-save"
    )

    # Verify the mapping includes all decision types
    assert '"Approve"' in content
    assert '"Hold"' in content
    assert '"Reject"' in content
    assert '"Escalate"' in content

    # Verify outcome_mapping is referenced in the audit-save path
    assert "outcome_mapping.get(st.session_state.executed_decision" in content


def test_ai_agent_transcript_wording_updated():
    """Test that AI agent intro uses updated wording for audit packet logging."""
    from backend.call_e_adapter import build_dry_run_escalation

    advisory = {"advisory_id": "SYN-WORDING"}
    result = build_dry_run_escalation(advisory, "Authorized, reviewed, approve")

    transcript = result.get("transcript_summary", "")
    assert "simulated interaction will be logged in the audit packet" in transcript.lower()
    assert "operational audit purposes" not in transcript
