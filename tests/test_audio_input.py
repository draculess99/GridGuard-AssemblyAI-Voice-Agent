"""Offline tests for the shared upload/microphone ingest handler."""

import pytest

import backend.assemblyai_integration as assemblyai_integration
from backend.audio_input import (
    STATUS_ERROR,
    STATUS_NETWORK_BLOCKED,
    STATUS_OK,
    handle_audio_input,
)


def test_rejects_unknown_input_channel():
    with pytest.raises(ValueError):
        handle_audio_input(b"fake-audio-bytes", "wav", "carrier_pigeon")


def test_rejects_empty_audio_for_every_known_channel():
    for channel in ("upload", "microphone"):
        result = handle_audio_input(b"", "wav", channel)
        assert result.status == STATUS_ERROR
        assert result.input_channel == channel
        assert result.transcript is None


def test_mock_mode_never_touches_disk_or_network_for_microphone(monkeypatch):
    # In Mock Mode there is no API key, so is_mock_mode() is True and the audio
    # bytes must never reach transcribe_audio / the filesystem / AssemblyAI.
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("transcribe_audio must not be called in Mock Mode")

    monkeypatch.setattr(assemblyai_integration, "transcribe_audio", fail_if_called)

    result = handle_audio_input(b"fake-microphone-bytes", "wav", "microphone")

    assert result.status == STATUS_OK
    assert result.source == "mock"
    assert result.input_channel == "microphone"
    assert result.transcript == assemblyai_integration.mock_transcribe_audio()


def test_mock_mode_never_touches_disk_or_network_for_upload(monkeypatch):
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("transcribe_audio must not be called in Mock Mode")

    monkeypatch.setattr(assemblyai_integration, "transcribe_audio", fail_if_called)

    result = handle_audio_input(b"fake-upload-bytes", "mp3", "upload")

    assert result.status == STATUS_OK
    assert result.source == "mock"
    assert result.input_channel == "upload"


def test_live_mode_success_tags_microphone_channel(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "backend.audio_input.transcribe_audio", lambda path: "A real live transcript."
    )

    result = handle_audio_input(b"fake-microphone-bytes", "wav", "microphone")

    assert result.status == STATUS_OK
    assert result.source == "assemblyai_live"
    assert result.input_channel == "microphone"
    assert result.transcript == "A real live transcript."


def test_live_mode_network_blocked_is_surfaced_without_leaking_key(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "backend.audio_input.transcribe_audio",
        lambda path: "NETWORK_BLOCKED: Unable to establish the HTTPS connection.",
    )

    result = handle_audio_input(b"fake-microphone-bytes", "wav", "microphone")

    assert result.status == STATUS_NETWORK_BLOCKED
    assert "test-key" not in result.detail


def test_live_mode_transcription_error_is_surfaced(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "backend.audio_input.transcribe_audio", lambda path: "Error: invalid audio"
    )

    result = handle_audio_input(b"fake-upload-bytes", "wav", "upload")

    assert result.status == STATUS_ERROR
    assert result.detail == "Error: invalid audio"


def test_unrecognized_suffix_falls_back_to_wav(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-key")
    seen_paths = []

    def fake_transcribe(path):
        seen_paths.append(path)
        return "Transcribed."

    monkeypatch.setattr("backend.audio_input.transcribe_audio", fake_transcribe)

    result = handle_audio_input(b"fake-bytes", "exe", "upload")

    assert result.status == STATUS_OK
    assert seen_paths[0].endswith(".wav")
