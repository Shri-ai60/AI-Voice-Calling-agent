#!/usr/bin/env python3
"""
Transcript Analyzer — one-file, offline, low-end friendly lead intelligence model.
==================================================================================

What it does (from a raw call transcript):
  1. Classifies the customer: INTERESTED / NOT_INTERESTED / CALLBACK_REQUESTED /
     NEEDS_INFORMATION / UNCERTAIN (+ binary INTERESTED / NOT_INTERESTED).
  2. Explains WHY — categorized reasons, each backed by the customer's own
     words quoted as evidence (why interested, or why not).
  3. Extracts customer information stated in the call: name, phone, email,
     city, budget, preferred callback time, product interest, business type.
  4. Gives a 0–100 lead score.
  5. Exports everything to a real Excel (.xlsx) file — all results, or only
     Interested / only Not Interested / Follow-ups — so it can be downloaded
     and filtered later "according to our need".

Offline / low-end guarantees:
  * Python standard library ONLY. No pip installs, no internet, no GPU,
    no LLM download. Runs on Python 3.8+ on any PC (tested pattern: a few
    milliseconds per transcript, a few MB of RAM).
  * If the repo's richer rule classifier (model/classifier, needs pydantic)
    happens to be importable, it is used for classification; otherwise the
    built-in multilingual lexicon classifier in this file is used, so the
    file works standalone when copied anywhere on its own.

Usage:
  python transcript_analyzer.py call1.txt
  python transcript_analyzer.py --dir data/transcripts --excel leads.xlsx
  python transcript_analyzer.py --dir data/transcripts --excel interested.xlsx --filter interested
  python transcript_analyzer.py call1.txt --json out.json --csv out.csv

Transcript format: lines prefixed with "Agent:" / "Customer:" (also accepts
Bot/User/Caller, timestamps like [00:12], and plain unlabelled text, which is
then treated as customer speech).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# 1. Transcript parsing
# ---------------------------------------------------------------------------

_ROLE_RE = re.compile(
    r"^\s*(?:\[[0-9:.-]+\]\s*)?(agent|bot|assistant|system|customer|user|caller|client)\s*[:\-]\s*(.*)$",
    re.IGNORECASE,
)
_AGENT_ROLES = {"agent", "bot", "assistant", "system"}


def parse_transcript(text: str) -> List[Dict[str, str]]:
    """Split raw transcript text into [{role, text}] turns."""
    turns: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or set(line) <= set("=-_*# "):
            continue
        # Skip the export header lines produced by the backend data exporter.
        if re.match(r"^(call id|phone number|agent name|date & time|total duration|call status|audio file|qualification|reasoning|key signals|disposition)\s*:", line, re.IGNORECASE):
            continue
        m = _ROLE_RE.match(line)
        if m:
            role = "agent" if m.group(1).lower() in _AGENT_ROLES else "customer"
            current = {"role": role, "text": m.group(2).strip()}
            turns.append(current)
        elif current is not None:
            current["text"] = (current["text"] + " " + line).strip()
        else:
            current = {"role": "customer", "text": line}
            turns.append(current)
    return [t for t in turns if t["text"]]


def _customer_text(turns: List[Dict[str, str]]) -> str:
    return "\n".join(t["text"] for t in turns if t["role"] == "customer")


# ---------------------------------------------------------------------------
# 2. Built-in multilingual lexicon classifier (fallback, stdlib only)
#    English + Hindi (Roman & Devanagari) + Marathi cues — the languages this
#    product's calls actually happen in. Deterministic and explainable.
# ---------------------------------------------------------------------------

# (pattern, weight, signal-label). Searched in lower-cased customer text.
_POSITIVE_CUES: List[Tuple[str, int, str]] = [
    (r"\bi am interested\b|\bi'?m interested\b|\binterested hai\b|\binterest hai\b", 5, "explicit_interest"),
    (r"इंटरेस्टेड|मुझे चाहिए|चाहिए मुझे|बताइए|बताओ|पाहिजे|सांगा", 4, "explicit_interest_local"),
    (r"\bprice\b|\bcost\b|\bcharge|\brate kitna\b|\bkitne ka\b|\bhow much\b|कितना|कितने|किंमत", 3, "price_inquiry"),
    (r"\bdemo\b|\bpresentation\b|\bmeeting\b.*\b(fix|book|schedule|set)\b|\bbook\b.*\bdemo\b", 4, "demo_interest"),
    (r"\bsend\b.*\b(details|brochure|link|information|info)\b|\bdetails (bhej|send)|\bwhatsapp\b.*\b(details|bhej|send)\b|भेज दीजिए|भेजा", 3, "wants_details"),
    (r"\bsounds good\b|\bthat'?s good\b|\bgood offer\b|\bnice\b.*\boffer\b|\btheek hai\b|\bthik hai\b|\bachha hai\b|\bठीक है\b|\bबरं\b|\bचालेल\b", 3, "positive_response"),
    (r"\bi (need|want)\b|\bmujhe chahiye\b|\bhamare (liye|ko)\b.*\bchahiye\b|\bजरूर\b|\bनक्की\b", 3, "need_expressed"),
    (r"\bhow (do|can) i (start|join|buy|get|proceed)\b|\bnext step\b|\bsign up\b|\bbuy\b|\bproceed\b|\bgo ahead\b", 4, "ready_next_step"),
    (r"\btell me more\b|\bexplain\b|\baur batao\b|\bdetail mein\b", 2, "wants_information"),
    (r"\byes\b|\bhaan\b|\bhmm\b.*\bhaan\b|हो\b|होय", 1, "agreement"),
]

_NEGATIVE_CUES: List[Tuple[str, int, str]] = [
    (r"\bnot interested\b|\bno interest\b|नॉट इंटरेस्टेड|इंटरेस्ट नहीं|रुचि नहीं", 6, "explicit_not_interested"),
    (r"\bdo ?n'?t call\b|\bdo not call\b|\bstop calling\b|\bremove my number\b|\bnumber (delete|remove)\b|फोन मत करो|कॉल मत करो|परत फोन करू नका|\bdnc\b", 7, "opt_out"),
    (r"\bnahi chahiye\b|\bnai chahiye\b|\bnahi bolna\b|\bnahi lena\b|नहीं चाहिए|नको|नाही पाहिजे", 5, "refusal_local"),
    (r"\bno need\b|\bdon'?t need\b|\bno requirement\b|\bzarurat nahi\b|\bगरज नाही\b", 4, "no_need"),
    (r"\balready (have|using|taken|bought|purchased)\b|\balready subscribed\b|पहले से है|आधीच आहे", 4, "already_has"),
    (r"\btoo (expensive|costly|high)\b|\bprice (is )?too high\b|\bmehenga\b|\bमहंगा\b|\bमहाग\b|\bbudget nahi\b", 3, "price_objection"),
    (r"\b(busy|no time|fursat nahi)\b|\btime nahi\b|वेळ नाही|मीटिंग मध्ये", 3, "busy_no_time"),
    (r"\bwrong number\b|\bgalat number\b|\brong number\b|चुकीचा नंबर", 6, "wrong_number"),
    (r"\bscam\b|\bfraud\b|\bchor\b|\bfake (call|company)\b|धोखा|फ्रॉड", 4, "trust_concern"),
    (r"\bwho (is|are) (this|you)\b|\bkaun bol raha\b|\bkyu (call|phone) kiya\b", 2, "hostile_or_confused"),
    (r"\bcall (cut|band)\b|\bphone rakho\b|\bरख दो\b|\bcut the call\b", 4, "asked_to_hang_up"),
    (r"\bhe is not (here|available)\b|\bshe is not\b|\bnot available\b|\bmadam nahi\b|\bsir nahi hai\b", 3, "person_unavailable"),
]

_CALLBACK_CUES: List[Tuple[str, int, str]] = [
    (r"\bcall (me )?(later|back|tomorrow|after)\b|\bbaad mein (call|baat)\b|\bkal (call|baat|phone)\b|नंतर कॉल|नंतर बोला", 4, "callback_request"),
    (r"\bi'?ll (think|decide) and tell\b|\bsoch ke (bata|batata)\b|\bthink about it\b", 2, "will_think"),
]


# ---------------------------------------------------------------------------
# 2b. FIRST-QUESTION YES rule (business policy, added 2026-10-29):
#     "If he says YES to the 1st question, the lead must be shortlisted."
#     A bare "yes" is only a +1 agreement cue in the scoring below, so a
#     caller who said yes at Q1 and then answered factually used to land in
#     NEEDS_INFORMATION / UNCERTAIN and never got shortlisted. This rule
#     looks at the customer's FIRST substantive reply (skipping a bare
#     "hello") and, when it is an affirmative, shortlists the lead —
#     unless the customer anywhere showed a hard negative (opt-out /
#     explicit rejection / wrong number), which always wins.
# ---------------------------------------------------------------------------

_AFFIRMATIVE_START = re.compile(
    # NOTE: no \b after the group — Python's \b does not fire after a
    # Devanagari vowel sign (e.g. the ो in हो), so a bare "हो" never
    # matched. A lookahead for end/space/punctuation works for all scripts
    # and still rejects prefixes of longer words ("yesterday", "होता").
    r"^\s*(yes|yeah|yep|sure|ok|okay|haan|ha|ho|हाँ|हो|होय|जी|बरोबर|चालेल|"
    r"ठीक\s*है|theek\s*hai|thik\s*hai|बिल्कुल|bilkul|नक्की|nakki|हं|ह्म)"
    r"(?=$|[\s!.।,?;])",
    re.IGNORECASE,
)
_GREETING_ONLY_TURN = re.compile(
    r"^\s*(hello|hi|hey|हॅलो|हेलो|हाय|नमस्ते|नमस्कार)[\s!.।,]*$",
    re.IGNORECASE,
)
_HARD_NEGATIVE_LABELS = {"opt_out", "explicit_not_interested", "refusal_local", "wrong_number"}


_AUDIO_CHECK_RE = re.compile(r"(can\s+you\s+hear|audible|aawaz|awaaz|आवाज|ऐकू|सुन\s*पा\s*रहे)", re.IGNORECASE)

def first_question_yes_evidence(turns: List[Dict[str, str]]) -> Optional[str]:
    """Return the customer's first-answer utterance if it was a YES to the
    first question, else None. The first substantive customer turn is their
    answer to Q1 (the agent opens with greeting + Q1). Audio check turns are ignored."""
    last_agent_text = ""
    for t in turns:
        if t["role"] == "agent":
            last_agent_text = (t.get("text") or "").strip()
            continue
        if t["role"] != "customer":
            continue
        text = (t["text"] or "").strip()
        if not text or _GREETING_ONLY_TURN.match(text):
            continue
        # Audio check guard: do not classify 'can you hear me' -> 'yes' as Q1 YES
        if last_agent_text and _AUDIO_CHECK_RE.search(last_agent_text):
            return None
        if _AFFIRMATIVE_START.search(text.lower()):
            return text[:200]
        return None  # first real answer was not an affirmative
    return None


def _has_hard_negative(turns: List[Dict[str, str]]) -> bool:
    """Engine-independent hard-negative check (opt-out / explicit no /
    wrong number) using the builtin cue tables on ALL customer speech."""
    cust = _customer_text(turns)
    if not cust.strip():
        return False
    _, neg_signals = _score_cues(" " + cust.lower() + " ", _NEGATIVE_CUES)
    return bool(_HARD_NEGATIVE_LABELS & set(neg_signals))


def _score_cues(text_low: str, cues: List[Tuple[str, int, str]]) -> Tuple[int, List[str]]:
    score, signals = 0, []
    for pattern, weight, label in cues:
        if re.search(pattern, text_low):
            score += weight
            signals.append(label)
    return score, signals


def _builtin_classify(turns: List[Dict[str, str]]) -> Dict[str, Any]:
    """Deterministic fallback classifier. Returns the same shape the repo
    classifier produces, so callers don't care which engine ran."""
    cust = _customer_text(turns)
    low = " " + cust.lower() + " "
    if not cust.strip():
        return {"classification": "UNCERTAIN", "binary": "NOT_INTERESTED",
                "confidence": 0.30, "interest_strength": "UNKNOWN",
                "reason": "No customer speech found in the transcript.",
                "rule_applied": "builtin:no_customer_speech", "signals": [],
                "opt_out": False, "callback": False, "engine": "builtin_lexicon"}

    pos, pos_signals = _score_cues(low, _POSITIVE_CUES)
    neg, neg_signals = _score_cues(low, _NEGATIVE_CUES)
    cb, cb_signals = _score_cues(low, _CALLBACK_CUES)

    opt_out = "opt_out" in neg_signals
    explicit_no = "explicit_not_interested" in neg_signals or "refusal_local" in neg_signals

    if opt_out:
        cls, conf, strength = "NOT_INTERESTED", 0.97, "NONE"
        reason = "Customer explicitly asked not to be called again (opt-out / DNC)."
        rule = "builtin:opt_out_override"
    elif explicit_no and pos < 5:
        cls, conf, strength = "NOT_INTERESTED", 0.93, "NONE"
        reason = "Customer explicitly said they are not interested."
        rule = "builtin:explicit_rejection"
    elif "wrong_number" in neg_signals:
        cls, conf, strength = "NOT_INTERESTED", 0.95, "NONE"
        reason = "Customer said this is a wrong number."
        rule = "builtin:wrong_number"
    elif pos >= 5 and pos > neg + 1:
        cls, conf = "INTERESTED", min(0.97, 0.65 + pos * 0.04)
        strength = "HIGH" if pos >= 8 else "MEDIUM"
        reason = "Customer showed clear positive buying signals: " + ", ".join(pos_signals) + "."
        rule = "builtin:positive_signals"
    elif cb >= 4 and neg <= 3:
        cls, conf, strength = "CALLBACK_REQUESTED", 0.85, "MEDIUM"
        reason = "Customer asked to be called back later without rejecting the offer."
        rule = "builtin:callback_request"
    elif neg >= 4 and neg > pos:
        cls, conf, strength = "NOT_INTERESTED", min(0.95, 0.60 + neg * 0.04), "NONE"
        reason = "Customer's responses were mainly negative: " + ", ".join(neg_signals) + "."
        rule = "builtin:negative_signals"
    elif pos >= 2:
        cls, conf, strength = "NEEDS_INFORMATION", 0.62, "LOW"
        reason = "Customer engaged and asked questions but did not commit."
        rule = "builtin:engaged_uncommitted"
    elif neg >= 2:
        cls, conf, strength = "NOT_INTERESTED", 0.66, "NONE"
        reason = "Customer leaned negative: " + ", ".join(neg_signals) + "."
        rule = "builtin:leaning_negative"
    else:
        cls, conf, strength = "UNCERTAIN", 0.45, "UNKNOWN"
        reason = "Not enough customer signal in the transcript to decide."
        rule = "builtin:insufficient_signal"

    return {"classification": cls,
            "binary": "INTERESTED" if cls in ("INTERESTED", "NEEDS_INFORMATION") else "NOT_INTERESTED",
            "confidence": round(float(conf), 3), "interest_strength": strength,
            "reason": reason, "rule_applied": rule,
            "signals": pos_signals + neg_signals + cb_signals,
            "opt_out": opt_out, "callback": cls == "CALLBACK_REQUESTED" or cb >= 4,
            "engine": "builtin_lexicon"}


def _repo_classify(turns: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """Use the repo's richer classifier when importable (needs pydantic)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from classifier.engine import IntentClassifier  # type: ignore

        text = "\n".join(
            ("Agent: " if t["role"] == "agent" else "Customer: ") + t["text"] for t in turns
        )
        res = IntentClassifier().classify_detailed(text)
        return {"classification": res.classification.value,
                "binary": res.binary_classification or (
                    "INTERESTED" if res.classification.value in ("INTERESTED", "NEEDS_INFORMATION") else "NOT_INTERESTED"),
                "confidence": round(float(res.confidence), 3),
                "interest_strength": res.interest_strength.value,
                "reason": res.reason, "rule_applied": res.rule_applied,
                "signals": list(res.signals_detected or []),
                "opt_out": bool(res.opt_out_detected),
                "callback": bool(res.callback_requested),
                "engine": "repo_classifier"}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 3. Customer information extraction (from CUSTOMER turns only, so the
#    agent's pitch never contaminates the customer's details)
# ---------------------------------------------------------------------------

_NAME_STOPWORDS = {
    "interested", "not", "busy", "fine", "good", "okay", "ok", "sorry", "the",
    "a", "an", "calling", "here", "speaking", "happy", "glad", "from", "in",
    "very", "really", "just", "now", "available", "unavailable", "driving",
    "working", "sleeping", "eating", "out", "at", "on", "this", "that",
}

_INDIAN_CITIES = [
    "Mumbai", "Delhi", "New Delhi", "Bengaluru", "Bangalore", "Hyderabad",
    "Chennai", "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Surat", "Lucknow",
    "Kanpur", "Nagpur", "Indore", "Thane", "Bhopal", "Patna", "Vadodara",
    "Ghaziabad", "Ludhiana", "Agra", "Nashik", "Faridabad", "Meerut",
    "Rajkot", "Varanasi", "Aurangabad", "Amravati", "Akola", "Solapur",
    "Kolhapur", "Satara", "Sangli", "Jalgaon", "Nanded", "Latur", "Wardha",
    "Yavatmal", "Chandrapur", "Coimbatore", "Madurai", "Kochi", "Cochin",
    "Mysore", "Mysuru", "Hubli", "Mangaluru", "Vizag", "Visakhapatnam",
    "Vijayawada", "Guntur", "Warangal", "Ranchi", "Jamshedpur", "Guwahati",
    "Bhubaneswar", "Raipur", "Udaipur", "Jodhpur", "Kota", "Ajmer",
    "Dehradun", "Haridwar", "Shimla", "Jammu", "Srinagar", "Amritsar",
    "Chandigarh", "Panaji", "Goa", "Noida", "Gurgaon", "Gurugram",
]


def _clean_name(raw: str) -> Optional[str]:
    words = [w for w in re.split(r"\s+", raw.strip(" .,\"'")) if w]
    words = [w for w in words if w.lower() not in _NAME_STOPWORDS]
    if not words or len(words) > 3:
        return None
    if any(not re.match(r"^[A-Za-z\u0900-\u097F'.-]+$", w) for w in words):
        return None
    return " ".join(w.capitalize() if w.isascii() else w for w in words)


def _extract_name(cust_text: str) -> Optional[str]:
    patterns = [
        r"my name is\s+([A-Za-z]+(?: [A-Za-z]+){0,2})",
        r"mera naam\s+([A-Za-z]+(?: [A-Za-z]+){0,2})(?:\s+hai|\s+he|\.|,|$)",
        r"मेरा नाम\s+([\u0900-\u097F]+(?: [\u0900-\u097F]+){0,2})\s*(?:है|आहे)",
        r"this is\s+([A-Za-z]+(?: [A-Za-z]+){0,2})\s*(?:speaking|here|calling)?",
        r"(?:^|[.!]\s)i am\s+([A-Za-z]+(?: [A-Za-z]+){0,2})",
        r"माझं नाव\s+([\u0900-\u097F]+(?: [\u0900-\u097F]+){0,2})\s*(?:आहे|है)",
    ]
    for pat in patterns:
        m = re.search(pat, cust_text, re.IGNORECASE)
        if m:
            name = _clean_name(m.group(1))
            if name:
                return name
    return None


def _extract_phone(full_text: str) -> Optional[str]:
    text = re.sub(r"(?<=\d)[\s.-]+(?=\d)", " ", full_text)
    m = re.search(r"(?:\+?91[\s-]?)?([6-9]\d{9})\b", text.replace(" ", ""))
    if m:
        return "+91" + m.group(1)
    m = re.search(r"\b([6-9]\d{4})\s(\d{5})\b", text)
    if m:
        return "+91" + m.group(1) + m.group(2)
    return None


def _extract_budget(cust_text: str) -> Dict[str, Any]:
    low = cust_text.lower()
    mult = {"lakh": 100000, "lac": 100000, "crore": 10000000, "cr": 10000000,
            "thousand": 1000, "k": 1000, "hazaar": 1000, "हजार": 1000, "लाख": 100000}
    patterns = [
        r"(?:₹|rs\.?|inr|rupees?)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|cr|thousand|k|हजार|लाख)?(?![a-z])",
        r"([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|cr|thousand|k|हजार|लाख)(?![a-z])\s*(?:rupees?|rs|₹|budget)?",
        r"budget\s*(?:is|of|hai|:)?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|cr|thousand|k)?(?![a-z])",
    ]
    for pat in patterns:
        m = re.search(pat, low)
        if m:
            try:
                amount = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            factor = mult.get(m.group(2) or "", 1)
            return {"budget_inr": int(amount * factor), "budget_raw": m.group(0).strip()}
    return {"budget_inr": None, "budget_raw": None}


def _extract_callback_time(cust_text: str) -> Optional[str]:
    m = re.search(
        r"((?:call (?:me )?(?:back )?(?:later|tomorrow|today|in the evening|in the morning|after \d+[^.,]*)"
        r"|baad mein call[^.,]*|kal (?:subah|shaam|call)[^.,]*"
        r"|tomorrow (?:at|by|morning|evening)[^.,]*"
        r"|(?:at|by) \d{1,2}(?::\d{2})?\s*(?:am|pm)[^.,]*))",
        cust_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    low = cust_text.lower()
    for hint in ("tomorrow", "kal ", "evening", "shaam", "morning", "subah", "sunday", "monday"):
        if hint.strip() in low and ("call" in low or "बोला" in low or "call karo" in low):
            return hint.strip()
    return None


def extract_customer_info(turns: List[Dict[str, str]], full_text: str) -> Dict[str, Any]:
    """Pull every customer detail actually stated in the conversation."""
    cust = _customer_text(turns)
    info: Dict[str, Any] = {}

    info["name"] = _extract_name(cust)

    email_m = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", cust)
    info["email"] = email_m.group(0) if email_m else None

    info["phone"] = _extract_phone(full_text)

    city = None
    m = re.search(r"(?:i (?:live|stay) in|i am from|i'?m from|from)\s+([A-Z][a-z]+)", cust)
    if m and m.group(1) in _INDIAN_CITIES:
        city = m.group(1)
    if not city:
        for c in _INDIAN_CITIES:
            if re.search(r"\b" + re.escape(c) + r"\b", cust, re.IGNORECASE):
                city = c
                break
    info["city"] = city

    info.update(_extract_budget(cust))

    info["preferred_callback_time"] = _extract_callback_time(cust)

    prod = None
    m = re.search(r"interested in (?:the |your |this )?([a-z][a-z0-9 /-]{2,40}?)(?:\.|,| plan| product| service|$)",
                  cust, re.IGNORECASE)
    if m and m.group(1).strip().lower() not in ("this", "it", "that"):
        prod = m.group(1).strip()
    info["product_interest"] = prod

    biz = None
    m = re.search(r"i (?:run|own|have) a[n]?\s+([a-z][a-z ]{2,30}?)(?:\.|,|business|shop|store|$)",
                  cust, re.IGNORECASE)
    if m:
        biz = m.group(1).strip()
    else:
        m = re.search(r"my (shop|company|business|store) (?:is|name is)\s+([A-Za-z0-9 &]{2,40})",
                      cust, re.IGNORECASE)
        if m:
            biz = m.group(2).strip()
    info["business_type"] = biz

    info["fields_found"] = [k for k, v in info.items() if v not in (None, "", [])]
    return info


# ---------------------------------------------------------------------------
# 4. WHY — categorized reasons, each with the customer's exact words as proof
# ---------------------------------------------------------------------------

_INTEREST_REASONS: List[Tuple[str, str, str]] = [
    ("price_inquiry", "Asked about price / cost",
     r"\bprice\b|\bcost\b|\bhow much\b|rate kitna|kitne ka|कितना|किंमत"),
    ("demo_agreed", "Agreed to a demo / meeting / next step",
     r"\bdemo\b|\bbook (a|the)? ?(demo|meeting|appointment)\b|\bschedule\b|\bvisit\b.*\b(come|kar)"),
    ("wants_details", "Asked for details to be sent (WhatsApp / brochure / link)",
     r"send.*(details|brochure|link|info)|details (bhej|send)|whatsapp.*(details|bhej)|भेज दीजिए|भेजा"),
    ("need_expressed", "Expressed a need the product solves",
     r"i (need|want)|mujhe chahiye|hamare liye chahiye|मुझे चाहिए|पाहिजे"),
    ("positive_response", "Responded positively to the offer",
     r"sounds good|that'?s good|good offer|theek hai|thik hai|achha hai|ठीक है|चालेल|बरं"),
    ("ready_to_proceed", "Ready to proceed / buy / sign up",
     r"sign up|go ahead|let'?s proceed|proceed|buy karna|लेना है|घ्यायचं आहे"),
    ("asked_more_info", "Engaged — asked for more information",
     r"tell me more|explain|aur batao|detail mein|बताइए|बताओ|सांगा"),
    ("callback_positive", "Asked for a callback and stayed positive",
     r"call (me )?(later|back|tomorrow)|baad mein call|kal call|नंतर कॉल"),
]

_REJECTION_REASONS: List[Tuple[str, str, str]] = [
    ("explicit_no", "Clearly said not interested",
     r"not interested|नॉट इंटरेस्टेड|रुचि नहीं|nahi chahiye|नहीं चाहिए|नको"),
    ("opt_out", "Opt-out — asked never to be called again (DNC)",
     r"do ?n'?t call|do not call|stop calling|remove my number|फोन मत करो|कॉल मत करो"),
    ("already_has", "Already has / uses a similar product",
     r"already (have|using|taken|bought)|पहले से है|आधीच आहे"),
    ("price_too_high", "Price too high / no budget",
     r"too (expensive|costly|high)|mehenga|महंगा|महाग|budget nahi"),
    ("no_need", "Has no need for it",
     r"no need|don'?t need|no requirement|zarurat nahi|गरज नाही"),
    ("busy_no_time", "Busy / no time right now",
     r"\bbusy\b|no time|fursat nahi|time nahi|वेळ नाही"),
    ("trust_concern", "Trust concern — thinks it may be a scam/fraud",
     r"\bscam\b|\bfraud\b|\bfake\b|धोखा|फ्रॉड"),
    ("wrong_number", "Wrong number",
     r"wrong number|galat number|rong number|चुकीचा नंबर"),
    ("person_unavailable", "Decision-maker not available (gatekeeper)",
     r"he is not (here|available)|she is not|not available|sir nahi hai|madam nahi"),
    ("asked_to_hang_up", "Asked to end the call",
     r"cut the call|phone rakho|रख दो|call band"),
]


def _reasons_for(turns: List[Dict[str, str]], table: List[Tuple[str, str, str]]) -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    seen = set()
    for t in turns:
        if t["role"] != "customer":
            continue
        for code, label, pattern in table:
            if code in seen:
                continue
            if re.search(pattern, t["text"], re.IGNORECASE):
                found.append({"code": code, "reason": label,
                              "evidence": t["text"].strip()[:200]})
                seen.add(code)
    return found


# ---------------------------------------------------------------------------
# 5. Lead score + full analysis
# ---------------------------------------------------------------------------

def _lead_score(cls: Dict[str, Any], info: Dict[str, Any],
                why_in: List[Dict[str, str]]) -> int:
    if cls["opt_out"]:
        return 0
    c = cls["classification"]
    if c == "INTERESTED":
        score = 55 + int(cls["confidence"] * 25)
        codes = {r["code"] for r in why_in}
        if "demo_agreed" in codes:
            score += 10
        if "price_inquiry" in codes:
            score += 5
        if info.get("phone") or info.get("email"):
            score += 5
        return min(score, 98)
    if c == "CALLBACK_REQUESTED":
        return 58
    if c == "NEEDS_INFORMATION":
        return 48
    if c == "NOT_INTERESTED":
        return 8 if "wrong_number" not in str(cls["signals"]) else 2
    return 30


def analyze_transcript(text: str, source: str = "") -> Dict[str, Any]:
    """Analyze one transcript. Pure stdlib; safe to call per-call in the
    backend or in bulk from the CLI."""
    turns = parse_transcript(text)
    cls = _repo_classify(turns) or _builtin_classify(turns)
    info = extract_customer_info(turns, text)
    why_in = _reasons_for(turns, _INTEREST_REASONS)
    why_not = _reasons_for(turns, _REJECTION_REASONS)

    # FIRST-QUESTION YES policy: a YES to Q1 shortlists the lead at once,
    # whichever engine classified the call — unless a hard negative exists.
    fq_yes_quote = first_question_yes_evidence(turns)
    first_q_yes = bool(fq_yes_quote) and not _has_hard_negative(turns) and not cls["opt_out"]
    if first_q_yes:
        why_in.insert(0, {
            "code": "first_question_yes",
            "reason": "Said YES to the very first question — shortlisted immediately",
            "evidence": fq_yes_quote or "",
        })
        if cls["classification"] != "INTERESTED":
            cls = {**cls,
                   "classification": "INTERESTED",
                   "binary": "INTERESTED",
                   "confidence": max(float(cls["confidence"]), 0.92),
                   "interest_strength": "HIGH",
                   "reason": (f"Customer said YES to the first question "
                              f"(\"{fq_yes_quote}\") — shortlisted at question 1. "
                              + cls["reason"]),
                   "rule_applied": cls["rule_applied"] + "+first_question_yes"}

    if cls["classification"] in ("INTERESTED", "NEEDS_INFORMATION", "CALLBACK_REQUESTED"):
        summary_reason = cls["reason"]
        if why_in:
            summary_reason += " Evidence: " + "; ".join(
                f"{r['reason']} (\"{r['evidence']}\")" for r in why_in[:3])
    else:
        summary_reason = cls["reason"]
        if why_not:
            summary_reason += " Evidence: " + "; ".join(
                f"{r['reason']} (\"{r['evidence']}\")" for r in why_not[:3])

    return {
        "source": source,
        "classification": cls["classification"],
        "status": {"INTERESTED": "interested", "NOT_INTERESTED": "not_interested",
                   "CALLBACK_REQUESTED": "callback_requested",
                   "NEEDS_INFORMATION": "needs_information",
                   "UNCERTAIN": "uncertain"}[cls["classification"]],
        "binary": cls["binary"],
        "confidence": cls["confidence"],
        "interest_strength": cls["interest_strength"],
        "lead_score": _lead_score(cls, info, why_in),
        "reason_summary": summary_reason,
        "why_interested": why_in,
        "why_not_interested": why_not,
        "signals": cls["signals"],
        "opt_out_do_not_call": cls["opt_out"],
        "first_question_yes": first_q_yes,
        "callback_requested": cls["callback"],
        "customer_info": info,
        "customer_turns": sum(1 for t in turns if t["role"] == "customer"),
        "total_turns": len(turns),
        "engine": cls["engine"],
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "analyzer_version": __version__,
    }


# ---------------------------------------------------------------------------
# 6. Excel export — a real .xlsx written with ONLY the standard library
#    (zipfile + XML), so downloads work on any PC with zero installs.
# ---------------------------------------------------------------------------

COLUMNS: List[Tuple[str, str, int]] = [
    # (header, result-key or dotted path, column width)
    ("Source", "source", 28),
    ("Customer Name", "customer_info.name", 20),
    ("Phone", "customer_info.phone", 16),
    ("Email", "customer_info.email", 26),
    ("City", "customer_info.city", 14),
    ("Budget (INR)", "customer_info.budget_inr", 13),
    ("Budget (as said)", "customer_info.budget_raw", 16),
    ("Product Interest", "customer_info.product_interest", 22),
    ("Business Type", "customer_info.business_type", 18),
    ("Classification", "classification", 18),
    ("Status", "status", 16),
    ("Lead Score", "lead_score", 10),
    ("Confidence", "confidence", 11),
    ("Interest Strength", "interest_strength", 13),
    ("Why Interested", "why_interested", 46),
    ("Why Not Interested", "why_not_interested", 46),
    ("Reason Summary", "reason_summary", 60),
    ("Preferred Callback Time", "customer_info.preferred_callback_time", 20),
    ("Do Not Call", "opt_out_do_not_call", 11),
    ("Analyzed At (UTC)", "analyzed_at", 20),
]


def _get(row: Dict[str, Any], path: str) -> Any:
    cur: Any = row
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    if isinstance(cur, list):  # reason lists -> "Label — "evidence"" text
        return "; ".join(
            f"{r.get('reason', '')} — \"{r.get('evidence', '')}\"" if isinstance(r, dict) else str(r)
            for r in cur)
    if isinstance(cur, bool):
        return "YES" if cur else "NO"
    return cur


def _filter_rows(results: List[Dict[str, Any]], which: str) -> List[Dict[str, Any]]:
    if which == "interested":
        return [r for r in results if r["binary"] == "INTERESTED"]
    if which == "not_interested":
        return [r for r in results if r["classification"] == "NOT_INTERESTED"]
    if which == "followups":
        return [r for r in results if r["classification"] in
                ("CALLBACK_REQUESTED", "NEEDS_INFORMATION")]
    return list(results)


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def _sheet_xml(rows: List[Dict[str, Any]]) -> str:
    last_col = _col_letter(len(COLUMNS))
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           "<cols>"]
    for i, (_, _, w) in enumerate(COLUMNS, start=1):
        out.append(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>')
    out.append("</cols>")
    out.append(f'<sheetViews><sheetView workbookViewId="0">'
               f'<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
               f"</sheetView></sheetViews>")
    out.append("<sheetData>")
    # header
    cells = []
    for i, (header, _, _) in enumerate(COLUMNS, start=1):
        cells.append(f'<c r="{_col_letter(i)}1" t="inlineStr" s="1"><is><t>{xml_escape(header)}</t></is></c>')
    out.append('<row r="1">' + "".join(cells) + "</row>")
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, (_, path, _) in enumerate(COLUMNS, start=1):
            val = _get(row, path)
            if val is None or val == "":
                continue
            ref = f"{_col_letter(c_idx)}{r_idx + 1}"
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cells.append(f'<c r="{ref}"><v>{val}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(str(val))}</t></is></c>')
        out.append(f'<row r="{r_idx + 1}">' + "".join(cells) + "</row>")
    out.append("</sheetData>")
    out.append(f'<autoFilter ref="A1:{last_col}{max(1, len(rows) + 1)}"/>')
    out.append("</worksheet>")
    return "".join(out)


def export_excel(results: List[Dict[str, Any]], path: str, which: str = "all") -> str:
    """Write a workbook. which='all' -> sheets: All / Interested /
    Not Interested / Follow-ups. A specific filter -> a single sheet."""
    if which == "all":
        sheets = [("All Results", results),
                  ("Interested", _filter_rows(results, "interested")),
                  ("Not Interested", _filter_rows(results, "not_interested")),
                  ("Follow-ups", _filter_rows(results, "followups"))]
    else:
        sheets = [(which.replace("_", " ").title(), _filter_rows(results, which))]

    content_types = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                     '<Default Extension="xml" ContentType="application/xml"/>',
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    for i in range(len(sheets)):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    content_types.append("</Types>")

    workbook = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
    for i, (name, _) in enumerate(sheets):
        workbook.append(f'<sheet name="{xml_escape(name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>')
    workbook.append("</sheets></workbook>")

    wb_rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i in range(len(sheets)):
        wb_rels.append(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>')
    wb_rels.append(f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
    wb_rels.append("</Relationships>")

    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill>'
              '<fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border/></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')

    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 "</Relationships>")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(content_types))
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", "".join(workbook))
        z.writestr("xl/_rels/workbook.xml.rels", "".join(wb_rels))
        z.writestr("xl/styles.xml", styles)
        for i, (_, rows) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(rows))
    return path


def export_csv(results: List[Dict[str, Any]], path: str, which: str = "all") -> str:
    rows = _filter_rows(results, which)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([h for h, _, _ in COLUMNS])
    for row in rows:
        writer.writerow([_get(row, p) if _get(row, p) is not None else "" for _, p, _ in COLUMNS])
    Path(path).write_text(buf.getvalue(), encoding="utf-8-sig")
    return path


# ---------------------------------------------------------------------------
# 7. CLI
# ---------------------------------------------------------------------------

def _load_inputs(args: argparse.Namespace) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    for f in args.files or []:
        p = Path(f)
        items.append((p.name, p.read_text(encoding="utf-8", errors="ignore")))
    if args.dir:
        for p in sorted(Path(args.dir).glob("*.txt")):
            items.append((p.name, p.read_text(encoding="utf-8", errors="ignore")))
        for p in sorted(Path(args.dir).glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
                segs = data.get("segments") or []
                if segs:
                    text = "\n".join(
                        ("Agent: " if (s.get("speaker") in ("agent", "bot", "assistant")) else "Customer: ")
                        + (s.get("text") or "") for s in segs)
                    items.append((p.name, text))
            except Exception:
                pass
    if args.text:
        items.append(("inline", args.text))
    return items


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Offline transcript analyzer: interested / not interested, "
                    "WHY, customer-info extraction, Excel export.")
    ap.add_argument("files", nargs="*", help="Transcript .txt files")
    ap.add_argument("--dir", help="Folder of transcript .txt/.json files (e.g. data/transcripts)")
    ap.add_argument("--text", help="Analyze a raw transcript string directly")
    ap.add_argument("--excel", help="Write Excel workbook to this .xlsx path")
    ap.add_argument("--csv", help="Also write a CSV to this path")
    ap.add_argument("--json", help="Also write full JSON results to this path")
    ap.add_argument("--filter", default="all",
                    choices=["all", "interested", "not_interested", "followups"],
                    help="Which rows go into the Excel/CSV export (default: all, "
                         "with separate Interested / Not Interested sheets)")
    args = ap.parse_args(argv)

    items = _load_inputs(args)
    if not items:
        ap.print_help()
        return 1

    results = [analyze_transcript(text, source=name) for name, text in items]

    for r in results:
        ci = r["customer_info"]
        print(f"{r['source'] or 'transcript'}: {r['classification']} "
              f"(score {r['lead_score']}, confidence {r['confidence']:.0%}, engine {r['engine']})")
        print(f"  why: {r['reason_summary']}")
        found = {k: v for k, v in ci.items() if k != 'fields_found' and v}
        if found:
            print(f"  customer info: {found}")

    if args.excel:
        export_excel(results, args.excel, args.filter)
        print(f"Excel written: {args.excel} ({len(results)} analyzed, filter={args.filter})")
    if args.csv:
        export_csv(results, args.csv, args.filter)
        print(f"CSV written: {args.csv}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON written: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
