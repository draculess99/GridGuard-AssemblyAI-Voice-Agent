import streamlit as st
from dotenv import load_dotenv

# Load env before imports
load_dotenv()

from backend.assemblyai_integration import is_mock_mode, mock_transcribe_audio
from backend.audio_input import STATUS_ERROR, STATUS_NETWORK_BLOCKED, handle_audio_input
from backend.audit import save_audit_packet
from backend.conversation import generate_conversation_timeline
from backend.incident import build_synthetic_incident_record

st.set_page_config(page_title="GridGuard Voice Escalation", page_icon="⚡", layout="wide")

st.markdown("""
<style>
/* Readability-only presentation styles for the transcript and status context. */
div[data-testid="stTextArea"] textarea[disabled] {
    background: #0f172a !important;
    border: 1px solid #334155 !important;
    border-radius: 0.45rem;
    color: #F1F5F9 !important;
    font-size: 1.15rem !important;
    line-height: 1.6 !important;
    opacity: 1 !important;
    padding: 0.8rem 0.9rem !important;
}

.incident-source {
    color: #E2E8F0;
    font-size: 1.08rem;
    line-height: 1.5;
    margin: 0.25rem 0 0.6rem;
}

.incident-source-badge {
    background: #164e63;
    border: 1px solid #38bdf8;
    border-radius: 0.35rem;
    color: #F1F5F9;
    display: inline-block;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.98rem;
    font-weight: 700;
    padding: 0.1rem 0.4rem;
}

/* Streamlit's success alert remains green; this improves its text contrast/size. */
div[data-testid="stAlert"] p {
    color: #ECFDF5;
    font-size: 1.1rem;
    line-height: 1.45;
}

@media (max-width: 640px) {
    div[data-testid="stTextArea"] textarea[disabled] {
        font-size: 1.1rem !important;
    }

    .incident-source {
        font-size: 1.05rem;
    }
}
</style>
""", unsafe_allow_html=True)

# Sidebar
st.sidebar.title("⚙️ Configuration")
mock_mode = is_mock_mode()

if mock_mode:
    st.sidebar.warning("⚠️ **Mock Mode Active**\n\nNo `ASSEMBLYAI_API_KEY` detected. The system uses mock transcription for safe offline testing.")
else:
    st.sidebar.success("✅ **Live Mode Active**\n\n`ASSEMBLYAI_API_KEY` configured. Audio will be transcribed using AssemblyAI.")

st.sidebar.markdown("---")
st.sidebar.markdown("""
**How it works:**
- **Live Mode**: Upload or record real audio for AssemblyAI transcription.
- **Mock Mode**: Upload, record, or run a sample incident. Audio is never transcribed or sent externally; a deterministic sample transcript is used.
- **Dry-Run Default**: The app will never automatically execute grid actions or place calls.
""")

st.title("⚡ GridGuard AssemblyAI Voice Agent")
st.markdown("**Explainable grid forecasting with approval-gated, inbound AssemblyAI voice transcription.**")

st.markdown("---")
st.subheader("Operational Status")
col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("Grid Risk", "Standby")
col_b.metric("Affected Asset", "None")
col_c.metric("Incident Severity", "Nominal")
col_d.metric("Human Approval", "Required")

st.markdown("---")
st.subheader("1. Audio Ingestion")

if "transcript" not in st.session_state:
    st.session_state.transcript = None
if "extracted_details" not in st.session_state:
    st.session_state.extracted_details = None
if "incident_record" not in st.session_state:
    st.session_state.incident_record = None


def store_incident(transcript: str, source: str, input_channel: str) -> None:
    record = build_synthetic_incident_record(transcript, source, input_channel)
    st.session_state.transcript = transcript
    st.session_state.incident_record = record
    st.session_state.extracted_details = record["incident_details"]
    st.session_state.executed_decision = None
    st.session_state.audit_filepath = None
    # A new incident must be reviewed afresh: clear the previous review acknowledgement and choice.
    st.session_state.review_consent = False
    st.session_state.review_decision = None


def ingest_audio(audio_bytes: bytes, suffix: str, input_channel: str) -> None:
    """Shared path for uploaded and microphone audio; ends at the same store_incident/approval gate."""
    spinner_text = "Preparing mock transcript..." if mock_mode else "Transcribing..."
    with st.spinner(spinner_text):
        result = handle_audio_input(audio_bytes, suffix, input_channel)

    if result.status == STATUS_NETWORK_BLOCKED:
        st.error(
            "AssemblyAI could not be reached over HTTPS. "
            "The API key was not rejected; the outbound connection was blocked "
            "before AssemblyAI authentication."
        )
        st.info(
            "Required network action: allow outbound TCP 443 to "
            "`api.assemblyai.com` in Windows Firewall or endpoint security, "
            "or configure the approved HTTPS proxy/VPN for this process."
        )
    elif result.status == STATUS_ERROR:
        st.error(f"AssemblyAI transcription failed: {result.detail}")
    else:
        store_incident(result.transcript, result.source, result.input_channel)

col_upload, col_sample = st.columns([2, 1])

with col_upload:
    uploaded_file = st.file_uploader("Upload incident report audio", type=['wav', 'mp3', 'm4a'])

    if uploaded_file is not None:
        if st.button("Transcribe Audio"):
            ingest_audio(uploaded_file.getvalue(), uploaded_file.name.split('.')[-1], "upload")

    st.markdown("**Or record from your microphone:**")
    if mock_mode:
        st.info(
            "Mock Mode: a microphone recording is **not transcribed** and is **not sent to "
            "AssemblyAI or any external service**. The deterministic sample transcript is used instead."
        )
    else:
        st.caption(
            "Live Mode: the recording is sent to AssemblyAI for transcription only after you "
            "click **Transcribe Recording**."
        )
    recorded_audio = st.audio_input("Record incident report")

    if recorded_audio is not None:
        if st.button("Transcribe Recording"):
            ingest_audio(recorded_audio.getvalue(), "wav", "microphone")

with col_sample:
    st.write("Or run a test scenario:")
    if st.button("Run Sample Incident"):
        with st.spinner("Generating mock transcript..."):
            transcript = mock_transcribe_audio()
            store_incident(transcript, "mock", "sample")

if st.session_state.transcript:
    st.markdown("---")
    st.subheader("2. Transcription & Extraction")
    record = st.session_state.incident_record
    st.markdown(
        f'<div class="incident-source">Synthetic incident source: '
        f'<span class="incident-source-badge">{record["source"]}</span>'
        f' &nbsp;Input channel: '
        f'<span class="incident-source-badge">{record["input_channel"]}</span></div>',
        unsafe_allow_html=True,
    )
    if record["source"] == "mock" and record["input_channel"] in ("upload", "microphone"):
        st.warning(
            f"Mock Mode: the submitted {record['input_channel']} audio was not transcribed and was "
            "not sent to any external service. The transcript below is the deterministic sample."
        )
    st.text_area("Exact raw transcript", value=record["raw_transcript"], height=180, disabled=True)
    st.caption(record["safety_note"])
    
    st.markdown("### Extracted Grid Parameters")
    details = st.session_state.extracted_details
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Location", details["location"])
    col2.metric("Severity", details["severity"])
    col3.metric("Affected Asset", details["affected_asset"])
    col4.metric("Requested Action", details["requested_action"])
    
    st.markdown("---")
    st.subheader("3. Conversation Review Panel")
    
    timeline = generate_conversation_timeline(st.session_state.transcript, details, record["source"] == "mock")
    for msg in timeline:
        speaker_icon = "👤" if msg["speaker"] == "Caller" else "🤖"
        with st.chat_message(msg["speaker"], avatar=speaker_icon):
            st.markdown(f"**{msg['speaker']}**")
            st.write(msg["text"])
            
    st.markdown("---")
    st.subheader("4. Approval State")
    if st.session_state.get('executed_decision'):
        st.markdown(f"""
        * **Caller identity:** Unconfirmed — never inferred from audio
        * **Authorization status:** Unconfirmed — synthetic demo context only
        * **Requested action:** {details.get('requested_action')}
        * **Verbal intent:** Recorded
        * **Final authorization:** Recorded human reviewer decision
        * **Decision outcome:** {st.session_state.executed_decision}
        * **Execution mode:** Dry-run recorded — no grid action executed
        * **Audit status:** Recorded successfully
        """)
    else:
        st.markdown(f"""
        * **Caller identity:** Unconfirmed — never inferred from audio
        * **Authorization status:** Unconfirmed — synthetic demo context only
        * **Requested action:** {details.get('requested_action')}
        * **Verbal intent:** Recorded
        * **Final authorization:** Pending explicit human decision
        * **Execution mode:** Dry-run only
        """)

    st.markdown("---")
    st.subheader("5. Human Approval Gate")
    st.markdown("GridGuard acts as **decision support only**. Review the incident and explicitly approve or reject.")
    
    consent = st.checkbox("I have reviewed the transcription and extraction.", key="review_consent")

    decision = st.radio("Decision Outcome:", ["Approve", "Hold", "Reject", "Escalate"], index=None, horizontal=True, key="review_decision")
    
    can_execute = consent and decision is not None
    
    if st.button("Execute Decision", disabled=not can_execute):
        with st.spinner("Saving audit packet..."):
                outcome_mapping = {
                    "Approve": "ESCALATION_APPROVED",
                    "Hold": "REVIEWED_HOLD",
                    "Reject": "REVIEWED_NOT_APPROVED",
                    "Escalate": "ESCALATION_APPROVED"
                }
                outcome_state = outcome_mapping.get(decision, "UNKNOWN")
                filepath = save_audit_packet(
                    st.session_state.incident_record,
                    decision,
                    outcome_state
                )
                st.session_state.executed_decision = decision
                st.session_state.audit_filepath = filepath
                st.rerun()
                
    if st.session_state.get('executed_decision'):
        st.success(f"Decision '{st.session_state.executed_decision}' recorded successfully! Audit saved to `{st.session_state.get('audit_filepath')}`.")
        st.info("Note: GridGuard never executes grid actions or contacts anyone automatically.")
