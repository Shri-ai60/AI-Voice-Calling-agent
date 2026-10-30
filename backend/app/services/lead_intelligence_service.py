import re
import os
import sys
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Ensure the model package is importable
MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "model"))
if MODEL_DIR not in sys.path and os.path.exists(MODEL_DIR):
    sys.path.insert(0, MODEL_DIR)

try:
    from classifier.engine import IntentClassifier
    from classifier.models import IntentClassification, DetailedClassificationResponse
    from classifier.followup_detector import followup_detector, FollowupDetectionResult, FOLLOWUP_CATEGORIES
    _classifier_available = True
except Exception as e:
    logging.getLogger(__name__).warning(f"Could not import IntentClassifier or FollowupDetector from model dir: {e}")
    _classifier_available = False
    followup_detector = None
    FOLLOWUP_CATEGORIES = {}

try:
    # One-file offline analyzer (stdlib only): customer-info extraction,
    # why-interested / why-not reasons with evidence, lead score, Excel export.
    from transcript_analyzer import analyze_transcript as _analyze_transcript_offline
    _analyzer_available = True
except Exception as e:
    logging.getLogger(__name__).warning(f"Could not import transcript_analyzer: {e}")
    _analyzer_available = False
    _analyze_transcript_offline = None

from app.models.call import Call, Transcript, TranscriptSegment
from app.models.lead import Lead, Followup
from app.models.contact import Contact
from app.config import settings

logger = logging.getLogger(__name__)



# -------------------------------------------------------------
# Comprehensive Initial Interest & Follow-up Evaluator
# -------------------------------------------------------------
AUDIO_OR_IDENTITY_CHECK_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bcan\s+you\s+hear\s+me\b",
        r"\bam\s+i\s+audible\b",
        r"\bhello\s*,?\s*can\s+you\s+hear\b",
        r"\bhello\s*\??$",
        r"\bis\s+this\s+[a-z\s\.\']+\??$",
        r"\bam\s+i\s+speaking\s+(?:to|with)\b",
        r"\baawaz\s+aa\s+rahi\s+hai\b",
        r"\bmeri\s+aawaz\s+aa\s+rahi\s+hai\b",
        r"\bmajha\s+aawaz\s+yetoy\s+ka\b",
        r"\baawaz\s+yetoy\s+ka\b",
        r"आवाज\s+येतोय\s+का",
        r"आवाज़\s+आ\s+रही\s+है",
    ]
]

INTEREST_QUESTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bare\s+you\s+interested\b",
        r"\binterested\s+in\s+(?:learning|knowing|our|this|hearing)\b",
        r"\bwould\s+you\s+like\s+to\s+(?:know|hear|learn|explore)\b",
        r"\bcan\s+i\s+(?:tell\s+you|explain|share)\b",
        r"\bdo\s+you\s+want\s+to\s+know\b",
        r"\bwe\s+are\s+providing\b",
        r"\bwe\s+are\s+offering\b",
        r"जानकारी\s+चाहते\s+हैं",
        r"जानकारी\s+लेना\s+चाहते\s+हैं",
        r"इंटरेस्टेड\s+हैं",
        r"रुचि\s+रखते\s+हैं",
        r"एडमिशन\s+के\s+बारे\s+में",
        r"कोर्स\s+के\s+बारे\s+में",
        r"फ्लैट\s+देखने\s+में",
        r"माहिती\s+(?:हवी|पाहिजे)\s+आहे\s+का",
        r"जाणून\s+घ्यायचे\s+का",
        r"इच्छुक\s+आहात\s+का",
        r"बियाणे\s+उपलब्ध",
        r"मदत\s+करू\s+शकतो",
    ]
]

AFFIRMATIVE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^\s*(?:yes|yeah|yep|yup|sure|ok|okay|definitely|absolutely|certainly|interested|please\s*do|tell\s*me\s*more|i\s*want\s*to\s*know|i\s*am\s*interested|i\'m\s*interested)[\s\.,!]*$",
        r"\b(?:yes|yeah|yep|sure|definitely)\s*,?\s*(?:please|tell\s*me\s*more|i\s*am\s*interested|i\s*want\s*to\s*know|i\s*want\s*to\s*purchase)\b",
        r"\b(?:i\s*am|i\'m)\s*interested\b",
        r"\btell\s*me\s*more\b",
        r"\b(?:what\s+are|tell\s+me)\s+(?:your\s+)?prices?\b",
        r"\bwhat\s+(?:is|are)\s+the\s+(?:price|fees?|charges?|cost)\b",
        r"\bhow\s+much\s+(?:does\s+it\s+cost|is\s+it)\b",
        r"\b(?:send|bhejo|patwa)\s+.*whatsapp\b",
        r"\bwhatsapp\s+.*(?:send|bhejo|details|mahitii)\b",
        r"^\s*(?:हाँ|हा|हाँजी|जी|हां|हॉं|ज़रूर|जरूर|बताइए|बोलो|बोलिए|बिलकुल|बिल्कुल|ठीक\s*है)[\s\.,!]*$",
        r"(?:हाँ|हा|जी|हां)\s*,?\s*(?:बताइए|बताओ|जानकारी\s*चाहिए|चाहता\s*हूँ|चाहती\s*हूँ|इंटरेस्टेड\s*हूँ|दीजिए|सुनाइए)",
        r"जानकारी\s*(?:चाहिए|दीजिए|लेना\s*चाहता)",
        r"(?:याचे\s+)?दर\s+काय\s+आहेत",
        r"फीस\s+कितनी\s+है",
        r"कीमत\s+कितनी\s+है",
        r"^\s*(?:हो|होय|माहिती\s*पाहिजे|सांगा|नक्कीच|हो\s*सांगा)[\s\.,!]*$",
        r"हो\s*,?\s*(?:मला\s*)?(?:माहिती\s*पाहिजे|सांगा|आवड\s*आहे|हवी\s*आहे)",
        r"माहिती\s*(?:पाहिजे|द्या|सांगा)",
    ]
]

FOLLOWUP_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bi\s*am\s*busy(?:\s*right\s*now|\s*now|\s*currently|\s*today)?\b",
        r"\bi\'?m\s*busy(?:\s*right\s*now|\s*now|\s*currently|\s*today)?\b",
        r"\bbusy\s*right\s*now\b",
        r"\b(?:call|phone)\s*(?:me\s*)?(?:tomorrow|later|tonight|next\s*week)\b",
        r"\bcall\s*me\s*(?:today\s*)?(?:at\s*)?\d+(?::\d+)?\s*(?:am|pm)?\b",
        r"\bcall\s*me\s*(?:next\s*)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bneed\s*(?:some\s*)?time\s*to\s*(?:decide|think|discuss)\b",
        r"\bi\s*need\s*(?:some\s*)?time\b",
        r"\bdiscuss\s*(?:it\s*)?with\s*(?:my\s*)?family\b",
        r"\b(?:no\s*,?\s*)?call\s*me\s*tomorrow\b",
        r"\bplease\s*call\s*me\s*tomorrow\b",
        r"\bcurrently\s*travelling\b",
        r"व्यस्त\s*(?:हूँ|हु|है)",
        r"अभी\s*व्यस्त",
        r"टाइम\s*नहीं\s*है",
        r"फुर्सत\s*नहीं\s*है",
        r"बाद\s*में\s*(?:फोन|कॉल|बात)",
        r"कल\s*(?:सुबह\s*)?(?:फोन|कॉल|बात)",
        r"सोचने\s*(?:के\s*लिए|का)?\s*समय",
        r"व्यस्त\s*आहे",
        r"वेळ\s*नाही",
        r"नंतर\s*(?:फोन|कॉल|बोलू|सांगा)",
        r"उद्या\s*(?:फोन|कॉल|बोलूया|करा)",
        r"विचार\s*करून\s*सांगतो",
        r"घरच्यांशी\s*बोलून",
    ]
]

REJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(?:no|nope)\s*,?\s*(?:not\s*interested|i\s*am\s*not\s*interested|don\'?t\s*want)\b",
        r"^\s*(?:no|nope|not\s*interested)[\s\.,!]*$",
        r"\bnot\s*interested\b",
        r"\bdon\'?t\s*call\s*(?:me\s*)?again\b",
        r"\bdo\s*not\s*call\b",
        r"\bstop\s*calling\b",
        r"\bremove\s*(?:my\s*)?number\b",
        r"नहीं\s*,?\s*(?:नहीं\s*चाहिए|रुचि\s*नहीं|इंटरेस्ट\s*नहीं|नॉट\s*इंटरेस्टेड)",
        r"^\s*(?:नहीं|नही|ना)[\s\.,!]*$",
        r"नहीं\s*चाहिए",
        r"दोबारा\s*फोन\s*मत\s*(?:करना|कीजिए)",
        r"^\s*(?:नाही|नको)[\s\.,!]*$",
        r"नाही\s*,?\s*(?:नको|माहिती\s*नको|रुची\s*नाही)",
        r"नको\s*आहे",
        r"पुन्हा\s*फोन\s*करू\s*नका",
    ]
]

OPT_OUT_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bdon\'?t\s*call\s*(?:me\s*)?again\b",
        r"\bdo\s*not\s*call\b",
        r"\bstop\s*calling\b",
        r"\bnever\s*call\b",
        r"\bremove\s*(?:my\s*)?number\b",
        r"दोबारा\s*फोन\s*मत\s*(?:करना|कीजिए)",
        r"फोन\s*मत\s*करो",
        r"पुन्हा\s*फोन\s*करू\s*नका",
    ]
]

AUDIO_CHECK_RESPONSE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(?:yes\s*,?\s*)?(?:i\s*can\s*hear\s*you|can\s*hear\s*you|you\s*are\s*audible)\b",
        r"\b(?:हाँ|हा)\s*,?\s*(?:आवाज\s*आ\s*रही\s*है|सुनाई\s*दे\s*रहा\s*है)\b",
        r"\b(?:हो)\s*,?\s*(?:आवाज\s*येतोय|ऐकू\s*येतंय)\b",
    ]
]


def extract_turns_from_data(segments: Optional[List[Any]] = None, transcript_text: str = "") -> List[Dict[str, str]]:
    turns = []
    if segments:
        sorted_segs = sorted(segments, key=lambda s: s.get("sequence", 0) if isinstance(s, dict) else (getattr(s, "sequence", 0) or 0))
        for seg in sorted_segs:
            spk = seg.get("speaker", "") if isinstance(seg, dict) else getattr(seg, "speaker", "")
            txt = seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")
            role = "agent" if spk in ("agent", "bot", "assistant") else "customer"
            if txt and txt.strip():
                turns.append({"role": role, "text": txt.strip()})
    elif transcript_text:
        for line in transcript_text.splitlines():
            line_s = line.strip()
            if not line_s:
                continue
            if line_s.lower().startswith(("agent:", "assistant:", "bot:")):
                parts = line_s.split(":", 1)
                turns.append({"role": "agent", "text": parts[1].strip()})
            elif line_s.lower().startswith(("customer:", "user:", "caller:", "client:")):
                parts = line_s.split(":", 1)
                turns.append({"role": "customer", "text": parts[1].strip()})
    return turns


def evaluate_initial_interest(turns: List[Dict[str, str]]) -> Dict[str, Any]:
    interest_agent_turn = None
    customer_answer_turn = None

    for i, t in enumerate(turns):
        role = t.get("role", "").lower()
        txt = t.get("text", "").strip()
        if not txt:
            continue

        if role == "agent" and not interest_agent_turn:
            is_audio_check = any(p.search(txt) for p in AUDIO_OR_IDENTITY_CHECK_PATTERNS)
            is_pitch = any(p.search(txt) for p in INTEREST_QUESTION_PATTERNS)
            if is_pitch:
                interest_agent_turn = txt
                for j in range(i + 1, len(turns)):
                    if turns[j].get("role", "").lower() in ("customer", "user", "caller"):
                        customer_answer_turn = turns[j].get("text", "").strip()
                        break
                break
            elif not is_audio_check and len(txt) > 20:
                interest_agent_turn = txt
                for j in range(i + 1, len(turns)):
                    if turns[j].get("role", "").lower() in ("customer", "user", "caller"):
                        customer_answer_turn = turns[j].get("text", "").strip()
                        break
                break

    if not interest_agent_turn:
        for t in turns:
            if t.get("role", "").lower() == "agent" and not interest_agent_turn:
                interest_agent_turn = t.get("text", "").strip()
            elif t.get("role", "").lower() in ("customer", "user", "caller") and not customer_answer_turn:
                customer_answer_turn = t.get("text", "").strip()

    if not customer_answer_turn:
        return {
            "classification": "UNCERTAIN",
            "is_interested": False,
            "is_followup": False,
            "is_rejected": False,
            "is_opt_out": False,
            "reason": "No customer response found.",
            "evidence": "",
        }

    c_text = customer_answer_turn.strip()

    # Audio check guard
    if interest_agent_turn and any(p.search(interest_agent_turn) for p in AUDIO_OR_IDENTITY_CHECK_PATTERNS):
        if any(p.search(c_text) for p in AUDIO_CHECK_RESPONSE_PATTERNS) or c_text.lower() in ("yes", "yeah", "हाँ", "हा", "हो"):
            return {
                "classification": "UNCERTAIN",
                "is_interested": False,
                "is_followup": False,
                "is_rejected": False,
                "is_opt_out": False,
                "reason": "Customer answered audio/identity check; not an interest response.",
                "evidence": c_text,
            }

    # Opt-out check
    is_opt_out = any(p.search(c_text) for p in OPT_OUT_PATTERNS)
    if is_opt_out:
        return {
            "classification": "NOT_INTERESTED",
            "is_interested": False,
            "is_followup": False,
            "is_rejected": True,
            "is_opt_out": True,
            "reason": "Customer explicitly requested not to be called again (opt-out / DNC).",
            "evidence": c_text,
        }

    is_followup = any(p.search(c_text) for p in FOLLOWUP_PATTERNS)
    is_aff = any(p.search(c_text) for p in AFFIRMATIVE_PATTERNS)
    is_rej = any(p.search(c_text) for p in REJECTION_PATTERNS)

    # Scenario 15: "I am interested, but call me tomorrow" -> Both INTERESTED and FOLLOW_UP!
    if is_aff and is_followup:
        return {
            "classification": "INTERESTED",
            "is_interested": True,
            "is_followup": True,
            "is_rejected": False,
            "is_opt_out": False,
            "reason": "Customer expressed interest and requested a follow-up callback.",
            "evidence": c_text,
        }

    if is_aff and not is_rej:
        return {
            "classification": "INTERESTED",
            "is_interested": True,
            "is_followup": False,
            "is_rejected": False,
            "is_opt_out": False,
            "reason": "Customer responded positively to initial interest question.",
            "evidence": c_text,
        }

    if is_followup:
        reason = "Customer requested callback."
        c_low = c_text.lower()
        if "busy" in c_low or "व्यस्त" in c_text or "time nahi" in c_low or "वेळ नाही" in c_text:
            reason = "Customer is busy. (Action: Schedule callback)"
        elif "think" in c_low or "decide" in c_low or "family" in c_low or "सोचने" in c_text or "विचार" in c_text:
            reason = "Customer needs time to decide. (Action: Schedule callback)"

        return {
            "classification": "FOLLOW_UP",
            "is_interested": False,
            "is_followup": True,
            "is_rejected": False,
            "is_opt_out": False,
            "reason": reason,
            "evidence": c_text,
        }

    if is_rej:
        return {
            "classification": "NOT_INTERESTED",
            "is_interested": False,
            "is_followup": False,
            "is_rejected": True,
            "is_opt_out": False,
            "reason": "Customer declined initial interest question.",
            "evidence": c_text,
        }

    return {
        "classification": "UNCERTAIN",
        "is_interested": False,
        "is_followup": False,
        "is_rejected": False,
        "is_opt_out": False,
        "reason": "Customer response was ambiguous or unclear.",
        "evidence": c_text,
    }

class LeadIntelligenceService:
    """
    Lead Interest Intelligence Service powered by Google Gemini LLM
    with secondary fallback to the Multilingual AI Intent Classifier.
    Evaluates real customer conversation transcripts across English, Hindi (Devanagari & Hinglish),
    Marathi, and Indic code-mixed speech.
    Accurately scores confidence, explains reasoning, detects opt-outs, and manages the
    Interested Leads Pipeline.
    """

    def __init__(self):
        if _classifier_available:
            self.classifier = IntentClassifier()
        else:
            self.classifier = None

    @classmethod
    def evaluate_initial_interest(cls, turns: List[Dict[str, str]]) -> Dict[str, Any]:
        """Context-aware initial interest question evaluation."""
        return evaluate_initial_interest(turns)

    @classmethod
    def detect_first_question_yes(cls, segments: Optional[List[Any]] = None, transcript_text: str = "") -> bool:
        """
        Determines if the customer answered 'YES' / affirmative to the agent's opening interest question.
        Uses conversational context rather than simple word matches.
        """
        turns = extract_turns_from_data(segments, transcript_text)
        res = evaluate_initial_interest(turns)
        return bool(res.get("is_interested", False))

    def build_transcript_text(self, call: Call, segments: Optional[List[Any]] = None) -> str:
        """
        Extracts formatted multi-turn conversation text from call transcript segments.
        Accepts explicit segments list to avoid async SQLAlchemy lazy-loading greenlet errors.
        """
        if segments:
            lines = []
            for seg in sorted(segments, key=lambda s: s.get("sequence", 0) if isinstance(s, dict) else (getattr(s, "sequence", 0) or 0)):
                if isinstance(seg, dict):
                    spk = seg.get("speaker", "")
                    txt = seg.get("text", "")
                else:
                    spk = getattr(seg, "speaker", "")
                    txt = getattr(seg, "text", "")
                role_prefix = "Agent" if spk in ("agent", "bot", "assistant") else "Customer"
                lines.append(f"{role_prefix}: {txt}")
            return "\n".join(lines).strip()

        try:
            if call.transcript and call.transcript.segments:
                lines = []
                for seg in sorted(call.transcript.segments, key=lambda s: s.sequence if s.sequence is not None else 0):
                    role_prefix = "Agent" if seg.speaker in ("agent", "bot", "assistant") else "Customer"
                    lines.append(f"{role_prefix}: {seg.text}")
                return "\n".join(lines).strip()
        except Exception:
            pass

        return ""

    async def analyze_with_gemini(self, transcript_text: str) -> Optional[Dict[str, Any]]:
        """
        Uses Gemini LLM to accurately determine customer intent and interest from multi-turn transcript.
        Specifically handles Indic dialects, Hindi transliterations ('नॉट इंटरेस्टेड', 'नहीं चाहिए'),
        and nuanced sales conversation signals.
        """
        gemini_key = getattr(settings, "GEMINI_API_KEY", None) or os.environ.get("GEMINI_API_KEY", "")
        if not gemini_key:
            return None

        # Fast, low-latency, resilient model hierarchy
        configured_model = getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")
        candidate_models = list(dict.fromkeys([
            configured_model,
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-2.5-flash",
            "gemini-1.5-pro",
            "gemini-2.5-pro",
            "gemini-2.0-flash-lite",
            "gemini-flash-lite-latest",
        ]))

        prompt = f"""You are a specialized Lead Interest Intelligence analyzer for enterprise sales and support telephony calls.
Your objective: accurately classify customer intent from the conversation transcript.

Transcript to analyze:
\"\"\"
{transcript_text}
\"\"\"

Crucial Classification Rules:
1. First Question Yes Policy (TOP PRIORITY CLIENT POLICY):
   - At the beginning of the call, the agent asks whether the customer is interested or open to talking (e.g. "क्या आप इसमें इंटरेस्टेड हैं?").
   - If customer says YES ("हाँ", "जी", "हांजी", "yes", "sure", "bataiye", "theek hai", "interested") to this first question:
     status: "interested", is_interested: true, classification: "INTERESTED", interest_strength: "HIGH", confidence: 0.95.
   - CRUCIAL: Even if further in the conversation the customer says no or the call ends abruptly, saying YES to the first qualification question confirms they ARE an INTERESTED lead!
2. Call Duration Policy (> 1 Minute Engagement):
   - If the customer engages in conversation for more than 1 minute (or participates in multi-turn questions about acreage, seed varieties, quantity, timing, or price):
     They have invested meaningful time and MUST BE CLASSIFIED AS:
     status: "interested", is_interested: true, classification: "INTERESTED", interest_strength: "HIGH", confidence: 0.92+.
3. Indic & Hindi Nuances:
   - Phrases like "नॉट इंटरेस्टेड", "not interested", "नहीं बोलना", "नहीं चाहिए", "phone mat karo", "fursat nahi hai", "cut the call", "wrong number", or hanging up with clear negative sentiment MUST BE CLASSIFIED AS:
     status: "not_interested", is_interested: false, classification: "NOT_INTERESTED", interest_strength: "NONE", confidence: 0.90 to 0.99.
   - Under NO circumstance should a customer rejection or refusal be classified as interested!
2. Genuine Interest:
   - Customer inquires about pricing, offers, products, or service assistance (e.g. "kya plan hai", "bataiye", "price kitna hai", agrees to next step/demo):
     status: "interested", is_interested: true, classification: "INTERESTED", interest_strength: "HIGH" or "MEDIUM", confidence: 0.70 to 0.99.
3. Callback Request:
   - Customer asks to be called back later ("baad mein call karo", "call tomorrow"):
     status: "callback_requested", is_interested: true, classification: "CALLBACK_REQUESTED", interest_strength: "MEDIUM", confidence: 0.80 to 0.95.
4. Ambiguous / Disconnected:
   - Customer only uttered greeting ("hello") or silence with no real engagement:
     status: "uncertain", is_interested: false, classification: "UNCERTAIN", interest_strength: "LOW", confidence: 0.30 to 0.50.

Return ONLY a valid JSON object with these exact keys:
{{
  "status": "interested" | "not_interested" | "callback_requested" | "uncertain",
  "is_interested": boolean,
  "classification": "INTERESTED" | "NOT_INTERESTED" | "CALLBACK_REQUESTED" | "UNCERTAIN",
  "interest_strength": "HIGH" | "MEDIUM" | "LOW" | "NONE",
  "confidence": float,
  "reasoning": string,
  "rule_applied": string,
  "signals": list of strings,
  "languages": list of strings,
  "opt_out_detected": boolean,
  "callback_requested": boolean
}}"""

        import httpx

        for model_name in candidate_models:
            m_clean = model_name if not model_name.startswith("models/") else model_name.split("/")[-1]
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_clean}:generateContent?key={gemini_key}"
            try:
                gen_config = {
                    "responseMimeType": "application/json",
                    "temperature": 0.1,
                }
                async with httpx.AsyncClient(timeout=25.0) as client:
                    resp = await client.post(
                        url,
                        json={
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": gen_config,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        text_payload = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if text_payload.startswith("```"):
                            text_payload = text_payload.strip("`")
                            if text_payload.startswith("json"):
                                text_payload = text_payload[4:]
                            text_payload = text_payload.strip()
                        import json
                        parsed = json.loads(text_payload)
                        logger.info(f"Lead intelligence successfully evaluated via Gemini ({m_clean}): status={parsed.get('status')}, confidence={parsed.get('confidence')}")
                        return parsed
            except Exception as ex:
                logger.warning(f"Error querying Gemini model {m_clean} for lead intelligence: {type(ex).__name__} - {str(ex)[:100]}")

        return None

    async def analyze_call(self, session: AsyncSession, call: Call, segments: Optional[List[Any]] = None) -> Dict[str, Any]:
        """
        Analyzes a call's full transcript using Gemini LLM (with fallback to local engine)
        and updates the call disposition, contact suppression, and Interested Leads Pipeline.
        """
        if not segments:
            try:
                seg_stmt = (
                    select(TranscriptSegment)
                    .join(Transcript)
                    .where(Transcript.call_id == call.id)
                    .order_by(TranscriptSegment.sequence.asc())
                )
                seg_res = await session.execute(seg_stmt)
                segments = seg_res.scalars().all()
            except Exception as e:
                logger.warning(f"Could not load segments explicitly: {e}")

        transcript_text = self.build_transcript_text(call, segments=segments)

        # Handle empty/unrecorded calls
        if not transcript_text:
            return {
                "analysis_id": f"intel_{call.id}",
                "call_id": call.id,
                "agent_id": call.agent_id,
                "contact_id": call.contact_id,
                "status": "uncertain",
                "confidence_score": 0.0,
                "confidence": 0.0,
                "classification": "UNCERTAIN",
                "interest_strength": "UNKNOWN",
                "opt_out_detected": False,
                "callback_requested": False,
                "objection_detected": None,
                "reasoning": "No transcript turns available to evaluate customer intent.",
                "rule_applied": "No conversational data",
                "signals": [],
                "languages": [],
                "keywords": [],
                "created_at": datetime.now(UTC).isoformat(),
            }

        # 0. Offline analyzer (always available, stdlib only): extracts the
        # customer's stated details and WHY-reasons with evidence quotes.
        # This runs fully offline on any machine; Gemini/local classification
        # below stays the classifier of record.
        offline: Dict[str, Any] = {}
        customer_info: Dict[str, Any] = {}
        why_interested: List[Dict[str, str]] = []
        why_not_interested: List[Dict[str, str]] = []
        if _analyzer_available and _analyze_transcript_offline is not None:
            try:
                offline = _analyze_transcript_offline(transcript_text)
                customer_info = offline.get("customer_info") or {}
                why_interested = offline.get("why_interested") or []
                why_not_interested = offline.get("why_not_interested") or []
            except Exception as ae:
                logger.warning(f"Offline transcript analyzer failed: {ae}")

        # Business policy (client rule): If customer says YES to the first question,
        # they are added to the INTERESTED leads pipeline even if further in the conversation they say no.
        first_q_yes = self.detect_first_question_yes(segments=segments, transcript_text=transcript_text)

        # Duration Policy: If customer speaks / engages for more than 1 minute (>60s),
        # they are classified as an INTERESTED lead per business rule.
        call_duration = getattr(call, "duration", 0) or 0
        customer_speech_duration = 0.0
        if segments:
            for seg in segments:
                spk = seg.get("speaker", "") if isinstance(seg, dict) else getattr(seg, "speaker", "")
                if spk in ("customer", "user", "caller"):
                    st = seg.get("start_time", 0.0) if isinstance(seg, dict) else (getattr(seg, "start_time", 0.0) or 0.0)
                    et = seg.get("end_time", 0.0) if isinstance(seg, dict) else (getattr(seg, "end_time", 0.0) or 0.0)
                    if et > st:
                        customer_speech_duration += (et - st)
        elif transcript_text:
            cust_lines = [l for l in transcript_text.splitlines() if l.startswith("Customer:")]
            if len(cust_lines) >= 4:
                customer_speech_duration = max(customer_speech_duration, len(cust_lines) * 15.0)

        duration_interested = (call_duration >= 60) or (customer_speech_duration >= 50.0)

        # 1. Primary: Evaluate using Gemini LLM
        gemini_result = None
        try:
            gemini_result = await self.analyze_with_gemini(transcript_text)
        except Exception as ge:
            logger.warning(f"Gemini lead analysis failed, falling back to rule engine: {ge}")

        if gemini_result and isinstance(gemini_result, dict):
            status = gemini_result.get("status", "uncertain")
            is_interested = bool(gemini_result.get("is_interested", False))
            confidence = float(gemini_result.get("confidence", 0.85))
            classification_str = gemini_result.get("classification", "UNCERTAIN")
            interest_strength_str = gemini_result.get("interest_strength", "NONE" if not is_interested else "HIGH")
            opt_out = bool(gemini_result.get("opt_out_detected", False))
            callback_req = bool(gemini_result.get("callback_requested", False))
            reasoning = gemini_result.get("reasoning", "")
            rule_applied = gemini_result.get("rule_applied", "Gemini AI Lead Interest Intelligence")
            signals = gemini_result.get("signals", [])
            languages = gemini_result.get("languages", ["Hindi"])

            # First-question YES policy: Customer confirmed interest at Question 1.
            # Client Rule: Always add to interested leads even if later in conversation they said no.
            if first_q_yes:
                is_interested = True
                status = "interested"
                classification_str = "INTERESTED"
                interest_strength_str = "HIGH"
                confidence = max(confidence, 0.95)
                opt_out = False
                reasoning = ("Shortlisted at Question 1: customer answered YES to the initial interest question. " + reasoning).strip()
                rule_applied = "First Question YES Policy (Customer confirmed interest)"
            elif duration_interested:
                # Duration Policy: Customer spoke for > 1 minute
                is_interested = True
                status = "interested"
                classification_str = "INTERESTED"
                interest_strength_str = "HIGH"
                confidence = max(confidence, 0.92)
                opt_out = False
                dur_secs = int(call_duration if call_duration >= 60 else customer_speech_duration)
                reasoning = (f"Shortlisted by Duration: customer engaged in conversation for {dur_secs}s (>1 minute). " + reasoning).strip()
                rule_applied = "Call Duration > 1 Min Engagement Policy"

            # Sync Call disposition
            if opt_out:
                status = "not_interested"
                call.disposition = "not_interested"
                if call.contact_id:
                    try:
                        c_stmt = select(Contact).where(Contact.id == call.contact_id)
                        c_res = await session.execute(c_stmt)
                        contact = c_res.scalar_one_or_none()
                        if contact:
                            contact.status = "do_not_call"
                            session.add(contact)
                    except Exception as ce:
                        logger.warning(f"Could not update contact DNC: {ce}")
            elif callback_req:
                status = "callback_requested"
                call.disposition = "callback_requested"
            elif is_interested:
                status = "interested"
                call.disposition = "interested"
            else:
                status = "not_interested"
                call.disposition = "not_interested"

            session.add(call)

            # Manage Lead in Database
            lead_stmt = select(Lead).where(Lead.call_id == call.id)
            lead_res = await session.execute(lead_stmt)
            existing_lead = lead_res.scalar_one_or_none()

            if is_interested or first_q_yes or duration_interested:
                lead_metadata = {
                    "classification": classification_str,
                    "interest_strength": interest_strength_str,
                    "signals": signals,
                    "rule_applied": rule_applied,
                    "analyzer": "gemini",
                    "first_question_yes": first_q_yes,
                    "customer_info": customer_info,
                    "why_interested": why_interested,
                    "why_not_interested": why_not_interested,
                }
                phone = customer_info.get("phone") or call.phone_number or call.caller_number
                if not existing_lead:
                    existing_lead = Lead(
                        tenant_id=call.tenant_id,
                        agent_id=call.agent_id,
                        contact_id=call.contact_id,
                        call_id=call.id,
                        name=customer_info.get("name"),
                        email=customer_info.get("email"),
                        phone_number=phone,
                        score=confidence,
                        reason=reasoning,
                        status="interested",
                        metadata_json=lead_metadata,
                    )
                    session.add(existing_lead)
                else:
                    existing_lead.score = confidence
                    existing_lead.reason = reasoning
                    existing_lead.status = "interested"
                    existing_lead.metadata_json = lead_metadata
                    if customer_info.get("name"):
                        existing_lead.name = customer_info["name"]
                    if customer_info.get("email"):
                        existing_lead.email = customer_info["email"]
                    session.add(existing_lead)
            else:
                # If not genuinely interested, ensure FALSE leads are removed from pipeline
                if existing_lead:
                    await session.delete(existing_lead)

            # Check follow-up detector
            followup_info = None
            if followup_detector:
                try:
                    f_res = followup_detector.detect_followup_detailed(transcript_text)
                    if f_res.category_id is not None:
                        followup_info = {
                            "category_id": f_res.category_id,
                            "name": f_res.name,
                            "description": f_res.description,
                            "requires_followup": f_res.requires_followup,
                            "action": f_res.action,
                            "suggested_scheduled_at": f_res.suggested_scheduled_at,
                            "matched_utterance": f_res.matched_utterance,
                        }
                except Exception as fe:
                    logger.debug(f"Followup check exception: {fe}")

            return {
                "analysis_id": f"intel_{call.id}",
                "call_id": call.id,
                "agent_id": call.agent_id,
                "contact_id": call.contact_id,
                "status": status,
                "confidence_score": confidence,
                "confidence": confidence,
                "classification": classification_str,
                "binary_classification": "interested" if is_interested else "not_interested",
                "interest_strength": interest_strength_str,
                "opt_out_detected": opt_out,
                "callback_requested": callback_req,
                "objection_detected": None,
                "reasoning": reasoning,
                "rule_applied": rule_applied,
                "signals": signals,
                "languages": languages,
                "keywords": [f"Lang: {l}" for l in languages] + signals,
                "customer_info": customer_info,
                "why_interested": why_interested,
                "why_not_interested": why_not_interested,
                "offline_lead_score": offline.get("lead_score"),
                "followup": followup_info,
                "raw_model_output": gemini_result,
                "created_at": datetime.now(UTC).isoformat(),
            }

        # 2. Secondary Fallback: Use local rule classifier if Gemini was unavailable
        if self.classifier:
            try:
                diag: DetailedClassificationResponse = self.classifier.classify_detailed(transcript_text)
                is_interested = (
                    diag.classification in (IntentClassification.INTERESTED, IntentClassification.NEEDS_INFORMATION)
                    or diag.binary_classification == "INTERESTED"
                )
                confidence = float(diag.confidence)
                # First-question YES policy or Duration Policy (>1 min)
                if first_q_yes or duration_interested:
                    is_interested = True
                    diag.opt_out_detected = False
                    confidence = max(confidence, 0.95 if first_q_yes else 0.92)

                # Determine disposition and handle opt-out suppression
                if diag.opt_out_detected:
                    status = "not_interested"
                    call.disposition = "not_interested"
                    if call.contact_id:
                        try:
                            contact_stmt = select(Contact).where(Contact.id == call.contact_id)
                            c_res = await session.execute(contact_stmt)
                            contact = c_res.scalar_one_or_none()
                            if contact:
                                contact.status = "do_not_call"
                                session.add(contact)
                        except Exception as ce:
                            logger.warning(f"Could not update contact DNC status: {ce}")
                elif diag.callback_requested:
                    status = "callback_requested"
                    call.disposition = "callback_requested"
                elif is_interested:
                    status = "interested"
                    call.disposition = "interested"
                else:
                    status = "not_interested"
                    call.disposition = "not_interested"

                session.add(call)

                # Auto-create or update Lead record if interested and NOT opted-out
                lead_stmt = select(Lead).where(Lead.call_id == call.id)
                lead_res = await session.execute(lead_stmt)
                lead = lead_res.scalar_one_or_none()

                if is_interested or first_q_yes or duration_interested:
                    lead_metadata = {
                        "classification": diag.classification.value,
                        "interest_strength": diag.interest_strength.value,
                        "objection_detected": diag.objection_detected,
                        "signals": diag.signals_detected,
                        "rule_applied": diag.rule_applied,
                        "analyzer": "rule_engine",
                        "first_question_yes": first_q_yes,
                        "customer_info": customer_info,
                        "why_interested": why_interested,
                        "why_not_interested": why_not_interested,
                    }
                    if not lead:
                        lead = Lead(
                            tenant_id=call.tenant_id,
                            agent_id=call.agent_id,
                            contact_id=call.contact_id,
                            call_id=call.id,
                            name=customer_info.get("name"),
                            email=customer_info.get("email"),
                            phone_number=customer_info.get("phone") or call.phone_number or call.caller_number,
                            score=confidence,
                            reason=diag.reason,
                            status="interested",
                            metadata_json=lead_metadata,
                        )
                        session.add(lead)
                    else:
                        lead.score = confidence
                        lead.reason = diag.reason
                        lead.status = "interested"
                        lead.metadata_json = lead_metadata
                        if customer_info.get("name"):
                            lead.name = customer_info["name"]
                        if customer_info.get("email"):
                            lead.email = customer_info["email"]
                        session.add(lead)
                else:
                    if lead:
                        await session.delete(lead)

                keywords = list(diag.signals_detected) if diag.signals_detected else []
                if diag.languages_detected:
                    keywords.extend([f"Lang: {l}" for l in diag.languages_detected if l not in keywords])

                followup_info = None
                if followup_detector:
                    f_res = followup_detector.detect_followup_detailed(transcript_text)
                    if f_res.category_id is not None:
                        followup_info = {
                            "category_id": f_res.category_id,
                            "name": f_res.name,
                            "description": f_res.description,
                            "requires_followup": f_res.requires_followup,
                            "action": f_res.action,
                            "suggested_scheduled_at": f_res.suggested_scheduled_at,
                            "matched_utterance": f_res.matched_utterance,
                        }

                return {
                    "analysis_id": f"intel_{call.id}",
                    "call_id": call.id,
                    "agent_id": call.agent_id,
                    "contact_id": call.contact_id,
                    "status": status,
                    "confidence_score": confidence,
                    "confidence": confidence,
                    "classification": diag.classification.value,
                    "binary_classification": diag.binary_classification or ("interested" if is_interested else "not_interested"),
                    "interest_strength": diag.interest_strength.value,
                    "opt_out_detected": diag.opt_out_detected,
                    "callback_requested": diag.callback_requested,
                    "objection_detected": diag.objection_detected,
                    "reasoning": diag.reason,
                    "rule_applied": diag.rule_applied,
                    "signals": diag.signals_detected,
                    "languages": diag.languages_detected,
                    "keywords": keywords,
                    "customer_info": customer_info,
                    "why_interested": why_interested,
                    "why_not_interested": why_not_interested,
                    "offline_lead_score": offline.get("lead_score"),
                    "followup": followup_info,
                    "raw_model_output": diag.model_dump(),
                    "created_at": datetime.now(UTC).isoformat(),
                }
            except Exception as e:
                logger.error(f"IntentClassifier fallback failed on call {call.id}: {e}", exc_info=True)


        # Fallback if engine unavailable
        return {
            "analysis_id": f"intel_{call.id}",
            "call_id": call.id,
            "agent_id": call.agent_id,
            "contact_id": call.contact_id,
            "status": "uncertain",
            "confidence_score": 0.5,
            "confidence": 0.5,
            "classification": "UNCERTAIN",
            "reasoning": "Model classifier engine could not be executed.",
            "rule_applied": "Fallback",
            "signals": [],
            "languages": [],
            "keywords": [],
            "followup": None,
            "created_at": datetime.now(UTC).isoformat(),
        }

    async def analyze_followup(self, session: AsyncSession, call: Call, segments: Optional[List[Any]] = None) -> Dict[str, Any]:
        """
        Evaluates the transcript using the 25-category Follow-Up Detection Engine.
        If a follow-up condition is detected, optionally records or updates the Followup table.
        """
        if not segments:
            try:
                seg_stmt = (
                    select(TranscriptSegment)
                    .join(Transcript)
                    .where(Transcript.call_id == call.id)
                    .order_by(TranscriptSegment.sequence.asc())
                )
                seg_res = await session.execute(seg_stmt)
                segments = seg_res.scalars().all()
            except Exception as e:
                logger.warning(f"Could not load segments explicitly in analyze_followup: {e}")

        transcript_text = self.build_transcript_text(call, segments=segments)
        turns = extract_turns_from_data(segments, transcript_text)
        init_res = self.evaluate_initial_interest(turns)

        if not followup_detector:
            return {
                "call_id": call.id,
                "category_id": None,
                "name": None,
                "requires_followup": False,
                "message": "Followup detector engine unavailable"
            }

        res: FollowupDetectionResult = followup_detector.detect_followup_detailed(transcript_text)
        scheduled_dt = None

        # Automatic rescheduling from the customer's own words (offline)
        from app.services.callback_time import parse_callback_time, next_working_slot
        desired = parse_callback_time(transcript_text)
        if desired is not None:
            scheduled_dt = next_working_slot(desired)

        # Precise notes and date handling according to client scenarios
        t_low = (transcript_text or "").lower() + " " + (init_res.get("reason") or "").lower()
        if "busy" in t_low or "व्यस्त" in t_low or res.category_id == 1:
            notes_str = "Customer is busy. (Action: Schedule callback)"
            scheduled_dt = None
            res.requires_followup = True
        elif "decide" in t_low or "think" in t_low or "सोचने" in t_low or "विचार" in t_low:
            notes_str = "Customer needs time to decide. (Action: Schedule callback)"
            scheduled_dt = None
            res.requires_followup = True
        elif scheduled_dt is not None:
            notes_str = f"Customer requested callback for {scheduled_dt.strftime('%d %b %Y, %I:%M %p')}. (Action: Schedule callback)"
            res.requires_followup = True
        elif init_res.get("is_followup"):
            notes_str = f"{init_res.get('reason')}. (Action: Schedule callback)"
            scheduled_dt = None
            res.requires_followup = True
        else:
            notes_str = f"Category {res.category_id}: {res.name}. Action: {res.action}. (Matched: '{res.matched_utterance or 'N/A'}')"

        # Opt out guard
        if init_res.get("is_opt_out"):
            res.requires_followup = False

        followup_record_id = None
        call_phone = call.phone_number or call.caller_number
        if res.requires_followup and call_phone:
            stmt = select(Followup).where(Followup.call_id == call.id)
            db_res = await session.execute(stmt)
            followup = db_res.scalar_one_or_none()

            if not followup:
                followup = Followup(
                    tenant_id=call.tenant_id,
                    contact_id=call.contact_id,
                    agent_id=call.agent_id,
                    call_id=call.id,
                    phone_number=call_phone,
                    scheduled_at=scheduled_dt,
                    status="pending",
                    notes=notes_str,
                )
                session.add(followup)
            else:
                followup.scheduled_at = scheduled_dt
                followup.notes = notes_str
                followup.status = "pending"

            await session.flush()
            followup_record_id = followup.id

        return {
            "call_id": call.id,
            "agent_id": call.agent_id,
            "category_id": res.category_id,
            "name": res.name,
            "description": res.description,
            "requires_followup": res.requires_followup,
            "action": res.action,
            "suggested_scheduled_at": res.suggested_scheduled_at,
            "matched_utterance": res.matched_utterance,
            "priority_level": res.priority_level,
            "followup_id": followup_record_id,
        }


lead_intelligence_service = LeadIntelligenceService()

