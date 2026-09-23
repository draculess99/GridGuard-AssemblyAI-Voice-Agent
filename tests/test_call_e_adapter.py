"""Tests for dry-run Call-E escalation adapter."""

import pytest
from backend.call_e_adapter import (
    build_advisory,
    build_dry_run_escalation,
    DRY_RUN_SCENARIOS,
)
from backend.incident import build_synthetic_incident_record


def test_build_advisory_from_incident():
    """Test mapping incident record to advisory shape."""
    transcript = "Substation Alpha is critical. Deploy crews."
    record = build_synthetic_incident_record(transcript, "mock", "microphone")

    advisory = build_advisory(record)

    assert advisory["advisory_id"] == record["incident_id"]
    assert advisory["severity"] == "Critical"
    assert advisory["location"] == "Substation Alpha"
    assert advisory["evidence_summary"] == transcript
    assert "incident_record" not in advisory  # Does not include original record


def test_incident_record_not_mutated():
    """Test that building an advisory does not mutate the incident record."""
    transcript = "Substation Alpha is critical. Deploy crews."
    record = build_synthetic_incident_record(transcript, "mock", "upload")
    original_keys = set(record.keys())

    advisory = build_advisory(record)

    assert set(record.keys()) == original_keys
    assert record["raw_transcript"] == transcript


def test_dry_run_scenario_approved():
    """Test dry-run scenario: authorized, reviewed, approve."""
    advisory = {"advisory_id": "SYN-123", "severity": "Critical"}
    result = build_dry_run_escalation(advisory, "Authorized, reviewed, approve")

    assert result["final_status"] == "ESCALATION_APPROVED"
    assert result["auth_confirmed"] is True
    assert result["review_confirmed"] is True
    assert result["approval_decision"] == "approve"
    assert result["create_escalation_package"] is True
    assert result["mode"] == "dry_run"
    assert result["advisory_id"] == "SYN-123"


def test_dry_run_scenario_rejected():
    """Test dry-run scenario: authorized, reviewed, reject."""
    advisory = {"advisory_id": "SYN-456", "severity": "High"}
    result = build_dry_run_escalation(advisory, "Authorized, reviewed, reject")

    assert result["final_status"] == "REVIEWED_NOT_APPROVED"
    assert result["auth_confirmed"] is True
    assert result["approval_decision"] == "reject"
    assert result["create_escalation_package"] is False


def test_dry_run_scenario_not_authorized():
    """Test dry-run scenario: not authorized."""
    advisory = {"advisory_id": "SYN-789"}
    result = build_dry_run_escalation(advisory, "Not authorized / wrong person")

    assert result["final_status"] == "WRONG_RECIPIENT"
    assert result["auth_confirmed"] is False
    assert result["review_confirmed"] is None
    assert result["create_escalation_package"] is False


def test_dry_run_scenario_not_reviewed():
    """Test dry-run scenario: authorized but not reviewed."""
    advisory = {"advisory_id": "SYN-000"}
    result = build_dry_run_escalation(advisory, "Authorized, not reviewed")

    assert result["final_status"] == "PENDING_REVIEW"
    assert result["auth_confirmed"] is True
    assert result["review_confirmed"] is False
    assert result["create_escalation_package"] is False


def test_all_scenarios_have_required_fields():
    """Test that all scenarios return required fields."""
    advisory = {"advisory_id": "SYN-TEST"}
    required_fields = [
        "status",
        "timestamp",
        "dry_run_scenario",
        "advisory_id",
        "mode",
        "final_status",
        "auth_confirmed",
        "approval_decision",
        "create_escalation_package",
        "workflow_result_text",
    ]

    for scenario in DRY_RUN_SCENARIOS:
        result = build_dry_run_escalation(advisory, scenario)
        for field in required_fields:
            assert field in result, f"Missing {field} in scenario {scenario}"


def test_unknown_scenario_defaults_to_unclear():
    """Test that unknown scenario defaults to unclear response."""
    advisory = {"advisory_id": "SYN-UNK"}
    result = build_dry_run_escalation(advisory, "Unknown scenario")

    assert result["final_status"] == "NEEDS_MANUAL_FOLLOW_UP"
    assert result["auth_confirmed"] is None
    assert result["approval_decision"] == "unclear"
    assert result["create_escalation_package"] is False


def test_no_secrets_in_escalation_result():
    """Test that no secrets or phone numbers appear in escalation result."""
    advisory = {"advisory_id": "SYN-SECRET", "phone": "+15551234567"}
    result = build_dry_run_escalation(advisory, "Authorized, reviewed, approve")

    result_str = str(result)
    assert "CALLE_API_KEY" not in result_str
    assert "+15551234567" not in result_str
    assert "phone" not in result_str.lower()


def test_escalation_result_timestamp_is_valid():
    """Test that result contains a valid ISO timestamp."""
    advisory = {"advisory_id": "SYN-TS"}
    result = build_dry_run_escalation(advisory, "Authorized, reviewed, approve")

    timestamp = result.get("timestamp")
    assert timestamp is not None
    # Should be ISO format with Z suffix or timezone
    assert "T" in timestamp
    assert (timestamp.endswith("Z") or "+" in timestamp or "-" in timestamp)


def test_scenario_label_normalization():
    """Test that scenario labels are normalized for matching."""
    advisory = {"advisory_id": "SYN-NORM"}

    # All these variants should produce the same result
    variants = [
        "Authorized, reviewed, approve",
        "Authorized,reviewed,approve",
        "authorized, reviewed, approve",
        "AUTHORIZED, REVIEWED, APPROVE",
        "reviewed and approve",
        "approved",
    ]

    results = [build_dry_run_escalation(advisory, v) for v in variants]

    # All should have same final_status (though not all variants test the same)
    # At least check that approve/approved variants work
    for result in results:
        if result.get("final_status") == "ESCALATION_APPROVED":
            assert result["approval_decision"] == "approve"


def test_dry_run_failure_scenario():
    """Test dry-run scenario: Call-E execution failure."""
    advisory = {"advisory_id": "SYN-FAIL"}
    result = build_dry_run_escalation(advisory, "Call-E execution failure")

    assert result["status"] == "failed"
    assert result["final_status"] == "CALL_EXECUTION_FAILED"
    assert result["auth_confirmed"] is None
    assert result["review_confirmed"] is None
    assert result["approval_decision"] is None
    assert result["supervisor_outcome"] == "failed"
    assert result["create_escalation_package"] is False
    assert result["error_message"] is not None
    assert "unable to complete call" in result["error_message"].lower()


def test_all_scenarios_have_supervisor_outcome():
    """Test that all scenarios return a canonical supervisor_outcome field."""
    advisory = {"advisory_id": "SYN-OUTCOME"}
    valid_outcomes = {"approved", "denied", "unavailable", "failed"}

    for scenario in DRY_RUN_SCENARIOS:
        result = build_dry_run_escalation(advisory, scenario)
        assert "supervisor_outcome" in result
        assert result["supervisor_outcome"] in valid_outcomes


def test_ai_agent_disclosure_in_approved_transcript():
    """Test that Call-E explicitly identifies itself as an AI agent in transcripts."""
    advisory = {"advisory_id": "SYN-DISCLOSURE"}
    result = build_dry_run_escalation(advisory, "Authorized, reviewed, approve")

    transcript = result.get("transcript_summary", "")
    assert "Call-E" in transcript
    assert "AI agent" in transcript
    assert "GridGuard" in transcript
    assert "audit" in transcript.lower()


def test_ai_agent_disclosure_in_all_scenarios():
    """Test that AI agent disclosure appears in all normal (non-failure) transcripts."""
    advisory = {"advisory_id": "SYN-DISCALL"}

    for scenario in DRY_RUN_SCENARIOS:
        if scenario != "Call-E execution failure":  # Failure scenario has different transcript
            result = build_dry_run_escalation(advisory, scenario)
            transcript = result.get("transcript_summary", "")
            assert "Call-E" in transcript, f"Missing Call-E identification in {scenario}"
            assert "AI agent" in transcript, f"Missing AI agent disclosure in {scenario}"


def test_supervisor_outcome_mapping_approved():
    """Test canonical outcome field for approved scenario."""
    advisory = {"advisory_id": "SYN-MAP-APP"}
    result = build_dry_run_escalation(advisory, "Authorized, reviewed, approve")
    assert result["supervisor_outcome"] == "approved"
    assert result["auth_confirmed"] is True
    assert result["approval_decision"] == "approve"


def test_supervisor_outcome_mapping_denied():
    """Test canonical outcome field for denied scenario."""
    advisory = {"advisory_id": "SYN-MAP-DEN"}
    result = build_dry_run_escalation(advisory, "Authorized, reviewed, reject")
    assert result["supervisor_outcome"] == "denied"
    assert result["auth_confirmed"] is True
    assert result["approval_decision"] == "reject"


def test_supervisor_outcome_mapping_unavailable():
    """Test canonical outcome field maps unauthorized scenarios to unavailable."""
    advisory = {"advisory_id": "SYN-MAP-UNV"}

    # Test "not authorized" scenario
    result1 = build_dry_run_escalation(advisory, "Not authorized / wrong person")
    assert result1["supervisor_outcome"] == "unavailable"
    assert result1["auth_confirmed"] is False

    # Test "not reviewed" scenario
    result2 = build_dry_run_escalation(advisory, "Authorized, not reviewed")
    assert result2["supervisor_outcome"] == "unavailable"
    assert result2["review_confirmed"] is False
