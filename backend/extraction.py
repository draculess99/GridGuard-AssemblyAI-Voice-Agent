from typing import Dict

def extract_incident_details(transcript: str) -> Dict[str, str]:
    """
    Extracts incident location, severity, affected asset, and requested action 
    from the transcript using keyword/regex heuristics for the MVP.
    """
    transcript_lower = transcript.lower()
    
    # 1. Location
    location = "Unknown"
    locations = ["substation alpha", "north grid", "south sector", "downtown", "main plant"]
    for loc in locations:
        if loc in transcript_lower:
            location = loc.title()
            break
            
    # 2. Severity
    severity = "Low"
    if any(word in transcript_lower for word in ["critical", "severe", "emergency", "fatal"]):
        severity = "Critical"
    elif any(word in transcript_lower for word in ["elevated", "high", "warning"]):
        severity = "High"
        
    # 3. Affected Asset
    asset = "Unknown"
    assets = ["transformer", "thermal overload", "transmission line", "generator", "relay"]
    for a in assets:
        if a in transcript_lower:
            asset = a.title()
            break
            
    # 4. Requested Action
    action = "Monitor situation"
    if "deploy" in transcript_lower or "send" in transcript_lower or "crews" in transcript_lower:
        action = "Deploy emergency crews"
    elif "shutdown" in transcript_lower or "disconnect" in transcript_lower:
        action = "Shutdown affected systems"
        
    return {
        "location": location,
        "severity": severity,
        "affected_asset": asset,
        "requested_action": action
    }
