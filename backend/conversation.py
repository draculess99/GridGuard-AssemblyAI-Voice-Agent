from typing import List, Dict

def generate_conversation_timeline(transcript: str, details: Dict[str, str], is_mock: bool) -> List[Dict[str, str]]:
    timeline = []
    
    if is_mock:
        caller_part1 = "This is Jordan Lee, Operations Supervisor for Substation Alpha. We have a critical thermal overload."
        caller_part2 = "My operator identifier is OPS-4721. I am requesting emergency crew dispatch."
    else:
        caller_part1 = transcript
        caller_part2 = "My operator identifier is OPS-4721. I am requesting emergency crew dispatch."
        
    timeline.append({"speaker": "Caller", "text": caller_part1})
    
    timeline.append({"speaker": "GridGuard Voice Agent", "text": "Incident recorded. For this demonstration, please provide your operator identifier for authorization lookup."})
    
    timeline.append({"speaker": "Caller", "text": caller_part2})
    
    timeline.append({"speaker": "GridGuard Authorization Service", "text": "Demo directory match: Jordan Lee — Operations Supervisor. Dispatch authority: eligible for emergency crew recommendation.\n\n*Demo authorization lookup — not biometric or voice authentication.*"})
    
    action = details.get('requested_action', 'Unknown').lower()
    agent_summary = f"I have extracted: {details.get('severity', 'Unknown')} severity, {details.get('location', 'Unknown')}, {details.get('affected_asset', 'Unknown').lower()}, and a request to {action}. GridGuard provides decision support only and will not dispatch anyone automatically."
    timeline.append({"speaker": "GridGuard Voice Agent", "text": agent_summary})
    
    timeline.append({"speaker": "Caller", "text": "I have reviewed the recommendation and request approval to proceed with the documented dry-run decision."})
    
    timeline.append({"speaker": "GridGuard Voice Agent", "text": "Verbal intent recorded. A human reviewer must still explicitly select and execute the final decision below."})
    
    return timeline
