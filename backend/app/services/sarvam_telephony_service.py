import asyncio
import audioop
import base64
import io
import json
import logging
import math
import struct
import time
import uuid
import wave
from datetime import UTC, datetime
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.agent import Agent
from app.models.call import Call, Recording, Transcript, TranscriptSegment
from app.services.storage.s3 import storage_service

logger = logging.getLogger("sarvam_telephony")


class SarvamTelephonyService:
    """
    Native Sarvam AI Telephony Engine.
    Directly connects VoBiz PSTN telephony to Sarvam AI (STT, LLM, TTS)
    without requiring Dograh, Docker containers, or Kokoro.
    """

    def __init__(self):
        self.sarvam_api_key = settings.SARVAM_API_KEY
        self.tts_model = getattr(settings, "SARVAM_TTS_MODEL", "bulbul:v3")
        self.stt_model = getattr(settings, "SARVAM_STT_MODEL", "saaras:v3")
        self.llm_model = getattr(settings, "SARVAM_LLM_MODEL", "sarvam-105b-conversations")
        self.default_voice = getattr(settings, "SARVAM_DEFAULT_VOICE", "shubh")
        self._http_client: Optional[httpx.AsyncClient] = None
        self._tts_cache: Dict[str, bytes] = {}

    def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=40, max_connections=60, keepalive_expiry=120.0)
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(12.0, connect=3.0),
                limits=limits,
            )
        return self._http_client

    def _get_public_url(self) -> str:
        """Returns the public HTTPS URL for webhooks (auto-detects from local ngrok API, tunnel file, or settings)."""
        now = time.time()
        if hasattr(self, "_cached_public_url") and self._cached_public_url and (now - getattr(self, "_cached_url_time", 0) < 600):
            return self._cached_public_url
        # 1. Check local ngrok API
        try:
            with httpx.Client(timeout=2.5) as client:
                res = client.get("http://127.0.0.1:4040/api/tunnels")
                if res.status_code == 200:
                    tunnels = res.json().get("tunnels", [])
                    backend_port_str = str(getattr(settings, "BACKEND_PORT", 8001))
                    for t in tunnels:
                        addr = str(t.get("config", {}).get("addr", ""))
                        public_url = t.get("public_url", "")
                        if backend_port_str in addr and public_url.startswith("https://"):
                            self._cached_public_url = public_url.rstrip("/")
                            self._cached_url_time = now
                            return self._cached_public_url
                    for t in tunnels:
                        public_url = t.get("public_url", "")
                        if public_url.startswith("https://"):
                            return public_url.rstrip("/")
        except Exception:
            pass

        # 2. Check if tunnel_url.txt was written by the launcher script
        try:
            from app.config import LOGS_DIR
            tunnel_file = LOGS_DIR / "tunnel_url.txt"
            if tunnel_file.exists():
                saved_url = tunnel_file.read_text(encoding="utf-8").strip()
                if saved_url.startswith("https://"):
                    return saved_url.rstrip("/")
        except Exception:
            pass

        # 3. Check cloudflared metrics
        try:
            with httpx.Client(timeout=1.5) as client:
                cf_res = client.get("http://127.0.0.1:2000/metrics")
                if cf_res.status_code == 200:
                    import re
                    m = re.search(r'([a-z0-9-]+\.trycloudflare\.com)', cf_res.text)
                    if m:
                        return f"https://{m.group(1)}".rstrip("/")
        except Exception:
            pass

        # 4. Check explicit BACKEND_PUBLIC_URL from environment / .env
        candidate = getattr(settings, "BACKEND_PUBLIC_URL", "").strip()
        if candidate and candidate.startswith("https://") and "localhost" not in candidate and "127.0.0.1" not in candidate:
            return candidate.rstrip("/")

        return ""

    async def initiate_vobiz_call(
        self,
        call_id: str,
        to_number: str,
        from_number: Optional[str] = None,
        auth_id: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Directly initiates an outbound phone call via VoBiz REST API using agent-specific or global credentials.
        """
        carrier_auth_id = (auth_id or settings.VOBIZ_AUTH_ID or "").strip()
        carrier_auth_token = (auth_token or settings.VOBIZ_AUTH_TOKEN or "").strip()
        default_from = settings.VOBIZ_FROM_NUMBER or "+918065354620"

        if not carrier_auth_id or not carrier_auth_token:
            raise ValueError("VoBiz carrier Auth ID and Auth Token must be configured.")

        auth_id = carrier_auth_id
        auth_token = carrier_auth_token

        caller_id = (from_number or default_from).lstrip("+")
        callee_id = to_number.lstrip("+")
        public_url = self._get_public_url()
        if not public_url or not public_url.startswith("https://"):
            raise ValueError(
                "Cannot initiate live call: No public HTTPS webhook detected! "
                "Telephony carriers (VoBiz/Twilio) require a live public HTTPS URL to stream audio. "
                "Please ensure ngrok is running (run 'setup_and_run.bat' or 'ngrok http 8001') or set BACKEND_PUBLIC_URL."
            )

        answer_url = f"{public_url}/api/v1/telephony/vobiz/answer/{call_id}"
        hangup_url = f"{public_url}/api/v1/telephony/vobiz/hangup/{call_id}"

        url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/"
        recording_callback = f"{public_url}/api/v1/telephony/vobiz/recording-callback/{call_id}"
        payload = {
            "from": caller_id,
            "to": callee_id,
            "answer_url": answer_url,
            "answer_method": "POST",
            "hangup_url": hangup_url,
            "hangup_method": "POST",
            "record": "true",
            "record_url": recording_callback,
            "record_method": "POST",
            "recording_file_format": "wav",
        }
        headers = {
            "X-Auth-ID": auth_id,
            "X-Auth-Token": auth_token,
            "Content-Type": "application/json",
        }

        logger.info(f"[SarvamTelephony] Initiating VoBiz call to {to_number} (Call ID: {call_id})")
        client = self.get_http_client()
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code not in (200, 201):
            err_text = resp.text
            logger.error(f"[SarvamTelephony] VoBiz call initiation failed ({resp.status_code}): {err_text}")
            raise RuntimeError(f"VoBiz call failed: {err_text}")

        data = resp.json()
        call_uuid = (
            data.get("call_uuid")
            or data.get("CallUUID")
            or data.get("request_uuid")
            or data.get("RequestUUID")
            or f"vb-{uuid.uuid4().hex[:12]}"
        )
        logger.info(f"[SarvamTelephony] VoBiz call fired successfully. UUID: {call_uuid}")
        return {
            "status": "success",
            "call_uuid": call_uuid,
            "raw": data,
        }

    def get_vobiz_answer_xml(self, call_id: str) -> str:
        """
        Returns the Plivo/VoBiz XML response instructing VoBiz to open
        a bidirectional 8kHz mu-law audio WebSocket stream and record the call.
        """
        public_url = self._get_public_url()
        ws_endpoint = public_url.replace("https://", "wss://").replace("http://", "ws://")
        stream_url = f"{ws_endpoint}/api/v1/telephony/vobiz/stream/{call_id}"
        record_action = f"{public_url}/api/v1/telephony/vobiz/recording-callback/{call_id}"

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" contentType="audio/x-mulaw;rate=8000">{stream_url}</Stream>
</Response>"""
        return xml

    VALID_SPEAKERS = {
        "aditya", "ritu", "ashutosh", "priya", "neha", "rahul", "pooja", "rohan",
        "simran", "kavya", "amit", "dev", "ishita", "shreya", "ratan", "varun",
        "manan", "sumit", "roopa", "kabir", "aayan", "shubh", "advait", "anand",
        "tanya", "tarun", "sunny", "mani", "gokul", "vijay", "shruti", "suhani",
        "mohit", "kavitha", "rehan", "soham", "rupali",
    }

    def _normalize_sarvam_speaker(self, voice: Optional[str]) -> str:
        """Ensures the speaker is a recognized Sarvam Bulbul:v3 voice."""
        if not voice:
            return self.default_voice or "shubh"
        v = str(voice).strip().lower()
        if v in self.VALID_SPEAKERS:
            return v
        for s in self.VALID_SPEAKERS:
            if s in v:
                return s
        if any(female_hint in v for female_hint in ["female", "girl", "woman", "shreya", "priya", "neha", "pooja", "ritu"]):
            return "priya"
        return self.default_voice or "shubh"

    @staticmethod
    def normalize_indic_transcript(text: str) -> str:
        """
        Normalizes Indic speech-to-text transcriptions, correcting common phonetic
        misinterpretations of Marathi/Hindi numbers, acreages, and seed varieties.
        """
        if not text:
            return ""
        t = text
        corrections = [
            # Spoken Marathi/Hindi numbers + Acreage
            ("सहायक कर", "६ एकर"),
            ("सहा एकर", "६ एकर"),
            ("सहा एकड़", "६ एकर"),
            ("६ एकड़", "६ एकर"),
            ("साथ ही सर", "७ एकर"),
            ("सात एकर", "७ एकर"),
            ("सात एकड़", "७ एकर"),
            ("७ एकड़", "७ एकर"),
            ("बात एक और", "५ एकर"),
            ("पाच एकर", "५ एकर"),
            ("पाच एकड़", "५ एकर"),
            ("५ एकड़", "५ एकर"),
            ("दोन एकर", "२ एकर"),
            ("दो एकड़", "२ एकर"),
            ("तीन एकर", "३ एकर"),
            ("तीन एकड़", "३ एकर"),
            ("चार एकर", "४ एकर"),
            ("चार एकड़", "४ एकर"),
            ("दहा एकर", "१० एकर"),
            ("दस एकड़", "१० एकर"),
            ("एका एकर", "१ एकर"),
            ("एक एकर", "१ एकर"),
            ("एक एकड़", "१ एकर"),
            ("वीस किलो", "२० किलो"),
            ("तीस किलो", "३० किलो"),
            ("चाळीस किलो", "४० किलो"),
            ("पन्नास किलो", "५० किलो"),
            ("शंभर किलो", "१०० किलो"),
            ("दोनशे किलो", "२०० किलो"),
            # Crop & Variety phonetic slips
            ("लोगों के बारे में", "लोकवन बद्दल"),
            ("लोगों के बारे", "लोकवन बद्दल"),
            ("लोकमन", "लोकवन"),
            ("लोक वन", "लोकवन"),
            ("दिग विजय", "दिग्विजय"),
            # Questions asked by farmer
            ("का है इसका", "याचे दर काय आहेत"),
            ("का भाव आहे", "याचे दर काय आहेत"),
            ("काय भाव आहे", "याचे दर काय आहेत"),
            ("भाव काय", "दर काय आहेत"),
            ("रेट काय", "दर काय आहेत"),
            ("कोणता रिकमेंड", "कोणता प्रकार चांगला आहे"),
            ("कौन सा रिकमेंड", "कोणता प्रकार चांगला आहे"),
        ]
        for src, target in corrections:
            t = t.replace(src, target)
        return t

    @staticmethod
    def is_refusal_or_call_termination(text: str) -> bool:
        """
        Detects if the caller wants to end the call, refuses, or is not interested.
        Supports Hindi, Hinglish, and English phrases.
        """
        if not text:
            return False
        t = text.lower().strip()

        # Direct refusal & call-cut keywords
        refusal_keywords = [
            "नहीं चाहिए", "नहीं चाहिये", "नहीं लेना", "नहीं चाहिए जी", "नहीं चाहिए मुझे",
            "कट कर", "कट करो", "काट दो", "काट दीजिए", "काटो", "फोन रखो", "फोन काट",
            "रखो फोन", "रहने दो", "रहने दीजिए", "मत करो", "फोन मत करो", "कॉल मत",
            "नहीं नहीं", "नहीं जी", "नहीं भाई", "नहीं थैंक यू", "नहीं धन्यवाद", "थैंक यू नहीं",
            "बाद में बात", "बाद में करो", "अभी बिजी", "बिजी हूँ", "व्यस्त हूँ", "गलत नंबर", "रॉन्ग नंबर",
            "not interested", "no thanks", "don't call", "cut the call", "cut it", "hang up",
            "stop calling", "wrong number", "busy right now", "call later", "bye", "अलविदा",
            "बंद करो", "रख दीजिए", "नही चाहिए", "काट दिजिये", "काट दीजिये",
            "नको", "नाही", "नको मला", "काही नको", "रुचि नहीं", "इंटरेस्ट नहीं", "नॉट इंटरेस्टेड",
            "nahi chahiye", "nahi lena", "nahi re", "nahi bhai", "no need", "not needed",
            "interest nahi", "nahi hai", "not really"
        ]
        if any(k in t for k in refusal_keywords):
            return True

        # Standalone negative response words: only trigger if utterance is strictly a short standalone refusal
        clean_words = [w.strip("।,?!.") for w in t.split() if w.strip("।,?!.")]
        if len(clean_words) == 1 and clean_words[0] in [
            "नहीं", "नही", "ना", "no", "nahi", "nahin", "nope", "nako", "नाही"
        ]:
            return True
        if len(clean_words) == 2 and clean_words[0] in ["नहीं", "नही", "ना", "no", "nahi", "nahin", "nope", "nako", "नाही"] and clean_words[1] in ["जी", "भाई", "सर", "thanks", "धन्यवाद", "sir", "madam", "re", "नको"]:
            return True

        return False

    async def synthesize_speech(
        self,
        text: str,
        voice: Optional[str] = None,
        language_code: str = "hi-IN",
    ) -> bytes:
        """
        Calls Sarvam AI Bulbul TTS (8000Hz mono WAV), extracts raw 16-bit PCM,
        and converts it to 8kHz mu-law bytes for telephony streaming.
        Uses connection pooling and in-memory caching.
        """
        clean_text = text.strip()
        if not clean_text:
            return b""

        target_voice = self._normalize_sarvam_speaker(voice)
        target_lang = language_code
        marathi_markers = ["आहे", "नाही", "नको", "तुम्हाला", "बियाणे", "सांगा", "होय", "कडुन", "कडून", "हवे", "विचार", "खरेदी", "नियोजन", "गहू", "हरभरा", "एकर", "पाहिजे"]
        if any(m in clean_text for m in marathi_markers):
            target_lang = "mr-IN"
        elif any(h in clean_text for h in ["है", "हूँ", "बताइए", "नमस्ते", "धन्यवाद", "गेहूँ", "चना"]):
            target_lang = "hi-IN"

        cache_key = f"{target_voice}:{target_lang}:{clean_text}"
        if cache_key in self._tts_cache:
            return self._tts_cache[cache_key]

        url = "https://api.sarvam.ai/text-to-speech"
        headers = {"api-subscription-key": self.sarvam_api_key}
        payload = {
            "inputs": [clean_text],
            "target_language_code": target_lang,
            "speaker": target_voice,
            "model": self.tts_model,
            "speech_sample_rate": 8000,
            "enable_preprocessing": False,
        }

        try:
            client = self.get_http_client()
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"[SarvamTelephony] TTS generation failed ({resp.status_code}): {resp.text}")
                return b""

            audios = resp.json().get("audios", [])
            if not audios:
                return b""

            wav_bytes = base64.b64decode(audios[0])

            # Extract raw PCM frames from WAV
            with wave.open(io.BytesIO(wav_bytes)) as w:
                pcm_frames = w.readframes(w.getnframes())

            # Convert 16-bit linear PCM (8000Hz) to G.711 mu-law (8000Hz)
            mulaw_bytes = audioop.lin2ulaw(pcm_frames, 2)
            if len(self._tts_cache) < 200:
                self._tts_cache[cache_key] = mulaw_bytes
            return mulaw_bytes
        except Exception as e:
            logger.error(f"[SarvamTelephony] TTS request error: {e}")
            return b""

    async def transcribe_audio(
        self,
        mulaw_bytes: bytes,
        language_code: str = "hi-IN",
    ) -> str:
        """
        Converts accumulated 8kHz mu-law bytes to a 16-bit PCM WAV in memory
        and calls Sarvam AI Saaras STT for transcription via persistent client.
        """
        if len(mulaw_bytes) < 1200:
            return ""

        pcm_bytes = audioop.ulaw2lin(mulaw_bytes, 2)
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(pcm_bytes)
        wav_data = wav_buf.getvalue()

        url = "https://api.sarvam.ai/speech-to-text"
        headers = {"api-subscription-key": self.sarvam_api_key}
        files = {"file": ("caller_audio.wav", wav_data, "audio/wav")}
        data = {
            "model": self.stt_model,
            "language_code": language_code,
        }

        try:
            client = self.get_http_client()
            resp = await client.post(url, headers=headers, files=files, data=data)
            if resp.status_code != 200:
                logger.warning(f"[SarvamTelephony] STT failed ({resp.status_code}): {resp.text}")
                return ""

            result = resp.json()
            transcript = result.get("transcript", "").strip()
            return transcript
        except Exception as e:
            logger.error(f"[SarvamTelephony] STT error: {e}")
            return ""

    async def stream_llm_chunks(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
    ):
        """
        Streams conversational turns from Sarvam LLM and yields natural spoken sentences/clauses
        as fast as they are generated (Time-to-first-token: ~500ms).
        """
        client = self.get_http_client()
        url = "https://api.sarvam.ai/v1/chat/completions"
        headers = {
            "api-subscription-key": self.sarvam_api_key,
            "Content-Type": "application/json",
        }
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        payload = {
            "model": self.llm_model,
            "messages": full_messages,
            "temperature": 0.2,
            "max_tokens": 55,
            "stream": True,
        }

        delimiters = {"।", "?", "!", "\n"}
        current_chunk = []
        word_count = 0

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    yield "जी, बताइए मैं आपकी क्या सहायता कर सकता हूँ?"
                    return

                async for line in resp.aiter_lines():
                    line_str = line.strip()
                    if line_str.startswith("data: ") and line_str != "data: [DONE]":
                        try:
                            delta_json = json.loads(line_str[6:])
                            delta_text = delta_json["choices"][0].get("delta", {}).get("content", "")
                            if not delta_text:
                                continue

                            current_chunk.append(delta_text)
                            if " " in delta_text:
                                word_count += delta_text.count(" ")

                            has_delimiter = any(d in delta_text for d in delimiters)

                            if has_delimiter:
                                sentence = "".join(current_chunk).strip()
                                if sentence:
                                    yield sentence
                                current_chunk = []
                                word_count = 0
                        except Exception:
                            pass

                remainder = "".join(current_chunk).strip()
                if remainder:
                    yield remainder

        except Exception as e:
            logger.error(f"[SarvamTelephony] LLM streaming error: {e}")
            if not current_chunk:
                yield "जी, बताइए मैं आपकी क्या सहायता कर सकता हूँ?"

    async def generate_llm_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
    ) -> str:
        """
        Calls Sarvam AI LLM to produce the next conversational turn.
        """
        full_text = []
        async for chunk in self.stream_llm_chunks(messages, system_prompt):
            full_text.append(chunk)
        return " ".join(full_text).strip() or "जी, बताइए मैं आपकी क्या सहायता कर सकता हूँ?"

    async def stream_audio_to_vobiz(
        self,
        websocket: WebSocket,
        stream_id: str,
        mulaw_bytes: bytes,
        chunk_size: int = 640,  # 640 bytes = 80ms of 8kHz mu-law audio
        on_chunk_sent: Optional[Callable[[bytes], None]] = None,
    ):
        """
        Streams mu-law audio chunks into the VoBiz WebSocket using the official
        Plivo/VoBiz 'playAudio' event structure.
        """
        if not mulaw_bytes or not stream_id:
            return

        total_len = len(mulaw_bytes)
        prebuffer_chunks = 5  # Pre-send 400ms burst to prime carrier jitter buffer and eliminate underrun
        start_monotonic = time.monotonic()

        logger.info(f"[SarvamTelephony] Streaming {total_len} bytes to VoBiz (streamId: {stream_id})...")
        try:
            chunk_idx = 0
            offset = 0
            while offset < total_len:
                chunk = mulaw_bytes[offset : offset + chunk_size]
                b64_payload = base64.b64encode(chunk).decode("ascii")
                msg_str = (
                    f'{{"event":"playAudio","streamId":"{stream_id}",'
                    f'"media":{{"contentType":"audio/x-mulaw","sampleRate":8000,"payload":"{b64_payload}"}}}}'
                )
                await websocket.send_text(msg_str)
                if on_chunk_sent:
                    try:
                        on_chunk_sent(chunk)
                    except Exception:
                        pass

                offset += chunk_size
                chunk_idx += 1

                # Burst first 400ms into carrier queue immediately
                if chunk_idx < prebuffer_chunks:
                    continue

                # Drift-compensated monotonic pacing
                chunk_dur = len(chunk) / 8000.0
                target_elapsed = (chunk_idx - prebuffer_chunks + 1) * chunk_dur
                actual_elapsed = time.monotonic() - start_monotonic
                sleep_needed = target_elapsed - actual_elapsed

                if sleep_needed > 0.005:
                    await asyncio.sleep(sleep_needed)

            logger.info(f"[SarvamTelephony] Finished playing audio to VoBiz (streamId: {stream_id}).")
        except asyncio.CancelledError:
            logger.info(f"[SarvamTelephony] Outbound playback cancelled (caller barge-in) for stream {stream_id}")
            raise
        except Exception as e:
            logger.warning(f"[SarvamTelephony] Error during playAudio streaming: {e}")

    async def stop_playback_and_clear(self, websocket: WebSocket, stream_id: str):
        """
        Sends the official VoBiz/Plivo 'clearAudio' event to immediately flush
        any remaining audio in the carrier queue upon caller barge-in.
        """
        if not stream_id:
            return
        try:
            clear_msg = {
                "event": "clearAudio",
                "streamId": stream_id,
            }
            await websocket.send_text(json.dumps(clear_msg))
            logger.info(f"[SarvamTelephony] Sent 'clearAudio' for stream {stream_id}")
        except Exception as e:
            logger.debug(f"[SarvamTelephony] clearAudio notice: {e}")

    def _build_call_wav(
        self,
        timeline: List[tuple],
        duration_seconds: float,
    ) -> bytes:
        """
        Mixes recorded timeline of 8000Hz mu-law chunks (both caller and agent)
        into a clean, synchronized, glitch-free 16-bit PCM WAV recording.
        Preserves 100% authentic telephony microphone audio of the human caller
        without packet stacking, jitter clicks, or clipping distortion.
        """
        if not timeline:
            from app.services.storage.audio_generator import generate_synthesized_call_audio
            return generate_synthesized_call_audio(duration_seconds=duration_seconds or 6.0)

        # Separate customer and agent chunks
        customer_events = [(offset, chunk) for offset, spk, chunk in timeline if spk == "customer" and chunk]
        agent_events = [(offset, chunk) for offset, spk, chunk in timeline if spk == "agent" and chunk]

        # Calculate total recording duration
        max_time = float(duration_seconds or 2.0)
        for offset, _, chunk in timeline:
            if chunk:
                end_t = offset + (len(chunk) / 8000.0)
                if end_t > max_time:
                    max_time = end_t
        dur = max(max_time + 0.5, 2.0)
        total_samples = int(dur * 8000)

        customer_pcm = [0] * total_samples
        agent_pcm = [0] * total_samples

        # 1. Place customer chunks with jitter smoothing (continuous timeline)
        # Prevents packet clumping and comb-filtering buzz from network arrival jitter
        curr_cust_idx = 0
        for offset_sec, chunk in customer_events:
            try:
                pcm = audioop.ulaw2lin(chunk, 2)
                n_samples = len(pcm) // 2
                samples = struct.unpack(f"<{n_samples}h", pcm)

                target_idx = max(0, int(offset_sec * 8000))
                # If packet arrives within jitter window (within 60ms = 480 samples),
                # place continuously following previous packet for smooth, uninterrupted caller audio
                if curr_cust_idx > 0 and abs(target_idx - curr_cust_idx) <= 480:
                    start_idx = curr_cust_idx
                else:
                    start_idx = target_idx

                end_idx = min(start_idx + n_samples, total_samples)
                if start_idx < total_samples:
                    for i in range(end_idx - start_idx):
                        customer_pcm[start_idx + i] = samples[i]
                    curr_cust_idx = start_idx + n_samples
            except Exception as e:
                logger.debug(f"[SarvamTelephony] Error placing customer chunk: {e}")

        # 2. Place agent chunks
        for offset_sec, chunk in agent_events:
            try:
                pcm = audioop.ulaw2lin(chunk, 2)
                n_samples = len(pcm) // 2
                samples = struct.unpack(f"<{n_samples}h", pcm)
                start_idx = max(0, int(offset_sec * 8000))
                end_idx = min(start_idx + n_samples, total_samples)
                if start_idx < total_samples:
                    for i in range(end_idx - start_idx):
                        agent_pcm[start_idx + i] = samples[i]
            except Exception as e:
                logger.debug(f"[SarvamTelephony] Error placing agent chunk: {e}")

        # 3. Dynamic balance & Clean AGC
        # Measure customer voice energy on active speech frames only (|sample| > 250)
        active_customer_samples = [abs(s) for s in customer_pcm if abs(s) > 250]
        if active_customer_samples:
            mean_active = sum(active_customer_samples) / len(active_customer_samples)
            # Gentle target: bring customer speech to ~2800 mean amplitude, clamped between 1.0 and 2.5
            customer_gain = min(2.5, max(1.0, 2800.0 / max(mean_active, 50.0)))
        else:
            customer_gain = 1.2

        agent_gain = 0.85  # Balance agent slightly below caller

        # 4. Mix tracks with soft saturation limiter (absolutely zero digital clipping)
        out_samples = [0] * total_samples
        for i in range(total_samples):
            c_val = customer_pcm[i] * customer_gain
            a_val = agent_pcm[i] * agent_gain
            mixed = c_val + a_val

            # Soft-saturation limiter for seamless analog-like headroom
            if mixed > 28000.0:
                capped = 28000.0 + (32760.0 - 28000.0) * math.tanh((mixed - 28000.0) / 4760.0)
            elif mixed < -28000.0:
                diff = -mixed - 28000.0
                capped = -(28000.0 + (32760.0 - 28000.0) * math.tanh(diff / 4760.0))
            else:
                capped = mixed
            out_samples[i] = int(capped)

        raw_pcm = struct.pack(f"<{total_samples}h", *out_samples)
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(raw_pcm)

        return wav_buf.getvalue()

    async def handle_vobiz_media_stream(self, websocket: WebSocket, call_id: str):
        """
        Core bidirectional real-time conversational voice pipeline.
        Connects VoBiz WebSocket directly to Sarvam AI (STT -> LLM -> TTS).
        """
        await websocket.accept()
        logger.info(f"[SarvamTelephony] VoBiz WebSocket connected for Call ID: {call_id}")

        call_start_time = time.time()
        carrier_call_uuid: Optional[str] = None
        carrier_auth_id = settings.VOBIZ_AUTH_ID
        carrier_auth_token = settings.VOBIZ_AUTH_TOKEN

        # Fetch Call and Agent from DB
        async with AsyncSessionLocal() as session:
            stmt = select(Call).where(Call.id == call_id)
            res = await session.execute(stmt)
            call_record = res.scalar_one_or_none()
            if call_record:
                call_record.status = "in_progress"
                call_record.answered_at = datetime.now(UTC)
                carrier_call_uuid = call_record.telephony_call_id
                agent = await session.get(Agent, call_record.agent_id)
                if agent:
                    if getattr(agent, "telephony_auth_id", None):
                        carrier_auth_id = agent.telephony_auth_id
                    if getattr(agent, "telephony_auth_token", None):
                        carrier_auth_token = agent.telephony_auth_token
                await session.commit()

        if not agent:
            logger.error(f"[SarvamTelephony] Agent not found for Call ID: {call_id}")
            await websocket.close()
            return

        agent_name = agent.name or "Assistant"
        comp_name = getattr(agent, "company_name", None) or "ARB SoftTech"
        comp_desc = getattr(agent, "company_description", None) or agent.purpose or "Customer Assistance"
        voice_id = getattr(agent, "voice_id", None) or self.default_voice

        # Determine selected language & dialect
        agent_lang = (getattr(agent, "default_language", None) or getattr(agent, "primary_language", None) or "Hindi").lower()
        if "marathi" in agent_lang or "mr" in agent_lang:
            lang_code = "mr-IN"
            lang_name = "Marathi"
            default_greeting = f"नमस्कार, मी {comp_name} कडून {agent_name} बोलत आहे. तुम्हाला आमच्या सेवेमध्ये इंटरेस्ट आहे का?"
            farewell_reply = "ठीक आहे, वेळ दिल्याबद्दल धन्यवाद! नमस्कार."
            interest_followup = "खूप छान! सांगा, तुम्हाला कोणती माहिती हवी आहे?"
        elif "english" in agent_lang or "en" in agent_lang:
            lang_code = "en-IN"
            lang_name = "English"
            default_greeting = f"Hello! This is {agent_name} from {comp_name}. Are you interested in our services?"
            farewell_reply = "Alright, thank you for your time! Have a great day."
            interest_followup = "Great! Please let me know what information you need."
        elif "gujarati" in agent_lang or "gu" in agent_lang:
            lang_code = "gu-IN"
            lang_name = "Gujarati"
            default_greeting = f"નમસ્તે, હું {comp_name} માંથી {agent_name} વાત કરું છું. શું તમે અમારી સેવામાં રસ ધરાવો છો?"
            farewell_reply = "ઠીક છે, સમય આપવા બદલ આભાર! નમસ્તે."
            interest_followup = "ખૂબ સરસ! જણાવો તમે કઈ માહિતી ઈચ્છો છો?"
        else:  # Default Hindi
            lang_code = "hi-IN"
            lang_name = "Hindi"
            default_greeting = f"नमस्कार जी, मैं {comp_name} से {agent_name} बात कर रहा हूँ। क्या आप हमारी सेवाओं में इंटरेस्टेड हैं?"
            farewell_reply = "जी ठीक है, समय देने के लिए आपका बहुत धन्यवाद! नमस्कार।"
            interest_followup = "बहुत बढ़िया! बताइए आप किस सेवा या सहायता के बारे में जानना चाहते हैं?"

        # Every agent greets customer and asks if they are interested or not in selected language
        greeting = (getattr(agent, "greeting_message", None) or "").strip()
        if not greeting:
            greeting = default_greeting
        else:
            has_interest_q = any(k in greeting.lower() for k in [
                "interested", "interest", "रुचि", "इंटरेस्टेड", "इंटरेस्ट", "स्वारस्य", "रस", "चाहते हैं", "चाहते हो"
            ])
            if not has_interest_q:
                if "mr" in lang_code:
                    greeting = f"{greeting.rstrip('।,?!.')}. तुम्हाला आमच्या सेवेमध्ये इंटरेस्ट आहे का?"
                elif "en" in lang_code:
                    greeting = f"{greeting.rstrip('।,?!.')}. Are you interested in our services?"
                else:
                    greeting = f"{greeting.rstrip('।,?!.')}। क्या आप हमारी सेवाओं में इंटरेस्टेड हैं?"

        if "mr" in lang_code:
            lang_rules = (
                f"STRICT MARATHI LANGUAGE LOCK:\n"
                f"- Speak ONLY in pure, polite, and respectful Marathi (मराठी) in Devanagari script.\n"
                f"- NEVER switch to Hindi! Never use Hindi words like 'बहुत बढ़िया', 'क्या आप', 'बताइए', 'बीज', 'गेहूँ', 'चना', 'बुवाई', 'है', 'कीजिए'.\n"
                f"- ALWAYS use proper Marathi: 'खूप छान', 'बियाणे', 'गहू आणि हरभरा', 'पेरणी', 'सांगा', 'आहे', 'तुम्हाला / आपल्याला', 'आपण'.\n"
            )
        else:
            lang_rules = f"1. Spoken Language: Respond naturally in {lang_name} ({lang_code}). Never use English roman script for Indic languages or markdown.\n"

        system_prompt = (
            f"You are '{agent_name}', a helpful and polite AI Voice Calling Assistant representing '{comp_name}'.\n"
            f"Company / Purpose: {comp_desc}\n\n"
            f"INSTRUCTIONS & SCRIPT:\n{agent.instructions or agent.system_prompt or ''}\n\n"
            f"RULES FOR CONVERSATIONAL PHONE CALL:\n"
            f"{lang_rules}"
            f"2. Strict 1 Short Sentence: Keep replies strictly under 15 words total. Never give long speeches.\n"
            f"3. PROGRESSION ONLY - NEVER REPEAT: Never repeat a question you already asked in this call. If customer gives a vague response like 'ठीक आहे' / 'ठीक है' / 'बघू', acknowledge it and move forward to the next step immediately. NEVER ask for the same detail twice!\n"
            f"4. Callback Request: If customer says they are busy or want a callback ('नंतर फोन करा', 'बाद में कॉल करो', 'वेळ नाही', 'नंतर सांगा'): Say '{farewell_reply}' and do NOT ask any more questions.\n"
            f"5. If customer declines or says no ('नाही', 'नहीं', 'नको', 'not interested'): Say ONLY '{farewell_reply}' and stop.\n"
            f"6. Concluding: If customer says 'ठीक आहे', 'ठीक है', or 'thank you', say '{farewell_reply}'."
        )

        conversation_history: List[Dict[str, str]] = []

        # Ensure transcript record exists in DB
        async with AsyncSessionLocal() as session:
            stmt = select(Transcript).where(Transcript.call_id == call_id)
            res = await session.execute(stmt)
            tr = res.scalar_one_or_none()
            if not tr:
                tr = Transcript(call_id=call_id)
                session.add(tr)
                await session.commit()

        # Pre-synthesize opening greeting immediately so it's ready in memory for instant playback when user speaks
        logger.info(f"[SarvamTelephony] Pre-synthesizing greeting: '{greeting}'")
        greeting_mulaw = await self.synthesize_speech(greeting, voice=voice_id, language_code=lang_code)

        # State tracking for real-time bidirectional loop
        stream_id: Optional[str] = None
        greeting_delivered = False
        greeting_started_time = 0.0
        current_turn_task: Optional[asyncio.Task] = None
        is_agent_speaking = False
        agent_finished_speaking_time = 0.0

        audio_buffer = bytearray()
        is_user_speaking = False
        caller_turn_start_time = 0.0
        last_speech_time = 0.0
        energy_threshold = 300  # RMS threshold for caller voice activity detection
        sequence_counter = 1

        # Active conversation context tracker (remembers stated acreage, crop, timing, etc.)
        context_state = {
            "crop": None,
            "timing": None,
            "acreage": None,
            "quantity": None,
            "variety": None,
        }
        dialogue_step = 0

        recorded_timeline: List[tuple] = []

        barge_in_streak = 0
        agent_speech_started_time = 0.0

        async def play_audio_task(mulaw_data: bytes):
            nonlocal is_agent_speaking, agent_finished_speaking_time, agent_speech_started_time
            is_agent_speaking = True
            agent_speech_started_time = time.time()

            def on_chunk(chunk: bytes):
                recorded_timeline.append((time.time() - call_start_time, "agent", chunk))

            try:
                await self.stream_audio_to_vobiz(
                    websocket,
                    stream_id or call_id,
                    mulaw_data,
                    on_chunk_sent=on_chunk,
                )
            finally:
                is_agent_speaking = False
                agent_finished_speaking_time = time.time()

        async def deliver_greeting():
            nonlocal greeting_delivered, greeting_started_time, sequence_counter
            if greeting_delivered:
                return
            greeting_delivered = True
            greeting_started_time = time.time()
            logger.info(f"[SarvamTelephony] Delivering opening greeting immediately on call connect: '{greeting}'")
            conversation_history.append({"role": "assistant", "content": greeting})
            async with AsyncSessionLocal() as session:
                stmt = select(Transcript).where(Transcript.call_id == call_id)
                tr = (await session.execute(stmt)).scalar_one_or_none()
                if tr:
                    session.add(
                        TranscriptSegment(
                            transcript_id=tr.id,
                            speaker="agent",
                            text=greeting,
                            start_time=round(greeting_started_time - call_start_time, 2),
                            end_time=round(greeting_started_time + 3.0 - call_start_time, 2),
                            sequence=sequence_counter,
                            confidence=1.0,
                        )
                    )
                    await session.commit()
            sequence_counter += 1
            if greeting_mulaw:
                await play_audio_task(greeting_mulaw)

        async def process_caller_turn(user_audio_bytes: bytes, t_start: float, t_end: float):
            nonlocal sequence_counter, is_agent_speaking, agent_finished_speaking_time, greeting_delivered, greeting_started_time
            t_turn_start = time.time()
            logger.info(f"[SarvamTelephony] Caller finished turn ({len(user_audio_bytes)} bytes). Transcribing...")
            user_text = await self.transcribe_audio(user_audio_bytes)
            stt_duration_ms = round((time.time() - t_turn_start) * 1000)

            if not user_text or not user_text.strip():
                logger.info("[SarvamTelephony] STT returned empty transcription.")
                return

            logger.info(f"[SarvamTelephony] Raw STT caller text: '{user_text}' (took {stt_duration_ms}ms)")
            # 0. Phonetic & agricultural normalizer: accurately restores numbers and terms
            user_text = self.normalize_indic_transcript(user_text)
            logger.info(f"[SarvamTelephony] Normalized caller text: '{user_text}'")
            conversation_history.append({"role": "user", "content": user_text})

            # Update context_state from caller speech
            u_clean = user_text.lower()
            if "गहू" in u_clean or "wheat" in u_clean:
                context_state["crop"] = "गहू"
            elif "हरभरा" in u_clean or "चना" in u_clean or "chana" in u_clean:
                context_state["crop"] = "हरभरा"

            if "आता" in u_clean or "now" in u_clean:
                context_state["timing"] = "आता"
            elif "नंतर" in u_clean or "later" in u_clean:
                context_state["timing"] = "नंतर"

            import re
            acre_match = re.search(r"(\d+|एक|दोन|तीन|चार|पाच|सहा|सात|आठ|नऊ|दहा)\s*(?:एकर|एकड़)", user_text)
            if acre_match:
                context_state["acreage"] = acre_match.group(0)
                logger.info(f"[SarvamTelephony] Saved context: Acreage = {context_state['acreage']}")

            qty_match = re.search(r"(\d+|वीस|तीस|चाळीस|पन्नास|शंभर|दोनशे)\s*(?:किलो|बॅग)", user_text)
            if qty_match:
                context_state["quantity"] = qty_match.group(0)
                logger.info(f"[SarvamTelephony] Saved context: Quantity = {context_state['quantity']}")

            if "लोकवन" in user_text:
                context_state["variety"] = "लोकवन"
            elif "शरबती" in user_text:
                context_state["variety"] = "शरबती"
            elif "दिग्विजय" in user_text:
                context_state["variety"] = "दिग्विजय"
            elif "विजय" in user_text:
                context_state["variety"] = "विजय"

            # Persist caller transcript segment in DB with accurate timestamps
            async with AsyncSessionLocal() as session:
                stmt = select(Transcript).where(Transcript.call_id == call_id)
                tr = (await session.execute(stmt)).scalar_one_or_none()
                if tr:
                    session.add(
                        TranscriptSegment(
                            transcript_id=tr.id,
                            speaker="customer",
                            text=user_text,
                            start_time=round(t_start - call_start_time, 2),
                            end_time=round(t_end - call_start_time, 2),
                            sequence=sequence_counter,
                            confidence=0.98,
                        )
                    )
                    await session.commit()
            sequence_counter += 1

            # 1. Check if caller requested a callback or is busy / postponing call
            callback_keywords = [
                "बाद में कॉल", "बाद में फोन", "नंतर फोन", "नंतर कॉल", "नंतर बोला", "नंतर सांगा",
                "वेळ नाही", "टाइम नाही", "टाइम नही", "बाद में बात", "call later", "call me later",
                "busy right now", "नंतर बोला ना", "नंतर करा", "बाद में करना", "कल कॉल", "उद्या फोन",
                "उद्या करा", "नंतर सांगतो", "बाद में बताऊंगा"
            ]
            if greeting_delivered and any(k in user_text.lower() for k in callback_keywords):
                logger.info(f"[SarvamTelephony] Caller requested callback / busy: '{user_text}'. Concluding with callback promise.")
                if "mr" in lang_code:
                    cb_farewell = "नक्कीच! आम्ही तुम्हाला नंतर सोयीच्या वेळी पुन्हा कॉल करू. वेळ दिल्याबद्दल खूप धन्यवाद, नमस्कार!"
                elif "en" in lang_code:
                    cb_farewell = "Sure! We will call you back at a convenient time. Thank you, have a great day!"
                else:
                    cb_farewell = "जी बिल्कुल! हम आपको बाद में सुविधानुसार कॉल करेंगे। समय देने के लिए बहुत धन्यवाद, नमस्कार!"

                conversation_history.append({"role": "assistant", "content": cb_farewell})
                cb_start = time.time()
                cb_mulaw = await self.synthesize_speech(cb_farewell, voice=voice_id, language_code=lang_code)
                if cb_mulaw:
                    await play_audio_task(cb_mulaw)
                    await asyncio.sleep(1.2)

                # Persist callback farewell segment
                async with AsyncSessionLocal() as session:
                    stmt = select(Transcript).where(Transcript.call_id == call_id)
                    tr = (await session.execute(stmt)).scalar_one_or_none()
                    if tr:
                        session.add(
                            TranscriptSegment(
                                transcript_id=tr.id,
                                speaker="agent",
                                text=cb_farewell,
                                start_time=round(cb_start - call_start_time, 2),
                                end_time=round(time.time() - call_start_time, 2),
                                sequence=sequence_counter,
                                confidence=1.0,
                            )
                        )
                        await session.commit()
                sequence_counter += 1

                # Update call disposition as callback_requested
                async with AsyncSessionLocal() as session:
                    c = await session.get(Call, call_id)
                    if c:
                        c.disposition = "callback_requested"
                        await session.commit()

                # Terminate carrier call
                try:
                    from app.services.telephony_service import telephony_service
                    uuid_to_hangup = carrier_call_uuid or stream_id
                    if uuid_to_hangup:
                        await telephony_service.hangup_live_telephony_call(
                            call_uuid=uuid_to_hangup,
                            auth_id=carrier_auth_id,
                            auth_token=carrier_auth_token,
                        )
                except Exception as hangup_err:
                    logger.warning(f"[SarvamTelephony] Carrier hangup error on callback: {hangup_err}")

                try:
                    await websocket.close()
                except Exception:
                    pass
                return

            # 2. Check if caller refused, declined, or requested call disconnection
            if greeting_delivered and self.is_refusal_or_call_termination(user_text):
                logger.info(f"[SarvamTelephony] Caller declined / said NO: '{user_text}'. Concluding and cutting call {call_id} immediately.")
                conversation_history.append({"role": "assistant", "content": farewell_reply})

                farewell_start = time.time()
                farewell_mulaw = await self.synthesize_speech(farewell_reply, voice=voice_id, language_code=lang_code)
                if farewell_mulaw:
                    await play_audio_task(farewell_mulaw)
                    await asyncio.sleep(1.2)

                # Persist farewell transcript segment
                async with AsyncSessionLocal() as session:
                    stmt = select(Transcript).where(Transcript.call_id == call_id)
                    tr = (await session.execute(stmt)).scalar_one_or_none()
                    if tr:
                        session.add(
                            TranscriptSegment(
                                transcript_id=tr.id,
                                speaker="agent",
                                text=farewell_reply,
                                start_time=round(farewell_start - call_start_time, 2),
                                end_time=round(time.time() - call_start_time, 2),
                                sequence=sequence_counter,
                                confidence=1.0,
                            )
                        )
                        await session.commit()
                sequence_counter += 1

                # Actively terminate call from telecom carrier side (VoBiz PSTN Hangup)
                try:
                    from app.services.telephony_service import telephony_service
                    uuid_to_hangup = carrier_call_uuid or stream_id
                    if uuid_to_hangup:
                        logger.info(f"[SarvamTelephony] Executing telecom carrier hangup for call {call_id} (uuid: {uuid_to_hangup})...")
                        await telephony_service.hangup_live_telephony_call(
                            call_uuid=uuid_to_hangup,
                            auth_id=carrier_auth_id,
                            auth_token=carrier_auth_token,
                        )
                except Exception as hangup_err:
                    logger.warning(f"[SarvamTelephony] Carrier hangup error: {hangup_err}")

                # Mark disposition in DB as not_interested
                async with AsyncSessionLocal() as session:
                    c = await session.get(Call, call_id)
                    if c:
                        c.disposition = "not_interested"
                        await session.commit()

                try:
                    await websocket.close()
                except Exception:
                    pass
                return

            # 3. If opening greeting has not been delivered yet, deliver it now
            if not greeting_delivered:
                await deliver_greeting()
                return

            # 4. Generate next turn via Structured Dialogue Engine & Context Memory
            agent_speech_start = time.time()
            prev_agent_texts = [m["content"] for m in conversation_history if m.get("role") == "assistant"]
            is_agri_agent = (getattr(agent, "id", "") == "agent-samruddhi-agritech") or ("samruddhi" in (getattr(agent, "name", "")).lower())

            direct_reply = None
            should_terminate_after_reply = False
            t_clean = user_text.lower().strip("।,?!. ")

            # Handle Hello / Audio Check without repeating previous statements
            if t_clean in ["हेलो", "हॅलो", "hello", "आवाज येतोय का", "ऐकू येतंय का"]:
                if "mr" in lang_code:
                    if dialogue_step <= 1:
                        direct_reply = "हो, ऐकू येतंय! आपण बियाणे आता खरेदी करू इच्छिता की नंतर?"
                    elif dialogue_step == 2:
                        direct_reply = "हो, आवाज येतोय! आपण किती एकर जमिनीवर पेरणी करणार आहात?"
                    elif dialogue_step == 3:
                        direct_reply = "हो, ऐकू येतंय! आपल्याला साधारण किती किलो बियाणे हवे आहे किंवा दर जाणून घ्यायचे आहेत का?"
                    else:
                        direct_reply = "हो, ऐकू येतंय! अधिक माहिती आणि बुकिंगसाठी आमच्या प्रतिनिधीकडून कॉल हवा आहे का?"
                else:
                    direct_reply = "जी, आवाज़ आ रही है! बताएं मैं आपकी क्या सहायता कर सकता हूँ?"

            # Direct Farmer Q&A: Always answer farmer questions directly with verified facts
            elif any(q in user_text for q in ["कोणता प्रकार", "कोणती व्हरायटी", "रिकमेंड", "चांगला आहे", "कोणता चांगला", "कोणता ठीक"]):
                if "mr" in lang_code:
                    followup = " आपण किती एकर जमिनीवर पेरणी करणार आहात?" if not context_state["acreage"] else " आपण किती किलो बियाणे घेणार आहात?"
                    direct_reply = "उत्पादनासाठी गव्हामध्ये लोकवन आणि हरभऱ्यामध्ये दिग्विजय ही व्हरायटी सर्वोत्तम आहे!" + followup
                else:
                    direct_reply = "उपज के लिए गेहूँ में लोकवन और चने में दिग्विजय सबसे उत्तम किस्म है! आप कितने एकड़ के लिए सोच रहे हैं?"

            elif any(q in user_text for q in ["दर काय", "भाव काय", "किंमत काय", "काय भाव", "का भाव", "रेट काय", "किंमत"]):
                if "mr" in lang_code:
                    direct_reply = "प्रमाणित लोकवन गहू ४२ रुपये किलो आणि हरभरा ७८ रुपये किलो आहे. बुकिंगसाठी आमच्या टीमने आपल्याला कॉल करावा का?"
                else:
                    direct_reply = "प्रमाणित लोकवन गेहूँ ४२ रुपये किलो और चना ७८ रुपये किलो है। क्या बुकिंग के लिए हमारी टीम आपको कॉल करे?"

            elif "लोकवन" in user_text and any(q in user_text for q in ["माहिती", "सांगा", "बद्दल", "फायदे"]):
                if "mr" in lang_code:
                    direct_reply = "लोकवन गव्हाची ओंबी मोठी भरते, दाणा टपोरा येतो आणि एकरी १८ ते २० क्विंटल उत्पादन मिळते! बुकिंग करायची आहे का?"
                else:
                    direct_reply = "लोकवन गेहूँ की बाली बड़ी और दाना चमकदार होता है, प्रति एकड़ १८ से २० क्विंटल पैदावार मिलती है!"

            elif "शरबती" in user_text and any(q in user_text for q in ["माहिती", "सांगा", "बद्दल", "फायदे"]):
                if "mr" in lang_code:
                    direct_reply = "शरबती गहू खाण्यासाठी अत्यंत चवदार व मऊ चपातीसाठी प्रसिद्ध आहे आणि बाजारात चांगला भाव मिळतो!"
                else:
                    direct_reply = "शरबती गेहूँ खाने में स्वादिष्ट और मुलायम रोटियों के लिए जाना जाता है, मंडी में बढ़िया भाव मिलता है!"

            # Deterministic Turn Progression for Samruddhi Agritech Agent
            elif is_agri_agent and "mr" in lang_code:
                if dialogue_step == 0:
                    dialogue_step = 1
                    direct_reply = "खूप छान! आपण बियाणे आता खरेदी करू इच्छिता की नंतर?"
                elif dialogue_step == 1:
                    dialogue_step = 2
                    direct_reply = "काही हरकत नाही! आपण किती एकर जमिनीवर पेरणी करण्याचे ठरवले आहे?"
                elif dialogue_step == 2:
                    dialogue_step = 3
                    prefix = f"{context_state['acreage']} साठी खूप छान! " if context_state['acreage'] else "काही हरकत नाही! "
                    direct_reply = f"{prefix}साधारण किती किलो बियाणे हवे आहे किंवा दर जाणून घ्यायचे आहेत का?"
                elif dialogue_step == 3:
                    dialogue_step = 4
                    direct_reply = "आमच्याकडे लोकवन गहू ४२ रुपये किलो आणि दिग्विजय हरभरा ७८ रुपये किलो आहे. बुकिंगसाठी आमच्या प्रतिनिधीकडून कॉल हवा आहे का?"
                elif dialogue_step >= 4:
                    dialogue_step = 5
                    direct_reply = "नक्कीच! समृद्धी ॲग्रीटेक मध्ये संपर्क केल्याबद्दल खूप धन्यवाद, आपला दिवस शुभ जावो, नमस्कार!"
                    should_terminate_after_reply = True

            if direct_reply:
                full_reply = direct_reply
                logger.info(f"[SarvamTelephony] Dialogue Engine resolved: step={dialogue_step}, reply='{full_reply}'")
            else:
                dynamic_system_prompt = system_prompt
                ctx_parts = []
                if context_state["crop"]:
                    ctx_parts.append(f"पिक: {context_state['crop']}")
                if context_state["timing"]:
                    ctx_parts.append(f"खरेदी वेळ: {context_state['timing']}")
                if context_state["acreage"]:
                    ctx_parts.append(f"जमीन: {context_state['acreage']} (ALREADY KNOWN - DO NOT ASK FOR ACREAGE AGAIN)")
                if context_state["quantity"]:
                    ctx_parts.append(f"प्रमाण: {context_state['quantity']} (ALREADY KNOWN - DO NOT ASK FOR QUANTITY AGAIN)")
                if context_state["variety"]:
                    ctx_parts.append(f"पसंतीची व्हरायटी: {context_state['variety']}")

                if ctx_parts:
                    dynamic_system_prompt += f"\n\n[CURRENT SAVED CALL CONTEXT: {' | '.join(ctx_parts)}]"

                full_reply = await self.generate_llm_response(conversation_history, dynamic_system_prompt)

            # Extra Safety: If acreage is known, never ask for acreage again
            if context_state["acreage"] and any(w in full_reply for w in ["किती एकर", "कितने एकड़"]):
                logger.info(f"[SarvamTelephony] Acreage {context_state['acreage']} already known. Suppressing duplicate question.")
                if "mr" in lang_code:
                    full_reply = f"{context_state['acreage']} साठी खूप छान! साधारण किती किलो बियाणे हवे आहे किंवा दर जाणून घ्यायचे आहेत का?"
                else:
                    full_reply = f"{context_state['acreage']} के लिए बहुत बढ़िया! लगभग कितने किलो बीज चाहिए या भाव जानना चाहेंगे?"

            # Extra Safety: Exact duplicate reply suppression
            if any(full_reply.strip("।,?!. ") == prev.strip("।,?!. ") for prev in prev_agent_texts[-3:]):
                logger.info(f"[SarvamTelephony] Exact repeat detected in '{full_reply}'. Progressing turn.")
                if "mr" in lang_code:
                    full_reply = "नक्कीच! अधिक माहिती आणि बुकिंगसाठी आमच्या प्रतिनिधीकडून कॉल हवा आहे का?"
                else:
                    full_reply = "बिल्कुल! अधिक जानकारी और बुकिंग के लिए क्या हमारे प्रतिनिधि आपको कॉल करें?"

            # Strict Marathi Language Guard: Prevent any Hindi dialect leak in Marathi calls
            if "mr" in lang_code:
                hindi_to_marathi = {
                    "बहुत बढ़िया": "खूप छान",
                    "बहुत बढीया": "खूप छान",
                    "बीज": "बियाणे",
                    "बीजों": "बियाण्यांचे",
                    "गेहूँ": "गहू",
                    "चने": "हरभरा",
                    "चना": "हरभरा",
                    "बुवाई": "पेरणी",
                    "बताइए": "सांगा",
                    "बताएं": "सांगा",
                    "बता दीजिए": "सांगा",
                    "करना चाहते हैं": "करू इच्छिता",
                    "चाहेंगे": "इच्छिता",
                    "कितने एकड़": "किती एकर",
                    "कितने किलोग्राम": "किती किलो",
                    "आवश्यकता होगी": "गरज असेल",
                    "समय देने के लिए धन्यवाद": "वेळ दिल्याबद्दल धन्यवाद",
                    "समय देने के लिए आपका बहुत धन्यवाद": "वेळ दिल्याबद्दल खूप धन्यवाद",
                    "आपका दिन शुभ हो": "आपला दिवस शुभ जावो",
                    "जी बिल्कुल": "नक्कीच",
                    "कोई बात नहीं": "काही हरकत नाही",
                }
                for h_w, m_w in hindi_to_marathi.items():
                    full_reply = full_reply.replace(h_w, m_w)

            if not full_reply:
                full_reply = "सांगा, मी आपली काय मदत करू शकतो?" if "mr" in lang_code else "जी, बताइए मैं आपकी कैसे सहायता कर सकता हूँ?"

            logger.info(f"[SarvamTelephony] Full agent response: '{full_reply}'")

            # Synthesize and stream audio
            reply_mulaw = await self.synthesize_speech(full_reply, voice=voice_id, language_code=lang_code)
            if reply_mulaw:
                total_latency = round((time.time() - t_turn_start) * 1000)
                logger.info(f"[SarvamTelephony] >> Ultra-fast Time To First Audio: {total_latency}ms! <<")
                await play_audio_task(reply_mulaw)
            conversation_history.append({"role": "assistant", "content": full_reply})

            # Persist assistant transcript segment
            async with AsyncSessionLocal() as session:
                stmt = select(Transcript).where(Transcript.call_id == call_id)
                tr = (await session.execute(stmt)).scalar_one_or_none()
                if tr:
                    session.add(
                        TranscriptSegment(
                            transcript_id=tr.id,
                            speaker="agent",
                            text=full_reply,
                            start_time=round(agent_speech_start - call_start_time, 2),
                            end_time=round(time.time() - call_start_time, 2),
                            sequence=sequence_counter,
                            confidence=1.0,
                        )
                    )
                    await session.commit()
            sequence_counter += 1

            # Check if agent concluded call
            closing_phrases = ["धन्यवाद", "अलविदा", "नमस्कार", "शुभ हो", "bye"]
            if any(w in full_reply for w in closing_phrases):
                user_is_closing = any(w in user_text.lower() for w in ["ठीक", "अच्छा", "ok", "okay", "नहीं", "bye", "रखो", "काटो", "नो", "no", "ना", "धन्यवाद", "थैंक यू"])
                if user_is_closing or "शुभ हो" in full_reply or "समय देने के लिए" in full_reply:
                    logger.info("[SarvamTelephony] Natural conversational wrap-up concluded. Hanging up carrier call.")
                    await asyncio.sleep(1.0)
                    try:
                        from app.services.telephony_service import telephony_service
                        uuid_to_hangup = carrier_call_uuid or stream_id
                        if uuid_to_hangup:
                            await telephony_service.hangup_live_telephony_call(
                                call_uuid=uuid_to_hangup,
                                auth_id=carrier_auth_id,
                                auth_token=carrier_auth_token,
                            )
                    except Exception:
                        pass
                    try:
                        await websocket.close()
                    except Exception:
                        pass
                    return

        try:
            while True:
                try:
                    msg_text = await asyncio.wait_for(websocket.receive_text(), timeout=6.0)
                except asyncio.TimeoutError:
                    logger.info(f"[SarvamTelephony] Inactivity watchdog: zero audio received for 6.0s on call {call_id} (caller disconnected). Concluding call.")
                    break
                msg = json.loads(msg_text)
                event = msg.get("event")

                # Handle VoBiz stream start event
                if event == "start":
                    start_data = msg.get("start") or {}
                    stream_id = (
                        start_data.get("streamId")
                        or start_data.get("stream_id")
                        or msg.get("streamId")
                        or call_id
                    )
                    logger.info(f"[SarvamTelephony] VoBiz start event received for streamId: {stream_id}. Triggering opening greeting instantly!")
                    if not greeting_delivered:
                        current_turn_task = asyncio.create_task(deliver_greeting())

                elif event == "media":
                    now = time.time()
                    if not stream_id:
                        stream_id = msg.get("streamId") or msg.get("media", {}).get("streamId") or call_id

                    # Safeguard: If start event had no streamId or was missed, deliver greeting on first audio packet
                    if not greeting_delivered and not is_agent_speaking:
                        current_turn_task = asyncio.create_task(deliver_greeting())

                    media_payload = msg.get("media", {}).get("payload", "")
                    if not media_payload:
                        continue

                    chunk = base64.b64decode(media_payload)
                    pcm_chunk = audioop.ulaw2lin(chunk, 2)
                    rms = audioop.rms(pcm_chunk, 2)
                    recorded_timeline.append((now - call_start_time, "customer", chunk))

                    # 1. Caller Barge-In with Acoustic Echo Immunity:
                    # Protect agent from self-interrupting on phone speakerphone echo.
                    # First 1.5s of any agent utterance is completely immune to barge-in.
                    # Afterward, require genuine loud caller speech (RMS > 1600 for >= 6 chunks = 120ms).
                    if is_agent_speaking:
                        time_since_speech_started = now - agent_speech_started_time
                        if time_since_speech_started > 1.5 and rms > 1600:
                            barge_in_streak += 1
                            if barge_in_streak >= 6:
                                logger.info(f"[SarvamTelephony] Caller interrupted agent (RMS: {rms}, streak: {barge_in_streak}). Clearing playback buffer.")
                                if current_turn_task and not current_turn_task.done():
                                    current_turn_task.cancel()
                                await self.stop_playback_and_clear(websocket, stream_id)
                                is_agent_speaking = False
                                agent_finished_speaking_time = now
                                barge_in_streak = 0
                                is_user_speaking = True
                                caller_turn_start_time = now
                                audio_buffer.clear()
                                audio_buffer.extend(chunk)
                                last_speech_time = now
                        else:
                            barge_in_streak = 0
                        continue

                    barge_in_streak = 0

                    # 2. Speakerphone / Network Echo Suppression Grace Window (350ms after agent stops)
                    if (now - agent_finished_speaking_time < 0.35) and rms < 650:
                        continue

                    # 3. Conversational Voice Activity Detection
                    if rms > energy_threshold:
                        if not is_user_speaking:
                            is_user_speaking = True
                            caller_turn_start_time = now
                            logger.debug(f"[SarvamTelephony] Caller started speaking (RMS: {rms})")
                            # Note: Never cancel current_turn_task here! When agent is synthesizing
                            # response, ambient noise or second syllables must NOT abort the response.
                        audio_buffer.extend(chunk)
                        last_speech_time = now
                    elif is_user_speaking:
                        audio_buffer.extend(chunk)
                        silence_threshold = 0.95 if len(audio_buffer) < 16000 else 0.80
                        if now - last_speech_time > silence_threshold:
                            is_user_speaking = False
                            user_audio = bytes(audio_buffer)
                            audio_buffer.clear()
                            t_start = caller_turn_start_time
                            t_end = last_speech_time

                            # Require at least 200ms (1600 bytes) of genuine speech to prevent triggering on background clicks
                            if len(user_audio) < 1600:
                                continue

                            # Launch turn processing task asynchronously
                            current_turn_task = asyncio.create_task(
                                process_caller_turn(user_audio, t_start, t_end)
                            )

                elif event in ("stop", "hangup", "disconnect"):
                    logger.info(f"[SarvamTelephony] Call end event received from VoBiz: {event}")
                    break

        except WebSocketDisconnect:
            logger.info(f"[SarvamTelephony] VoBiz WebSocket disconnected for call {call_id}")
        except Exception as e:
            logger.error(f"[SarvamTelephony] WebSocket error during call {call_id}: {e}", exc_info=True)
        finally:
            if current_turn_task and not current_turn_task.done():
                current_turn_task.cancel()

            # Safeguard: ensure live phone call is disconnected on carrier side
            try:
                from app.services.telephony_service import telephony_service
                uuid_to_hangup = carrier_call_uuid or stream_id
                if uuid_to_hangup:
                    await telephony_service.hangup_live_telephony_call(
                        call_uuid=uuid_to_hangup,
                        auth_id=carrier_auth_id,
                        auth_token=carrier_auth_token,
                    )
            except Exception as e:
                logger.debug(f"[SarvamTelephony] Final carrier hangup safeguard note: {e}")

            call_duration = round(time.time() - call_start_time, 2)
            logger.info(f"[SarvamTelephony] Finalizing call {call_id} (Duration: {call_duration}s, Audio events: {len(recorded_timeline)})")

            # 1. Build mixed WAV recording
            wav_bytes = self._build_call_wav(recorded_timeline, call_duration)

            # Check if genuine live audio was captured from customer
            customer_audio_events = [c for _, spk, c in recorded_timeline if spk == "customer" and c]

            # ONLY fallback to synthetic reconstruction if NO genuine caller audio at all was captured from network stream
            if not recorded_timeline or not customer_audio_events:
                logger.info(f"[SarvamTelephony] Zero live audio chunks captured from stream; checking fallback...")
                try:
                    async with AsyncSessionLocal() as rec_session:
                        from app.services.storage.audio_generator import reconstruct_call_audio_from_transcript
                        reconstructed = await reconstruct_call_audio_from_transcript(rec_session, call_id, duration_seconds=call_duration)
                        if reconstructed and len(reconstructed) > 100:
                            wav_bytes = reconstructed
                except Exception as rec_err:
                    logger.warning(f"[SarvamTelephony] Audio reconstruction fallback notice: {rec_err}")
            else:
                logger.info(f"[SarvamTelephony] Preserved authentic 2-way live recording ({len(customer_audio_events)} caller audio chunks).")

            storage_key = f"calls/{call_id}/recording.wav"

            try:
                await storage_service.upload(
                    key=storage_key,
                    data=wav_bytes,
                    content_type="audio/wav",
                )
                logger.info(f"[SarvamTelephony] Saved call recording to storage: {storage_key} ({len(wav_bytes)} bytes)")
            except Exception as e:
                logger.warning(f"[SarvamTelephony] Failed to upload call recording: {e}")

            # 2. Update Database with Recording row and Call recording_url
            async with AsyncSessionLocal() as session:
                call = await session.get(Call, call_id)
                if call:
                    call.status = "completed"
                    call.ended_at = datetime.now(UTC)
                    call.duration = call_duration
                    call.transcript_url = f"/api/v1/calls/{call.id}/transcript"
                    call.recording_url = f"/api/v1/calls/{call.id}/recording"

                    rec_stmt = select(Recording).where(Recording.call_id == call_id)
                    rec = (await session.execute(rec_stmt)).scalar_one_or_none()
                    if not rec:
                        rec = Recording(
                            tenant_id=call.tenant_id,
                            call_id=call.id,
                            storage_key=storage_key,
                            bucket=getattr(settings, "S3_BUCKET", "voxora-recordings"),
                            content_type="audio/wav",
                            file_size=len(wav_bytes),
                            duration=call_duration,
                            status="ready",
                        )
                        session.add(rec)
                    else:
                        rec.storage_key = storage_key
                        rec.file_size = len(wav_bytes)
                        rec.duration = call_duration
                        rec.status = "ready"

                    try:
                        await session.commit()
                    except Exception as commit_err:
                        await session.rollback()
                        logger.debug(f"[SarvamTelephony] Recording commit race handled: {commit_err}")

                    # Export call artifacts directly to root data/ folder
                    try:
                        from app.services.data_exporter import data_exporter
                        from app.services.lead_intelligence_service import lead_intelligence_service

                        if wav_bytes:
                            data_exporter.export_call_recording(call_id, wav_bytes)

                        seg_stmt = select(TranscriptSegment).join(Transcript).where(Transcript.call_id == call_id).order_by(TranscriptSegment.sequence.asc())
                        seg_res = await session.execute(seg_stmt)
                        segs = [
                            {
                                "speaker": s.speaker,
                                "text": s.text,
                                "start_time": s.start_time,
                                "end_time": s.end_time,
                                "confidence": s.confidence,
                            }
                            for s in seg_res.scalars().all()
                        ]

                        intel = await lead_intelligence_service.analyze_call(session, call, segments=segs)

                        # Automatic Follow-up Call Scheduling
                        try:
                            from app.models.lead import Followup
                            from app.services.callback_time import schedule_from_transcript
                            
                            f_info = intel.get("followup") if intel else None
                            full_transcript = "\n".join(f"{s.get('speaker', 'speaker').title()}: {s.get('text', '')}" for s in segs)
                            parsed_callback_time = schedule_from_transcript(full_transcript)
                            
                            requires_followup = False
                            sched_time = parsed_callback_time
                            reason_action = "Scheduled follow-up"
                            matched_text = None
                            
                            if parsed_callback_time:
                                requires_followup = True
                                reason_action = f"Customer requested callback for {parsed_callback_time.strftime('%d %b %Y, %I:%M %p')}"
                                matched_text = f_info.get("matched_utterance") if f_info else "Specific callback time requested"
                            elif f_info and f_info.get("requires_followup"):
                                requires_followup = True
                                reason_action = f"{f_info.get('name')}: {f_info.get('action')}"
                                matched_text = f_info.get("matched_utterance")
                                sched_iso = f_info.get("suggested_scheduled_at")
                                if sched_iso and not sched_time:
                                    try:
                                        sched_time = datetime.fromisoformat(sched_iso.replace("Z", "+00:00"))
                                    except Exception:
                                        pass
                            elif (call.disposition or "").lower() == "callback_requested":
                                requires_followup = True
                                reason_action = "Customer requested callback during conversation"
                                matched_text = "Callback requested"

                            call_phone = call.phone_number or call.caller_number
                            if requires_followup and call_phone:
                                fu_stmt = select(Followup).where(Followup.call_id == call.id)
                                existing_fu = (await session.execute(fu_stmt)).scalar_one_or_none()
                                notes_txt = f"{reason_action}. (Matched: '{matched_text or 'callback'}')"
                                target_time = sched_time or (datetime.now(UTC) + timedelta(hours=2))

                                if not existing_fu:
                                    new_fu = Followup(
                                        tenant_id=call.tenant_id,
                                        contact_id=call.contact_id,
                                        agent_id=call.agent_id,
                                        call_id=call.id,
                                        phone_number=call_phone,
                                        scheduled_at=target_time,
                                        status="scheduled",
                                        notes=notes_txt,
                                    )
                                    session.add(new_fu)
                                    logger.info(f"[SarvamTelephony] Auto-scheduled Followup for call {call.id} at {target_time}")
                                else:
                                    existing_fu.scheduled_at = target_time
                                    existing_fu.notes = notes_txt
                                    existing_fu.status = "scheduled"
                                call.disposition = "callback_requested"
                        except Exception as fu_err:
                            logger.warning(f"[SarvamTelephony] Auto-followup scheduling note: {fu_err}")

                        data_exporter.export_call_transcript(
                            call_id=call_id,
                            phone_number=call.phone_number or call.caller_number or "",
                            agent_name=agent_name,
                            duration=call_duration,
                            disposition=call.disposition or "completed",
                            segments=segs,
                            intelligence_data=intel,
                        )
                        if intel:
                            data_exporter.export_call_intelligence(
                                call_id=call_id,
                                intelligence_data=intel,
                                phone_number=call.phone_number or call.caller_number or "",
                                disposition=call.disposition or "",
                            )
                        await session.commit()
                    except Exception as export_err:
                        logger.warning(f"[SarvamTelephony] Post-call data export note: {export_err}")


sarvam_telephony_service = SarvamTelephonyService()
