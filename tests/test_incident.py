import json
import os
from tempfile import TemporaryDirectory

import backend.assemblyai_integration as assemblyai_integration
import httpx
import pytest
from backend.extraction import extract_incident_details
from backend.incident import build_synthetic_incident_record


def test_extraction_uses_unknown_for_unsupported_fields():
    assert extract_incident_details("An operator reports an issue.") == {
        "location": "Unknown",
        "severity": "Unknown",
        "affected_asset": "Unknown",
        "requested_action": "Unknown",
    }


def test_live_record_uses_exact_transcript_and_unconfirmed_authority():
    transcript = "Substation Alpha reports a critical transformer issue. Send crews."
    record = build_synthetic_incident_record(transcript, "assemblyai_live")

    assert record["source"] == "assemblyai_live"
    assert record["raw_transcript"] == transcript
    assert record["incident_id"] == build_synthetic_incident_record(transcript, "assemblyai_live")["incident_id"]
    assert record["caller_identity"] == "Unconfirmed"
    assert record["authorization_status"] == "Unconfirmed"
    assert record["approval_authority"] == "Unconfirmed"


def test_live_audit_packet_has_required_schema():
    record = build_synthetic_incident_record("A live transcript.", "assemblyai_live", "upload")
    from backend.audit import save_audit_packet

    with TemporaryDirectory(dir=os.getcwd()) as audit_dir:
        filepath = save_audit_packet(record, "Hold", "REVIEWED_HOLD", audit_dir)
        with open(filepath, encoding="utf-8") as file_handle:
            packet = json.load(file_handle)

    assert packet["timestamp"].endswith("Z")
    assert packet["structured_incident_record"] == record
    assert packet["provenance"] == {"source": "assemblyai_live", "input_channel": "upload"}
    assert packet["reviewer_decision"] == "Hold"
    assert packet["dry_run"] is True


def test_input_channel_defaults_to_unspecified_and_is_validated():
    record = build_synthetic_incident_record("Some transcript.", "mock")
    assert record["input_channel"] == "unspecified"

    for channel in ("upload", "microphone", "sample"):
        record = build_synthetic_incident_record("Some transcript.", "mock", channel)
        assert record["input_channel"] == channel

    with pytest.raises(ValueError):
        build_synthetic_incident_record("Some transcript.", "mock", "carrier_pigeon")


def test_invalid_source_still_rejected_regardless_of_channel():
    with pytest.raises(ValueError):
        build_synthetic_incident_record("Some transcript.", "bogus_source", "upload")


def test_transcription_error_is_offline_testable(monkeypatch):
    class FakeTranscript:
        error = "invalid audio"
        text = None

    class FakeTranscriber:
        def transcribe(self, file_path):
            assert file_path == "sample.wav"
            return FakeTranscript()

    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(assemblyai_integration.aai, "Transcriber", FakeTranscriber)

    assert assemblyai_integration.transcribe_audio("sample.wav") == "Error: invalid audio"


def test_connect_error_explains_pre_authentication_network_block(monkeypatch):
    class FakeTranscriber:
        def transcribe(self, file_path):
            raise httpx.ConnectError("[WinError 10013] socket access forbidden")

    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(assemblyai_integration.aai, "Transcriber", FakeTranscriber)

    result = assemblyai_integration.transcribe_audio("sample.wav")

    assert result.startswith("NETWORK_BLOCKED:")
    assert "API key was not rejected" in result
    assert "outbound TCP 443" in result
    assert "test-key" not in result


def test_proxy_error_uses_same_safe_network_message(monkeypatch):
    class FakeTranscriber:
        def transcribe(self, file_path):
            raise httpx.ProxyError("proxy refused connection")

    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(assemblyai_integration.aai, "Transcriber", FakeTranscriber)

    result = assemblyai_integration.transcribe_audio("sample.wav")

    assert result.startswith("NETWORK_BLOCKED:")
    assert "API key was not rejected" in result
