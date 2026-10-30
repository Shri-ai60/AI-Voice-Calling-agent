"""
Offline callback-time understanding for automatic rescheduling.

Stdlib only — no API keys, no network, runs on any machine (including Windows without tzdata).

Two jobs:
1. ``parse_callback_time`` — turn what the customer said on the call
   ("call me tomorrow at 5 pm", "kal shaam ko 6 baje", "2 ghante baad",
   "udya sakali phone kara", "कल सुबह दस बजे", "उद्या सकाळी १० वाजता") into a concrete local datetime.
2. ``next_working_slot`` — move that moment inside working hours
   (09:00–19:00, Asia/Kolkata): requests before 09:00 are called at
   09:00 the same day; requests at/after 19:00 are called at 09:00 the
   NEXT day, so an out-of-hours promise never fires at night.
"""

from __future__ import annotations

import re
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=5, minutes=30), name="IST")

WORK_START = dtime(9, 0)
WORK_END = dtime(19, 0)
# Never schedule in the immediate next minutes — the customer just hung up.
MIN_LEAD = timedelta(minutes=10)

_WEEKDAYS = {
    "monday": 0, "somvaar": 0, "somvar": 0, "सोमवार": 0,
    "tuesday": 1, "mangalvaar": 1, "mangalvar": 1, "मंगळवार": 1, "मंगलवार": 1,
    "wednesday": 2, "budhvaar": 2, "budhvar": 2, "बुधवार": 2,
    "thursday": 3, "guruvaar": 3, "guruvar": 3, "गुरुवार": 3,
    "friday": 4, "shukravaar": 4, "shukravar": 4, "शुक्रवार": 4,
    "saturday": 5, "shanivaar": 5, "shanivar": 5, "शनिवार": 5,
    "sunday": 6, "ravivaar": 6, "ravivar": 6, "रविवार": 6,
}

_DAYPARTS = [
    (re.compile(r"(subah|sakali|sakal|morning|सुबह|सकाळी|सकाळ)", re.IGNORECASE), dtime(10, 0)),
    (re.compile(r"(dopahar|dupari|afternoon|lunch|दोपहर|दुपारी)", re.IGNORECASE), dtime(13, 30)),
    (re.compile(r"(shaam|sandhya|sandhyakal|evening|शाम|संध्याकाळी|सांध्य)", re.IGNORECASE), dtime(17, 30)),
    (re.compile(r"(raat|ratri|night|रात|रात्री)", re.IGNORECASE), dtime(19, 0)),
]

_INDIC_DIGITS = {
    '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
    '५': '5', '६': '6', '७': '7', '८': '8', '९': '9',
}

_INDIC_WORDS = {
    "एक": 1, "ek": 1, "one": 1,
    "दोन": 2, "दो": 2, "do": 2, "don": 2, "two": 2,
    "तीन": 3, "teen": 3, "three": 3,
    "चार": 4, "char": 4, "four": 4,
    "पाच": 5, "पांच": 5, "paanch": 5, "pach": 5, "five": 5,
    "सहा": 6, "छह": 6, "chhe": 6, "saha": 6, "six": 6,
    "सात": 7, "saat": 7, "seven": 7,
    "आठ": 8, "aath": 8, "eight": 8,
    "नऊ": 9, "नौ": 9, "nau": 9, "nine": 9,
    "दहा": 10, "दस": 10, "das": 10, "daha": 10, "ten": 10,
    "अकरा": 11, "ग्यारह": 11, "gyarah": 11, "akara": 11, "eleven": 11,
    "बारा": 12, "बारह": 12, "barah": 12, "bara": 12, "twelve": 12,
}


def _normalize_text(text: str) -> str:
    """Replaces Devanagari digits with ASCII and converts word numerals before clock markers."""
    t = text.lower()
    for dv, asc in _INDIC_DIGITS.items():
        t = t.replace(dv, asc)
    for w, n in _INDIC_WORDS.items():
        t = re.sub(rf'(?:^|\s){w}\s*(baje|बजे|वाजता|vajta|waje|pm|am|o\'clock)(?:\s|$|[.,!?])', f' {n} \\1 ', t)
    return t


def _customer_text(transcript: str) -> str:
    """Use only customer lines when role prefixes exist (like the detector)."""
    lines = []
    has_roles = False
    for line in transcript.split("\n"):
        s = line.strip()
        low = s.lower()
        if any(low.startswith(p) for p in ("customer:", "user:", "client:", "caller:")):
            has_roles = True
            lines.append(s.split(":", 1)[1].strip())
        elif any(low.startswith(p) for p in ("agent:", "assistant:", "bot:")):
            has_roles = True
    if has_roles and lines:
        return " ".join(lines)
    return transcript


def _parse_clock(text: str) -> Optional[dtime]:
    """Extract a time-of-day from '5 pm', '17:30', '6 baje', '10 वाजता', daypart words."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(3).lower() == "pm":
            hour += 12
        return dtime(hour, int(m.group(2) or 0))

    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if m:
        return dtime(int(m.group(1)), int(m.group(2)))

    m = re.search(r"(\d{1,2})\s*(baje|बजे|वाजता|vajta|waje)\b", text, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        if re.search(r"(subah|sakali|morning|सुबह|सकाळी)", text, re.IGNORECASE):
            return dtime(hour % 12, 0)
        if re.search(r"(shaam|sandhya|evening|raat|night|शाम|संध्याकाळी|रात)", text, re.IGNORECASE):
            return dtime(hour % 12 + 12 if hour != 12 else 12, 0)
        # Bare "5 baje" in Indian usage almost always means the evening;
        # 7–11 stays morning, 12 is noon.
        if 1 <= hour <= 6:
            return dtime(hour + 12, 0)
        return dtime(hour, 0)

    for pattern, t in _DAYPARTS:
        if pattern.search(text):
            return t
    return None


def parse_callback_time(transcript: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """
    Parse the customer's requested callback moment from a transcript.
    Returns a timezone-aware datetime in Asia/Kolkata (NOT yet adjusted
    to working hours), or None when no time was mentioned.
    """
    if not transcript or not transcript.strip():
        return None
    now = now or datetime.now(LOCAL_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=LOCAL_TZ)
    text = _normalize_text(_customer_text(transcript))

    # 1) Relative offsets: "in 2 hours", "30 minutes later", "2 ghante baad", "२ तासाने", "अर्ध्या तासाने"
    m = re.search(r"\bin\s+(\d+)\s*(minutes?|mins?|hours?|hrs?|days?)\b", text, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d+)\s*(ghante|ghanta|hours?|hrs?|minutes?|mins?|तास|तासाने|तासात|मिनिटे|मिनिटात)\s*(baad|later|after|नंतर)?", text, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = (m.group(2) or "").lower()
        if any(unit.startswith(p) for p in ("hour", "hr", "ghant", "तास")):
            return now + timedelta(hours=n)
        if any(unit.startswith(p) for p in ("day", "दिवस")):
            return now + timedelta(days=n)
        return now + timedelta(minutes=n)

    if re.search(r"(aadha|half|अर्धा|अर्ध्या)\s*(ghanta|hour|तास)", text, re.IGNORECASE):
        return now + timedelta(minutes=30)

    # 2) Day selection (Hindi, Marathi, English)
    day_offset: Optional[int] = None
    if re.search(r"(day after tomorrow|parso|parwa|परसों|परवा)", text, re.IGNORECASE):
        day_offset = 2
    elif re.search(r"(tomorrow|kal|udya|udiya|कल|उद्या)", text, re.IGNORECASE):
        day_offset = 1
    elif re.search(r"(today|aaj|aata|आज|आत्ता)", text, re.IGNORECASE):
        day_offset = 0
    elif re.search(r"(next week|पुढच्या आठवड्यात|अगले हफ्ते)", text, re.IGNORECASE):
        day_offset = 7
    else:
        for name, weekday in _WEEKDAYS.items():
            if re.search(rf"\b{name}\b", text, re.IGNORECASE):
                day_offset = (weekday - now.weekday()) % 7
                break

    clock = _parse_clock(text)

    # 3) Generic "call later" / "नंतर फोन करा" / "बाद में कॉल करो" with no explicit day or time
    is_generic_callback = any(k in text for k in (
        "बाद में कॉल", "बाद में फोन", "नंतर फोन", "नंतर कॉल", "नंतर बोला", "नंतर सांगा",
        "वेळ नाही", "टाइम नाही", "टाइम नही", "बाद में बात", "call later", "call me later",
        "busy right now", "नंतर करा", "बाद में करना", "नंतर सांगतो"
    ))

    if day_offset is None and clock is None:
        if is_generic_callback:
            # Default to 2 hours later
            return now + timedelta(hours=2)
        return None

    base_date = now.date() + timedelta(days=day_offset or 0)
    if clock is None:
        # A day with no time: late morning is the safest default (10:30 AM).
        clock = dtime(10, 30)
    result = datetime.combine(base_date, clock, tzinfo=LOCAL_TZ)

    # A bare clock time ("call at 5 pm") with no day means today when it
    # is still ahead, otherwise tomorrow.
    if day_offset is None and result <= now:
        result += timedelta(days=1)
    return result


def next_working_slot(desired: datetime, now: Optional[datetime] = None) -> datetime:
    """
    Move a desired callback moment into working hours (09:00–19:00 IST):
    before 09:00 → 09:00 the same day; at/after 19:00 → 09:00 the next
    day. Moments already past roll forward to the next valid slot.
    """
    now = now or datetime.now(LOCAL_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=LOCAL_TZ)
    candidate = desired
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=LOCAL_TZ)
    candidate = candidate.astimezone(LOCAL_TZ)

    earliest = now + MIN_LEAD
    if candidate < earliest:
        candidate = earliest

    for _ in range(4):
        t = candidate.time()
        if t < WORK_START:
            candidate = candidate.replace(hour=WORK_START.hour, minute=0, second=0, microsecond=0)
        elif t >= WORK_END:
            candidate = (candidate + timedelta(days=1)).replace(hour=WORK_START.hour, minute=0, second=0, microsecond=0)
        else:
            break
        if candidate < earliest:
            candidate = (candidate + timedelta(days=1)).replace(hour=WORK_START.hour, minute=0, second=0, microsecond=0)
    return candidate


def schedule_from_transcript(transcript: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Parse + working-hours in one call; None when no time was stated."""
    desired = parse_callback_time(transcript, now=now)
    if desired is None:
        return None
    return next_working_slot(desired, now=now)
