import streamlit as st
import tempfile
import os
from dotenv import load_dotenv

# Load env before imports
load_dotenv()

from backend.assemblyai_integration import transcribe_audio, is_mock_mode, mock_transcribe_audio
from backend.extraction import extract_incident_details
from backend.audit import save_audit_packet
from backend.conversation import generate_conversation_timeline

st.set_page_config(page_title="GridGuard Voice Escalation", page_icon="⚡", layout="wide")

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
- **Live Mode**: Upload real audio files for AssemblyAI transcription.
- **Mock Mode**: Run a sample incident to see how the system parses details and handles safety gates.
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

col_upload, col_sample = st.columns([2, 1])

with col_upload:
    uploaded_file = st.file_uploader("Upload incident report audio", type=['wav', 'mp3', 'm4a'])

    if uploaded_file is not None:
        if st.button("Transcribe Audio"):
            with st.spinner("Transcribing..."):
                # Save uploaded file to temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name
                    
                transcript = transcribe_audio(tmp_path)
                st.session_state.transcript = transcript
                st.session_state.extracted_details = extract_incident_details(transcript)
                
                # Clean up temp file
                os.remove(tmp_path)

with col_sample:
    st.write("Or run a test scenario:")
    if st.button("Run Sample Incident"):
        with st.spinner("Generating mock transcript..."):
            transcript = mock_transcribe_audio()
            st.session_state.transcript = transcript
            st.session_state.extracted_details = extract_incident_details(transcript)

if st.session_state.transcript:
    st.markdown("---")
    st.subheader("2. Transcription & Extraction")
    st.info(f"**Transcript:**\n\n{st.session_state.transcript}")
    
    st.markdown("### Extracted Grid Parameters")
    details = st.session_state.extracted_details
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Location", details["location"])
    col2.metric("Severity", details["severity"])
    col3.metric("Affected Asset", details["affected_asset"])
    col4.metric("Requested Action", details["requested_action"])
    
    st.markdown("---")
    st.subheader("3. Conversation Review Panel")
    
    timeline = generate_conversation_timeline(st.session_state.transcript, details, mock_mode)
    for msg in timeline:
        speaker_icon = "👤" if msg["speaker"] == "Caller" else "🤖"
        with st.chat_message(msg["speaker"], avatar=speaker_icon):
            st.markdown(f"**{msg['speaker']}**")
            st.write(msg["text"])
            
    st.markdown("---")
    st.subheader("4. Approval State")
    if st.session_state.get('executed_decision'):
        st.markdown(f"""
        * **Caller identity:** Demo directory matched
        * **Caller role:** Operations Supervisor
        * **Requested action:** {details.get('requested_action')}
        * **Verbal intent:** Recorded
        * **Final authorization:** Approved by human reviewer
        * **Decision outcome:** {st.session_state.executed_decision}
        * **Execution mode:** Dry-run recorded — no grid action executed
        * **Audit status:** Recorded successfully
        """)
    else:
        st.markdown(f"""
        * **Caller identity:** Demo directory matched
        * **Caller role:** Operations Supervisor
        * **Requested action:** {details.get('requested_action')}
        * **Verbal intent:** Recorded
        * **Final authorization:** Pending explicit human decision
        * **Execution mode:** Dry-run only
        """)

    st.markdown("---")
    st.subheader("5. Human Approval Gate")
    st.markdown("GridGuard acts as **decision support only**. Review the incident and explicitly approve or reject.")
    
    consent = st.checkbox("I have reviewed the transcription and extraction.")
    
    decision = st.radio("Decision Outcome:", ["Approve", "Hold", "Reject", "Escalate"], index=None, horizontal=True)
    
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
                    st.session_state.transcript,
                    st.session_state.extracted_details,
                    decision,
                    outcome_state
                )
                st.session_state.executed_decision = decision
                st.session_state.audit_filepath = filepath
                st.rerun()
                
    if st.session_state.get('executed_decision'):
        st.success(f"Decision '{st.session_state.executed_decision}' recorded successfully! Audit saved to `{st.session_state.get('audit_filepath')}`.")
        st.info("Note: GridGuard never executes grid actions or contacts anyone automatically.")
