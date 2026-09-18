import os
import assemblyai as aai

def get_api_key():
    return os.environ.get("ASSEMBLYAI_API_KEY")

def is_mock_mode():
    return not bool(get_api_key())

def transcribe_audio(file_path: str) -> str:
    api_key = get_api_key()
    if not api_key:
        return mock_transcribe_audio()
    
    aai.settings.api_key = api_key
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(file_path)
    
    if transcript.error:
        return f"Error: {transcript.error}"
    
    return transcript.text

def mock_transcribe_audio() -> str:
    return "This is a mock transcription of a critical grid incident. The Substation Alpha is experiencing a severe thermal overload and we need to deploy emergency crews immediately to prevent cascading failures."
