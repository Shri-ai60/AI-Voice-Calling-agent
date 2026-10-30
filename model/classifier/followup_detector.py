import re
import os
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, UTC
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Complete system prompt provided by specification
FOLLOWUP_SYSTEM_PROMPT = """You are responsible for detecting whether a voice call requires a follow-up.

Listen to the complete conversation and identify the client's actual situation. The client may speak in English, Hindi, Hinglish, Marathi, or mixed languages. Understand the meaning even when the grammar is incorrect, informal, short, unclear, or colloquial.

### IMPORTANT OUTPUT RULE

If a follow-up condition is detected, return ONLY the corresponding number.

Do NOT return:
* explanations
* sentences
* reason names
* JSON
* extra text
* punctuation

Example:
1

### FOLLOW-UP CATEGORIES

1 — CLIENT NOT AVAILABLE / BUSY
2 — PHONE / LINE BUSY
3 — CALL NOT ANSWERED / NO RESPONSE
4 — CALL DISCONNECTED WITHOUT ANSWER / CONVERSATION
5 — CLIENT VOICE UNCLEAR / NOT AUDIBLE
6 — NETWORK / CONNECTION ISSUE
7 — CLIENT ASKS TO CALL LATER
8 — SPECIFIC CALLBACK TIME GIVEN
9 — CLIENT DRIVING / OUTSIDE / TEMPORARILY UNAVAILABLE
10 — CLIENT IN MEETING / CLASS / OCCUPIED
11 — CLIENT CANNOT TALK NOW
12 — CLIENT REQUESTS CALL BACK LATER
13 — CLIENT REQUESTS TOMORROW / NEXT DAY
14 — CLIENT REQUESTS AFTER SOME TIME
15 — CLIENT REQUESTS WHATSAPP / MESSAGE
16 — CLIENT REQUESTS ANOTHER NUMBER / PERSON
17 — CLIENT CANNOT HEAR AGENT
18 — AGENT CANNOT UNDERSTAND CLIENT
19 — WRONG / INVALID NUMBER
20 — CLIENT DOES NOT WANT TO TALK NOW
21 — PERSONAL / WORK REASON FOR UNAVAILABILITY
22 — LANGUAGE / COMMUNICATION DIFFICULTY
23 — CALL DROPPING REPEATEDLY
24 — CLIENT ANSWERS BUT REMAINS SILENT
25 — VOICEMAIL / AUTOMATED RESPONSE

### PRIORITY RULES
If multiple conditions appear, select the condition that best describes the actual reason the conversation could not be completed.
Specific callback instructions have higher priority than generic unavailability.
For example:
Client: "Abhi busy hoon, kal 5 baje call karna." -> 8
Client: "Abhi busy hoon, baad mein call karna." -> 7
Client: "Awaaz clear nahi aa rahi, network problem hai." (unclear audio primary -> 5, connection failure primary -> 6)
If the client simply says "Hello" and immediately disconnects -> 4
If the client answers but remains silent -> 24

### FINAL OUTPUT
Return ONLY ONE NUMBER from 1 to 25 when a follow-up condition is detected.
Never return the explanation.
"""

FOLLOWUP_CATEGORIES: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "CLIENT NOT AVAILABLE / BUSY",
        "description": "Client indicates that they are currently unavailable or busy.",
        "requires_followup": True,
        "default_delay_minutes": 120,
        "action": "Schedule callback in 2 hours",
    },
    2: {
        "name": "PHONE / LINE BUSY",
        "description": "Phone line itself is busy or call encounters a busy signal.",
        "requires_followup": True,
        "default_delay_minutes": 30,
        "action": "Retry call after 30 minutes",
    },
    3: {
        "name": "CALL NOT ANSWERED / NO RESPONSE",
        "description": "Call was not answered or nobody responded.",
        "requires_followup": True,
        "default_delay_minutes": 60,
        "action": "Retry call in 1 hour",
    },
    4: {
        "name": "CALL DISCONNECTED WITHOUT ANSWER / CONVERSATION",
        "description": "Call ended or disconnected before a meaningful conversation happened.",
        "requires_followup": True,
        "default_delay_minutes": 45,
        "action": "Retry call in 45 minutes",
    },
    5: {
        "name": "CLIENT VOICE UNCLEAR / NOT AUDIBLE",
        "description": "Client's voice cannot be clearly understood because of audio quality, low volume, disturbance, or unclear speech.",
        "requires_followup": True,
        "default_delay_minutes": 60,
        "action": "Check line quality and call back in 1 hour",
    },
    6: {
        "name": "NETWORK / CONNECTION ISSUE",
        "description": "Conversation affected by network, signal, or internet connection problems.",
        "requires_followup": True,
        "default_delay_minutes": 60,
        "action": "Retry call when network stabilizes",
    },
    7: {
        "name": "CLIENT ASKS TO CALL LATER",
        "description": "Client generally asks for a later call without giving a specific time.",
        "requires_followup": True,
        "default_delay_minutes": 180,
        "action": "Callback scheduled for later today",
    },
    8: {
        "name": "SPECIFIC CALLBACK TIME GIVEN",
        "description": "Client provides a specific time, day, or period for calling back.",
        "requires_followup": True,
        "default_delay_minutes": 240,
        "action": "Schedule callback at the exact requested time",
    },
    9: {
        "name": "CLIENT DRIVING / OUTSIDE / TEMPORARILY UNAVAILABLE",
        "description": "Client is driving, travelling, outside, or temporarily unable to talk.",
        "requires_followup": True,
        "default_delay_minutes": 120,
        "action": "Schedule callback in 2 hours once client is safe/available",
    },
    10: {
        "name": "CLIENT IN MEETING / CLASS / OCCUPIED",
        "description": "Client is in a meeting, class, office work, or lecture.",
        "requires_followup": True,
        "default_delay_minutes": 120,
        "action": "Schedule callback in 2 hours after meeting concludes",
    },
    11: {
        "name": "CLIENT CANNOT TALK NOW",
        "description": "Client directly states they cannot talk right now without giving busy detail.",
        "requires_followup": True,
        "default_delay_minutes": 180,
        "action": "Schedule callback later today",
    },
    12: {
        "name": "CLIENT REQUESTS CALL BACK LATER",
        "description": "Client specifically requests another phone call later.",
        "requires_followup": True,
        "default_delay_minutes": 180,
        "action": "Schedule callback later today",
    },
    13: {
        "name": "CLIENT REQUESTS TOMORROW / NEXT DAY",
        "description": "Client specifically asks to be contacted tomorrow / next day.",
        "requires_followup": True,
        "default_delay_minutes": 1440,  # 24 hours
        "action": "Schedule callback for tomorrow",
    },
    14: {
        "name": "CLIENT REQUESTS AFTER SOME TIME",
        "description": "Client asks for a short waiting period (10-30 mins or 1 hour).",
        "requires_followup": True,
        "default_delay_minutes": 30,
        "action": "Schedule callback in 30 minutes",
    },
    15: {
        "name": "CLIENT REQUESTS WHATSAPP / MESSAGE",
        "description": "Client asks agent to send details on WhatsApp, SMS, or message.",
        "requires_followup": True,
        "default_delay_minutes": 10,
        "action": "Send WhatsApp / SMS brochure and details",
    },
    16: {
        "name": "CLIENT REQUESTS ANOTHER NUMBER / PERSON",
        "description": "Client asks to call another phone number or another person (brother, sir, etc.).",
        "requires_followup": True,
        "default_delay_minutes": 60,
        "action": "Contact alternate number / designated person",
    },
    17: {
        "name": "CLIENT CANNOT HEAR AGENT",
        "description": "Client explicitly states they cannot hear the agent.",
        "requires_followup": True,
        "default_delay_minutes": 30,
        "action": "Retry call with clearer telephony route",
    },
    18: {
        "name": "AGENT CANNOT UNDERSTAND CLIENT",
        "description": "Client speech is audible but not comprehensible, requiring repetition.",
        "requires_followup": True,
        "default_delay_minutes": 60,
        "action": "Follow up with human agent or message",
    },
    19: {
        "name": "WRONG / INVALID NUMBER",
        "description": "Number is wrong, invalid, or reaches the wrong person.",
        "requires_followup": False,
        "default_delay_minutes": None,
        "action": "Flag as wrong number / do not redial",
    },
    20: {
        "name": "CLIENT DOES NOT WANT TO TALK NOW",
        "description": "Client declines current talk without permanently opting out.",
        "requires_followup": True,
        "default_delay_minutes": 2880,  # 2 days
        "action": "Soft follow-up after 2 days",
    },
    21: {
        "name": "PERSONAL / WORK REASON FOR UNAVAILABILITY",
        "description": "Client gives a personal, family, home, or office reason for unavailability.",
        "requires_followup": True,
        "default_delay_minutes": 240,
        "action": "Schedule callback in 4 hours",
    },
    22: {
        "name": "LANGUAGE / COMMUNICATION DIFFICULTY",
        "description": "Communication blocked by language mismatch (e.g. wants Hindi or Marathi).",
        "requires_followup": True,
        "default_delay_minutes": 120,
        "action": "Assign agent speaking preferred language (Hindi/Marathi)",
    },
    23: {
        "name": "CALL DROPPING REPEATEDLY",
        "description": "Call repeatedly disconnects or keeps dropping.",
        "requires_followup": True,
        "default_delay_minutes": 60,
        "action": "Redial after 1 hour",
    },
    24: {
        "name": "CLIENT ANSWERS BUT REMAINS SILENT",
        "description": "Call answered but client stays silent despite attempts.",
        "requires_followup": True,
        "default_delay_minutes": 60,
        "action": "Redial in 1 hour or verify contact validity",
    },
    25: {
        "name": "VOICEMAIL / AUTOMATED RESPONSE",
        "description": "Reached voicemail, IVR, or non-human automated response.",
        "requires_followup": True,
        "default_delay_minutes": 180,
        "action": "Retry outbound call later",
    },
}


class FollowupDetectionResult(BaseModel):
    category_id: Optional[int] = Field(None, description="Category number 1 to 25, or None if no follow-up condition detected")
    name: Optional[str] = None
    description: Optional[str] = None
    requires_followup: bool = False
    action: Optional[str] = None
    suggested_delay_minutes: Optional[int] = None
    suggested_scheduled_at: Optional[str] = None
    matched_utterance: Optional[str] = None
    priority_level: int = 99


class FollowupDetector:
    """
    Multilingual Follow-Up Detection Engine.
    Evaluates call transcripts across English, Hindi, Hinglish, and Marathi,
    identifying whether a call requires a follow-up and classifying it strictly
    into categories 1 through 25 with full priority handling.
    """

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        # Category 8: Specific callback time given
        # e.g. "5 baje call karna", "shaam ko 6 baje", "kal 10 baje", "tomorrow at 5", "lunch ke baad", "2 ghante baad", "पाच वाजता फोन करा"
        self.p_cat8 = re.compile(
            r"(\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|ek|do|teen|char|paanch|chhe|saat|aath|nau|das)\s*(baje|pm|am|o'clock|ghante|hours?)\b|"
            r"(\d{1,2}|एक|दोन|तीन|चार|पाच|सहा|सात|आठ|नऊ|दहा|दस|ग्यारह|अकरा|बारा|बारह)\s*(वाजता|बजे)|"
            r"(कल|उद्या|tomorrow)\s*(सुबह|सकाळी|दुपारी|दोपहर|संध्याकाळी|शाम)?\s*(\d{1,2}|एक|दोन|तीन|चार|पाच|सहा|सात|आठ|नऊ|दहा|दस|ग्यारह|अकरा|बारा|बारह)?\s*(वाजता|बजे)?|"
            r"\b(shaam\s*ko|subah|dopahar|evening|morning|afternoon|lunch\s*ke\s*baad)\s*(call|phone|baje|\d{1,2})|"
            r"(संध्याकाळी|सकाळी|दुपारी)\s*(फोन|कॉल|\d{1,2}\s*वाजता)|"
            r"\b(\d{1,2}\s*baje\s*(call|phone|karna)?)\b)",
            re.IGNORECASE
        )

        # Category 13: Client requests tomorrow / next day
        # e.g. "kal call karna", "kal phone karna", "call me tomorrow", "udya phone kara", "उद्या फोन करा"
        self.p_cat13 = re.compile(
            r"(\b(kal\s*(call|phone|baat|batao|karna|karo)|call\s*me\s*tomorrow|tomorrow\s*(call|morning|evening)?|udya\s*(phone|call|kara))\b|"
            r"(कल\s*(कॉल|फोन|बात|सुबह|शाम|करना|करो|कर\s*सकते|आना)|उद्या\s*(फोन|कॉल|बोलूया|करा|सकाळी)))",
            re.IGNORECASE
        )

        # Category 14: Client requests after some time (minutes / short time)
        # e.g. "10 minute baad", "aadhe ghante baad", "half an hour", "thodi der baad call karo", "अर्ध्या तासाने फोन करा"
        self.p_cat14 = re.compile(
            r"(\b((\d{1,2}|ten|fifteen|twenty|thirty|dus|pandrah|bees|tees)\s*(min|minute|mins?)\s*(baad|mein|after)|"
            r"aadhe\s*ghante|half\s*an\s*hour|thodi\s*der\s*(baad|me)|kuch\s*der\s*baad|thoda\s*time\s*do|give\s*me\s*(some\s*)?time)\b|"
            r"(थोड्या\s*वेळाने|अर्ध्या\s*तासाने|काही\s*वेळानंतर))",
            re.IGNORECASE
        )

        # Category 15: Client requests WhatsApp / message
        # e.g. "whatsapp pe bhej do", "whatsapp kar do", "message kar do", "details whatsapp pe bhejo", "WhatsApp वर पाठवा"
        self.p_cat15 = re.compile(
            r"(\b(whatsapp|what\'?s\s*app|watsapp|wapp|message\s*(kar|bhej|send|karo)|sms\s*(kar|send)|whatsapp\s*(pe|par|var|me|kardo|bhejo|patwa))\b|"
            r"(व्हॉट्सअॅप|व्हॉट्सॲप|WhatsApp\s*वर|मेसेज\s*करा|माहिती\s*WhatsApp))",
            re.IGNORECASE
        )

        # Category 16: Client requests another number / person
        # e.g. "is number pe call karo", "brother ko call karo", "sir ko call karo", "dusre number pe", "दुसऱ्या नंबरवर"
        self.p_cat16 = re.compile(
            r"(\b(dusre\s*number|another\s*number|different\s*number|is\s*number\s*pe\s*call|"
            r"(brother|bhai|papa|sir|boss|friend|husband|wife|manager)\s*(ko\s*call|se\s*baat|cha\s*number))\b|"
            r"(दुसऱ्या\s*नंबरवर|त्यांना\s*फोन))",
            re.IGNORECASE
        )

        # Category 9: Driving / Outside / Travel
        # e.g. "driving kar raha", "bahar hoon", "travel kar raha", "raste mein hoon", "गाडी चालवत आहे", "मी बाहेर आहे"
        self.p_cat9 = re.compile(
            r"(\b(driving|drive\s*kar|bahar\s*hu|bahar\s*hoon|outside|travel|traveling|travelling|raste\s*mein|traffic\s*mein)\b|"
            r"(गाडी\s*चालवत|बाहेर\s*आहे|प्रवासात))",
            re.IGNORECASE
        )

        # Category 10: In meeting / class / lecture / occupied
        # e.g. "meeting mein hoon", "class mein hoon", "office meeting", "lecture", "मीटिंगमध्ये", "क्लासमध्ये"
        self.p_cat10 = re.compile(
            r"(\b(meeting\s*(mein|chal|chalu|madhe|aahe)|class\s*(mein|chal|madhe)|lecture\s*(mein|madhe)|office\s*(mein\s*kaam|meeting)|in\s*a?\s*meeting|in\s*class)\b|"
            r"(मीटिंगमध्ये|क्लासमध्ये|आत्ता\s*काम\s*चालू))",
            re.IGNORECASE
        )

        # Category 12: Client specifically requests call back later
        # e.g. "mujhe baad mein call karna", "aap baad mein call karo", "please call me later", "nantar call kara", "पुन्हा फोन करा"
        self.p_cat12 = re.compile(
            r"(\b(mujhe\s*baad\s*mein\s*call|aap\s*baad\s*mein\s*call|please\s*call\s*(me\s*)?later|nantar\s*call\s*kara)\b|"
            r"(पुन्हा\s*फोन\s*करा|नंतर\s*परत\s*फोन|बाद\s*में\s*(कॉल|फोन|करना|बात)|नंतर\s*(फोन|कॉल|करा|सांगा)|वेळ\s*नाही|टाइम\s*नाही))",
            re.IGNORECASE
        )

        # Category 7: Client asks to call later generally
        # e.g. "baad mein call karna", "later call karo", "thodi der baad", "nantar phone kara", "later baat karte", "abhi nahi baad mein"
        self.p_cat7 = re.compile(
            r"(\b(baad\s*mein\s*(call|phone|baat)|later\s*(call|phone|baat|karo)|call\s*(me\s*)?later|nantar\s*phone\s*kara|abhi\s*nahi\s*baad\s*mein)\b|"
            r"(नंतर\s*फोन|नंतर\s*बोलूया|थोड्या\s*वेळाने\s*फोन))",
            re.IGNORECASE
        )

        # Category 11: Client cannot talk now
        # e.g. "abhi baat nahi kar sakta", "can't talk right now", "abhi possible nahi hai", "आत्ता बोलता येणार नाही"
        self.p_cat11 = re.compile(
            r"(\b(abhi\s*baat\s*nahi\s*kar\s*sak|can\'?t\s*talk(\s*now|\s*right\s*now)?|cannot\s*talk|abhi\s*possible\s*nahi|not\s*possible\s*to\s*talk)\b|"
            r"(आत्ता\s*बोलू\s*शकत\s*नाही|आत्ता\s*बोलता\s*येणार))",
            re.IGNORECASE
        )

        # Category 20: Client does not want to talk now
        # e.g. "mujhe baat nahi karni", "abhi nahi baat karni", "not interested in talking right now", "आत्ता बोलायचं नाही"
        self.p_cat20 = re.compile(
            r"(\b(mujhe\s*baat\s*nahi\s*karni|abhi\s*nahi\s*baat\s*karni|not\s*interested\s*in\s*talking\s*right\s*now|don\'?t\s*want\s*to\s*talk\s*now)\b|"
            r"(आत्ता\s*बोलायचं\s*नाही|मला\s*आत्ता\s*बोलायचं\s*नाही))",
            re.IGNORECASE
        )

        # Category 21: Personal / work reason
        # e.g. "ghar pe kaam hai", "office mein kaam", "family ke saath", "bachchon ke saath", "घरच्या कामात"
        self.p_cat21 = re.compile(
            r"(\b(ghar\s*(pe|ka)\s*kaam|office\s*(ka|mein)\s*kaam|family\s*ke\s*saath|occupied\s*with\s*work|kam\s*chal\s*raha)\b|"
            r"(घरच्या\s*कामात|ऑफिसच्या\s*कामात|घरात\s*काम))",
            re.IGNORECASE
        )

        # Category 1: Client not available / busy
        # e.g. "busy hoon", "not available", "occupied", "not free", "time nahi hai", "कामात आहे", "व्यस्त आहे"
        self.p_cat1 = re.compile(
            r"(\b(busy\s*(hoon|hu|hai|ahe|aahe)|not\s*available|i\'?m\s*occupied|i\'?m\s*busy|not\s*free|time\s*nahi\s*hai|vel\s*nahi)\b|"
            r"(उपलब्ध\s*नाही|व्यस्त\s*आहे|कामात\s*आहे|वेळ\s*नाही))",
            re.IGNORECASE
        )

        # Category 17: Client cannot hear agent
        # e.g. "aapki awaaz nahi aa rahi", "mujhe aap sunai nahi de rahe", "i can't hear you", "tumcha aawaz yet nahi"
        self.p_cat17 = re.compile(
            r"(\b(aapki\s*awaaz\s*nahi\s*aa\s*rahi|aapki\s*voice\s*nahi\s*aa\s*rahi|can\'?t\s*hear\s*you|cannot\s*hear\s*you|sunai\s*nahi\s*de\s*raha|tumcha\s*aawaz\s*aiku\s*yet\s*nahi)\b|"
            r"(आवाज\s*ऐकू\s*येत\s*नाही|आवाज\s*येत\s*नाही))",
            re.IGNORECASE
        )

        # Category 5: Client voice unclear / audio disturbed
        # e.g. "voice clear nahi", "awaaz cut ho rahi", "breaking voice", "unclear voice", "आवाज तुटत आहे"
        self.p_cat5 = re.compile(
            r"(\b(voice\s*clear\s*nahi|awaaz\s*clear\s*nahi|voice\s*(is\s*)?breaking|voice\s*cut\s*ho\s*rahi|awaaz\s*cut\s*ho\s*rahi|unclear\s*voice)\b|"
            r"(आवाज\s*स्पष्ट\s*नाही|आवाज\s*स्पष्ट\s*ऐकू\s*येत\s*नाही|आवाज\s*तुटत\s*आहे|आवाज\s*नीट\s*नाही))",
            re.IGNORECASE
        )

        # Category 6: Network / connection issue
        # e.g. "network problem", "network weak", "connection problem", "नेटवर्क प्रॉब्लेम"
        self.p_cat6 = re.compile(
            r"(\b(network\s*problem|network\s*issue|network\s*weak|network\s*nahi|connection\s*problem|connection\s*issue)\b|"
            r"(नेटवर्क\s*प्रॉब्लेम|कनेक्शन\s*नीट\s*नाही))",
            re.IGNORECASE
        )

        # Category 23: Call dropping repeatedly
        # e.g. "call baar baar cut", "call disconnect ho raha", "keeps dropping"
        self.p_cat23 = re.compile(
            r"(\b(call\s*baar\s*baar\s*cut|call\s*disconnect\s*ho\s*raha|call\s*keeps\s*dropping|connection\s*baar\s*baar)\b|"
            r"(वारंवार\s*कॉल\s*कट|पुन्हा\s*पुन्हा\s*डिस्कनेक्ट))",
            re.IGNORECASE
        )

        # Category 19: Wrong / invalid number
        # e.g. "wrong number", "galat number", "wrong person", "चुकीचा नंबर"
        self.p_cat19 = re.compile(
            r"(\b(wrong\s*number|galat\s*number|wrong\s*person|not\s*this\s*person|ye\s*woh\s*person\s*nahi)\b|"
            r"(चुकीचा\s*नंबर|ही\s*व्यक्ती\s*इथे\s*नाही))",
            re.IGNORECASE
        )

        # Category 22: Language / communication difficulty
        # e.g. "english samajh nahi aati", "hindi mein baat karo", "marathi madhe bola", "मराठीत बोला"
        self.p_cat22 = re.compile(
            r"(\b(english\s*samajh\s*nahi|hindi\s*mein\s*(baat|bolo)|marathi\s*(mein|madhe)\s*bola|language\s*samajh\s*nahi)\b|"
            r"(मराठीत\s*बोला|मराठीमध्ये\s*बोला|हिंदीमध्ये\s*बोला|इंग्लिश\s*समजत\s*नाही))",
            re.IGNORECASE
        )

        # Category 25: Voicemail / IVR / Automated response
        self.p_cat25 = re.compile(
            r"\b(voicemail|leave\s*a\s*message|automated\s*response|press\s*1\s*press\s*2|ivr\s*response|call\s*is\s*being\s*forwarded|mailbox\s*is\s*full)\b",
            re.IGNORECASE
        )

        # Category 2: Phone / line busy
        self.p_cat2 = re.compile(
            r"(\b(phone\s*busy\s*hai|number\s*busy|line\s*busy|busy\s*tone)\b|"
            r"(नंबर\s*बिजी|फोन\s*व्यस्त))",
            re.IGNORECASE
        )

    def detect_category_number(self, transcript: str) -> Optional[int]:
        """
        Evaluates the transcript and returns ONLY ONE NUMBER from 1 to 25
        strictly adhering to priority rules, or None if no follow-up condition is found.
        """
        detailed = self.detect_followup_detailed(transcript)
        return detailed.category_id

    def detect_followup_detailed(self, transcript: str) -> FollowupDetectionResult:
        """
        Analyzes the call transcript and extracts:
        - category_id: 1..25
        - name: Category name
        - requires_followup: bool
        - suggested_scheduled_at: ISO timestamp based on category delay
        - action: recommended action
        """
        text = transcript.strip()
        if not text:
            return FollowupDetectionResult(
                category_id=3,
                name=FOLLOWUP_CATEGORIES[3]["name"],
                description=FOLLOWUP_CATEGORIES[3]["description"],
                requires_followup=True,
                action=FOLLOWUP_CATEGORIES[3]["action"],
                suggested_delay_minutes=60,
                suggested_scheduled_at=(datetime.now(UTC) + timedelta(minutes=60)).isoformat(),
                matched_utterance="Empty transcript / no conversation turns",
                priority_level=1,
            )

        # Extract only customer lines if role prefixes exist
        customer_lines = []
        for line in text.split("\n"):
            line_str = line.strip()
            if any(line_str.lower().startswith(p) for p in ["customer:", "user:", "client:", "caller:"]):
                customer_lines.append(line_str.split(":", 1)[1].strip())
            elif not any(line_str.lower().startswith(p) for p in ["agent:", "assistant:", "bot:"]):
                customer_lines.append(line_str)

        customer_text = " ".join(customer_lines) if customer_lines else text

        # Check for Category 4: Immediate disconnect without meaningful conversation
        # e.g. Customer says only "hello" or "ha" and call ends (1 turn)
        tokens = customer_text.split()
        if len(tokens) <= 2 and customer_text.strip().lower() in ["hello", "ha", "haan", "yes", "bolo"]:
            cat_info = FOLLOWUP_CATEGORIES[4]
            return FollowupDetectionResult(
                category_id=4,
                name=cat_info["name"],
                description=cat_info["description"],
                requires_followup=cat_info["requires_followup"],
                action=cat_info["action"],
                suggested_delay_minutes=cat_info["default_delay_minutes"],
                suggested_scheduled_at=(datetime.now(UTC) + timedelta(minutes=cat_info["default_delay_minutes"])).isoformat(),
                matched_utterance=customer_text,
                priority_level=2,
            )

        # Check for Category 24: Silent call (Customer answers but stays silent)
        # e.g., only "..." or repeated hello from agent with silence from customer
        if len(customer_text.strip()) == 0 or re.match(r"^(\.\.\.|\s*|silent|silence)+$", customer_text, re.IGNORECASE):
            cat_info = FOLLOWUP_CATEGORIES[24]
            return FollowupDetectionResult(
                category_id=24,
                name=cat_info["name"],
                description=cat_info["description"],
                requires_followup=cat_info["requires_followup"],
                action=cat_info["action"],
                suggested_delay_minutes=cat_info["default_delay_minutes"],
                suggested_scheduled_at=(datetime.now(UTC) + timedelta(minutes=cat_info["default_delay_minutes"])).isoformat(),
                matched_utterance="Client stayed silent",
                priority_level=1,
            )

        # Apply Priority Rules:
        # Highest Priority: Wrong number (19), Voicemail (25)
        if self.p_cat19.search(customer_text):
            return self._build_result(19, customer_text, self.p_cat19.search(customer_text).group(0), priority=1)

        if self.p_cat25.search(text):
            return self._build_result(25, text, self.p_cat25.search(text).group(0), priority=1)

        # Specific time/day instruction: (8, 13, 14) overrides generic unavailability (1, 7, 11)
        m8 = self.p_cat8.search(customer_text)
        if m8:
            return self._build_result(8, customer_text, m8.group(0), priority=2)

        m13 = self.p_cat13.search(customer_text)
        if m13:
            return self._build_result(13, customer_text, m13.group(0), priority=3)

        m14 = self.p_cat14.search(customer_text)
        if m14:
            return self._build_result(14, customer_text, m14.group(0), priority=4)

        # WhatsApp request (15)
        m15 = self.p_cat15.search(customer_text)
        if m15:
            return self._build_result(15, customer_text, m15.group(0), priority=5)

        # Alternate number / person (16)
        m16 = self.p_cat16.search(customer_text)
        if m16:
            return self._build_result(16, customer_text, m16.group(0), priority=6)

        # Driving / Travel (9)
        m9 = self.p_cat9.search(customer_text)
        if m9:
            return self._build_result(9, customer_text, m9.group(0), priority=7)

        # In meeting / class (10)
        m10 = self.p_cat10.search(customer_text)
        if m10:
            return self._build_result(10, customer_text, m10.group(0), priority=8)

        # Audio / Connection difficulties (5, 6, 17, 23)
        m17 = self.p_cat17.search(customer_text)
        if m17:
            return self._build_result(17, customer_text, m17.group(0), priority=9)

        m5 = self.p_cat5.search(customer_text)
        if m5:
            return self._build_result(5, customer_text, m5.group(0), priority=10)

        m6 = self.p_cat6.search(customer_text)
        if m6:
            return self._build_result(6, customer_text, m6.group(0), priority=11)

        m23 = self.p_cat23.search(customer_text)
        if m23:
            return self._build_result(23, customer_text, m23.group(0), priority=12)

        # Call back later requests (12, 7)
        m12 = self.p_cat12.search(customer_text)
        if m12:
            return self._build_result(12, customer_text, m12.group(0), priority=13)

        m7 = self.p_cat7.search(customer_text)
        if m7:
            return self._build_result(7, customer_text, m7.group(0), priority=14)

        # Language difficulty (22)
        m22 = self.p_cat22.search(customer_text)
        if m22:
            return self._build_result(22, customer_text, m22.group(0), priority=15)

        # Cannot talk now / Does not want to talk now (11, 20)
        m11 = self.p_cat11.search(customer_text)
        if m11:
            return self._build_result(11, customer_text, m11.group(0), priority=16)

        m20 = self.p_cat20.search(customer_text)
        if m20:
            return self._build_result(20, customer_text, m20.group(0), priority=17)

        # Personal / work reason (21)
        m21 = self.p_cat21.search(customer_text)
        if m21:
            return self._build_result(21, customer_text, m21.group(0), priority=18)

        # Line busy (2)
        m2 = self.p_cat2.search(customer_text)
        if m2:
            return self._build_result(2, customer_text, m2.group(0), priority=19)

        # Client unavailable / busy (1)
        m1 = self.p_cat1.search(customer_text)
        if m1:
            return self._build_result(1, customer_text, m1.group(0), priority=20)

        # No follow-up condition detected (Normal conversation without interruption)
        return FollowupDetectionResult(
            category_id=None,
            name=None,
            description="Call completed without explicit follow-up / callback trigger.",
            requires_followup=False,
            action=None,
            suggested_delay_minutes=None,
            suggested_scheduled_at=None,
            matched_utterance=None,
            priority_level=99,
        )

    def _build_result(self, cat_id: int, full_text: str, match_text: str, priority: int) -> FollowupDetectionResult:
        cat_info = FOLLOWUP_CATEGORIES[cat_id]
        delay = cat_info.get("default_delay_minutes")
        scheduled_iso = None
        # Check exact customer requested callback moment
        try:
            from app.services.callback_time import schedule_from_transcript
            desired_dt = schedule_from_transcript(full_text)
            if desired_dt:
                scheduled_iso = desired_dt.astimezone(UTC).isoformat()
        except Exception:
            pass

        if not scheduled_iso and delay and cat_info.get("requires_followup"):
            scheduled_iso = (datetime.now(UTC) + timedelta(minutes=delay)).isoformat()

        return FollowupDetectionResult(
            category_id=cat_id,
            name=cat_info["name"],
            description=cat_info["description"],
            requires_followup=cat_info["requires_followup"],
            action=cat_info["action"],
            suggested_delay_minutes=delay,
            suggested_scheduled_at=scheduled_iso,
            matched_utterance=match_text,
            priority_level=priority,
        )


followup_detector = FollowupDetector()
