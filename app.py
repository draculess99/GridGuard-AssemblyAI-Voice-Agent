import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

# Load env before imports
load_dotenv()

from backend.assemblyai_integration import is_mock_mode, mock_transcribe_audio
from backend.audio_input import STATUS_ERROR, STATUS_NETWORK_BLOCKED, handle_audio_input
from backend.audit import save_audit_packet
from backend.call_e_adapter import build_advisory, build_dry_run_escalation, DRY_RUN_SCENARIOS
from backend.conversation import generate_conversation_timeline
from backend.incident import build_synthetic_incident_record

st.set_page_config(page_title="GridGuard Voice Escalation", page_icon="⚡", layout="wide")


def render_spoken_message(label: str, text: str, key: str) -> None:
    """Render a browser-based text-to-speech button using Web Speech API.

    The speech is generated locally by the browser and plays only after user clicks.
    No external service or API key is used.
    """
    escaped_text = text.replace('\\', '\\\\').replace('"', '\\"')
    html_code = f"""
    <div style="margin: 1rem 0;">
        <button
            id="speak_btn_{key}"
            onclick="window.speakText_{key}()"
            style="
                background-color: #1f2937;
                border: 1px solid #4b5563;
                border-radius: 0.375rem;
                color: #e5e7eb;
                cursor: pointer;
                font-size: 0.95rem;
                padding: 0.5rem 1rem;
                transition: all 0.2s;
                font-weight: 500;
            "
            onmouseover="this.style.backgroundColor='#374151'; this.style.borderColor='#6b7280';"
            onmouseout="this.style.backgroundColor='#1f2937'; this.style.borderColor='#4b5563';"
        >
            🔊 {label}
        </button>
    </div>
    <script>
        window.speakText_{key} = function() {{
            const text = "{escaped_text}";
            if ('speechSynthesis' in window) {{
                window.speechSynthesis.cancel();
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.rate = 1.0;
                utterance.pitch = 1.0;
                utterance.volume = 1.0;
                window.speechSynthesis.speak(utterance);
            }} else {{
                console.log('Speech Synthesis API not supported');
            }}
        }};
    </script>
    """
    components.html(html_code, height=80)

st.markdown("""
<style>
/* Readability-only presentation styles for the transcript and status context. */
div[data-testid="stTextArea"] textarea[disabled] {
    background: #0f172a !important;
    border: 1px solid #334155 !important;
    border-radius: 0.45rem;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
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
    # Clear any previous Call-E escalation state
    st.session_state.escalation_result = None
    st.session_state.escalation_scenario_executed = None
    st.session_state.escalation_consent = False
    st.session_state.escalation_audit_saved = False


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
    st.subheader("Operator Briefing")
    briefing_text = (
        f"GridGuard briefing. Severity: {details['severity']}. "
        f"Location: {details['location']}. "
        f"Affected asset: {details['affected_asset']}. "
        f"Requested action: {details['requested_action']}. "
        f"Please review the extracted details before selecting a decision."
    )
    render_spoken_message("Speak operator briefing", briefing_text, "briefing")
    st.caption("🎙️ Browser speech demo only. Spoken playback is generated locally by the browser and is not an AssemblyAI service.")

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

    # Outcome mapping for audit consistency (available to both decision execution and Call-E result save)
    outcome_mapping = {
        "Approve": "ESCALATION_APPROVED",
        "Hold": "REVIEWED_HOLD",
        "Reject": "REVIEWED_NOT_APPROVED",
        "Escalate": "ESCALATION_APPROVED"
    }

    consent = st.checkbox("I have reviewed the transcription and extraction.", key="review_consent")

    decision = st.radio("Decision Outcome:", ["Approve", "Hold", "Reject", "Escalate"], index=None, horizontal=True, key="review_decision")

    can_execute = consent and decision is not None

    if st.button("Execute Decision", disabled=not can_execute):
        with st.spinner("Saving audit packet..."):
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

        decision_confirmation = (
            f"Decision recorded: {st.session_state.executed_decision}. "
            f"This workflow remains a simulated dry run. "
            f"No real grid action, telephone call, or external escalation has occurred."
        )
        render_spoken_message("Speak decision confirmation", decision_confirmation, "decision_confirm")
        st.caption("🎙️ Browser speech demo only. Spoken playback is generated locally by the browser and is not an AssemblyAI service.")

        # Show Call-E escalation controls only if decision was "Escalate"
        if st.session_state.executed_decision == "Escalate":
            st.markdown("---")
            st.subheader("6. Simulated Call‑E Supervisor Escalation")

            with st.container(border=True):
                st.markdown("#### 🔔 Call‑E Simulation Disclosure")
                st.warning(
                    "⚠️ **This is a simulated dry-run.** No real call will be placed. "
                    "Call‑E is an AI voice agent. Supervisor identity and approval are simulated outcomes only."
                )
                st.info(
                    "This simulation demonstrates how GridGuard would escalate to an authorized supervisor "
                    "for review and approval. The supervisor's authorization and decision are mocked for demonstration."
                )

                # Scenario selector
                st.markdown("#### Choose a simulated outcome:")
                selected_scenario = st.selectbox(
                    "Supervisor response scenario (dry-run only):",
                    DRY_RUN_SCENARIOS,
                    index=0,
                    key="escalation_scenario"
                )

                # Scenario preview speech
                def build_scenario_preview_text(scenario: str) -> str:
                    """Build preview text based on selected scenario."""
                    if scenario == "Authorized, reviewed, approve":
                        return "Selected simulated scenario: authorized supervisor, evidence reviewed, escalation approved. This is a dry-run preview only. No call has been placed and no action has been executed."
                    elif scenario == "Authorized, reviewed, reject":
                        return "Selected simulated scenario: authorized supervisor, evidence reviewed, escalation denied. This is a dry-run preview only. No call has been placed and no action has been executed."
                    elif scenario == "Not authorized / wrong person":
                        return "Selected simulated scenario: supervisor not authorized or wrong person contacted. This is a dry-run preview only. No call has been placed and no action has been executed."
                    elif scenario == "Authorized, not reviewed":
                        return "Selected simulated scenario: authorized supervisor, but evidence was not reviewed. This is a dry-run preview only. No call has been placed and no action has been executed."
                    elif scenario == "Call-E execution failure":
                        return "Selected simulated scenario: Call-E execution failed due to a technical error. This is a dry-run preview only. No call has been placed and no action has been executed."
                    else:
                        return "Selected simulated scenario. This is a dry-run preview only. No call has been placed and no action has been executed."

                preview_text = build_scenario_preview_text(selected_scenario)
                render_spoken_message("Preview selected scenario", preview_text, "scenario_preview")

                # Second confirmation
                st.markdown("#### Final confirmation:")
                escalation_consent = st.checkbox(
                    "I understand this is a dry-run simulation with no real call or grid action.",
                    key="escalation_consent"
                )

                if st.button(
                    "Run Simulated Supervisor Escalation",
                    disabled=not escalation_consent,
                    type="primary"
                ):
                    with st.spinner("Running Call‑E dry-run simulation..."):
                        advisory = build_advisory(st.session_state.incident_record)
                        escalation_result = build_dry_run_escalation(advisory, selected_scenario)
                        st.session_state.escalation_result = escalation_result
                        st.session_state.escalation_scenario_executed = selected_scenario
                    st.rerun()

            # Display escalation result if available
            if st.session_state.get('escalation_result'):
                st.markdown("---")
                st.subheader("7. Supervisor Escalation Result")

                result = st.session_state.escalation_result
                final_status = result.get("final_status", "UNKNOWN")
                supervisor_outcome = result.get("supervisor_outcome", "unknown").lower()

                # Status-based rendering with canonical supervisor outcome
                if supervisor_outcome == "approved":
                    st.success("APPROVED: Supervisor authorized and approved escalation")
                    st.markdown(f"**Workflow result:** {result.get('workflow_result_text', 'Approved')}")
                    st.info("Escalation package would be created with the incident details and supervisor approval.")
                elif supervisor_outcome == "denied":
                    st.warning("DENIED: Supervisor authorized but denied escalation")
                    st.markdown(f"**Workflow result:** {result.get('workflow_result_text', 'Denied')}")
                elif supervisor_outcome == "unavailable":
                    st.error("UNAVAILABLE: Supervisor not available or not authorized")
                    st.markdown(f"**Workflow result:** {result.get('workflow_result_text', 'Not available')}")
                elif supervisor_outcome == "failed":
                    st.error("FAILED: Call-E execution failed")
                    st.markdown(f"**Error:** {result.get('error_message', 'Call could not be completed')}")
                    st.markdown(f"**Workflow result:** {result.get('workflow_result_text', 'Execution failed')}")
                    st.warning("No supervisor response received. Manual escalation may be required.")
                else:
                    st.warning("UNCLEAR: Unable to interpret supervisor response")
                    st.markdown(f"**Workflow result:** {result.get('workflow_result_text', 'Manual follow-up needed')}")

                # Display result details with canonical outcome
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Auth Confirmed", "Yes" if result.get("auth_confirmed") else ("No" if result.get("auth_confirmed") is False else "Unknown"))
                col2.metric("Review Confirmed", "Yes" if result.get("review_confirmed") else ("No" if result.get("review_confirmed") is False else "Unknown"))
                col3.metric("Supervisor Outcome", supervisor_outcome.capitalize())
                col4.metric("Mode", "Dry-run")

                # Show transcript
                st.markdown("#### Simulated Call Transcript:")
                st.text(result.get("transcript_summary", "No transcript"))

                # Update audit with escalation result
                with st.container(border=True):
                    st.markdown("#### Audit Update")
                    if st.button("Save escalation result to audit packet", key="save_escalation_audit"):
                        audit_filepath = save_audit_packet(
                            st.session_state.incident_record,
                            st.session_state.executed_decision,
                            outcome_mapping.get(st.session_state.executed_decision, "UNKNOWN"),
                            escalation_result=result
                        )
                        st.session_state.escalation_audit_saved = True
                        st.success(f"Escalation result recorded in audit: `{audit_filepath}`")
                        st.info("The audit packet now includes both the operator decision and the simulated supervisor response.")

                if st.session_state.get('escalation_audit_saved'):
                    auth_confirmed = result.get("auth_confirmed")
                    review_confirmed = result.get("review_confirmed")
                    supervisor_outcome_lower = result.get("supervisor_outcome", "unknown").lower()
                    workflow_result = result.get("workflow_result_text", "Unknown")

                    auth_text = "Supervisor authorization was confirmed." if auth_confirmed else ("Supervisor authorization was not confirmed." if auth_confirmed is False else "Supervisor authorization status is unknown.")
                    review_text = "Supervisor review was confirmed." if review_confirmed else ("Supervisor review was not confirmed." if review_confirmed is False else "Supervisor review status is unknown.")

                    if supervisor_outcome_lower == "approved":
                        outcome_text = "The supervisor approved escalation."
                    elif supervisor_outcome_lower == "denied":
                        outcome_text = "The supervisor denied escalation."
                    elif supervisor_outcome_lower == "unavailable":
                        outcome_text = "The supervisor was unavailable or not authorized."
                    elif supervisor_outcome_lower == "failed":
                        outcome_text = "Escalation simulation failed due to a technical error."
                    else:
                        outcome_text = "The supervisor outcome could not be determined."

                    audited_outcome_text = (
                        f"Dry-run escalation complete. {auth_text} {review_text} {outcome_text} "
                        f"{workflow_result}. The audit packet has been saved. No real call was placed."
                    )
                    render_spoken_message("Speak audited outcome", audited_outcome_text, "audited_outcome")
                    st.caption("🎙️ Browser speech demo only. Spoken playback is generated locally by the browser and is not an AssemblyAI service.")
