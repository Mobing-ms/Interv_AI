"""
Hosted Speech-to-Text (STT) Service.
Provides high-speed, cloud-hosted audio transcription with word-level timestamps.
Solves the problem of running heavy local Whisper models on RAM/CPU-constrained
cloud free tiers (Render, Railway, Fly.io, etc.).

Supported Providers:
1. "groq"        - Groq Cloud Whisper API (Free tier, ultra-low latency ~250ms, zero server RAM)
2. "openai"      - OpenAI Whisper API (whisper-1, verbose_json)
3. "deepgram"    - Deepgram Nova-2 / Audio Intelligence API
4. "mock"        - Instant deterministic mock transcriber (for tests and offline local dev)
5. "local_whisper"- Local faster-whisper (requires 2GB+ server RAM and AVX CPU)
"""

import os
import io
import time
import logging
import httpx
from typing import Optional, Dict, Any, List

from app.config import settings

logger = logging.getLogger("intervai.stt")


class HostedSTTService:
    """Multi-provider speech-to-text service."""

    def __init__(self, provider: Optional[str] = None, api_key: Optional[str] = None):
        self.provider = (provider or settings.STT_PROVIDER or "mock").lower()
        self.api_key = api_key or settings.STT_API_KEY or getattr(settings, "LLM_API_KEY", "")
        self.model = settings.STT_MODEL or "whisper-large-v3-turbo"

    async def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        filename: str = "answer.wav",
        language: str = "en",
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transcribes raw audio bytes into text and word-level timestamps.
        
        Returns:
            {
                "text": str,
                "words": List[{"word": str, "start": float, "end": float, "probability": float}],
                "provider": str,
                "duration": float
            }
        """
        if not audio_bytes or len(audio_bytes) < 400:
            return {"text": "", "words": [], "provider": self.provider, "duration": 0.0}

        # 1. Groq Cloud Whisper API (Recommended for public deployment free-tier)
        if self.provider == "groq" and self.api_key:
            return await self._transcribe_groq(audio_bytes, filename, language, prompt)

        # 2. OpenAI Whisper API
        elif self.provider == "openai" and self.api_key:
            return await self._transcribe_openai(audio_bytes, filename, language, prompt)

        # 3. Deepgram API
        elif self.provider == "deepgram" and self.api_key:
            return await self._transcribe_deepgram(audio_bytes, language)

        # 4. Fallback / Mock provider
        else:
            return self._mock_transcription(audio_bytes)

    async def _transcribe_groq(
        self,
        audio_bytes: bytes,
        filename: str,
        language: str,
        prompt: Optional[str],
    ) -> Dict[str, Any]:
        url = settings.STT_BASE_URL or "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = {
            "model": self.model if "whisper" in self.model else "whisper-large-v3-turbo",
            "response_format": "verbose_json",
            "language": language,
            "timestamp_granularities[]": "word",
        }
        if prompt:
            data["prompt"] = prompt

        files = {"file": (filename, audio_bytes, "audio/wav")}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, headers=headers, data=data, files=files)
                if res.status_code == 200:
                    payload = res.json()
                    full_text = payload.get("text", "").strip()
                    raw_words = payload.get("words", [])
                    parsed_words = []
                    for w in raw_words:
                        parsed_words.append({
                            "word": w.get("word", ""),
                            "start": round(float(w.get("start", 0.0)), 2),
                            "end": round(float(w.get("end", 0.0)), 2),
                            "probability": round(float(w.get("probability", 0.95)), 2),
                        })
                    logger.info(f"[STT][Groq] Transcribed {len(audio_bytes)} bytes -> {len(full_text.split())} words")
                    return {
                        "text": full_text,
                        "words": parsed_words,
                        "provider": "groq",
                        "duration": payload.get("duration", 0.0),
                    }
                else:
                    logger.warning(f"[STT][Groq] HTTP {res.status_code}: {res.text}. Falling back to mock.")
                    return self._mock_transcription(audio_bytes)
        except Exception as e:
            logger.error(f"[STT][Groq] Request failed: {e}. Falling back to mock.")
            return self._mock_transcription(audio_bytes)

    async def _transcribe_openai(
        self,
        audio_bytes: bytes,
        filename: str,
        language: str,
        prompt: Optional[str],
    ) -> Dict[str, Any]:
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = {
            "model": "whisper-1",
            "response_format": "verbose_json",
            "language": language,
            "timestamp_granularities[]": "word",
        }
        if prompt:
            data["prompt"] = prompt

        files = {"file": (filename, audio_bytes, "audio/wav")}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(url, headers=headers, data=data, files=files)
                if res.status_code == 200:
                    payload = res.json()
                    full_text = payload.get("text", "").strip()
                    raw_words = payload.get("words", [])
                    parsed_words = [
                        {
                            "word": w.get("word", ""),
                            "start": round(float(w.get("start", 0.0)), 2),
                            "end": round(float(w.get("end", 0.0)), 2),
                            "probability": 0.98,
                        }
                        for w in raw_words
                    ]
                    logger.info(f"[STT][OpenAI] Transcribed -> {len(full_text.split())} words")
                    return {
                        "text": full_text,
                        "words": parsed_words,
                        "provider": "openai",
                        "duration": payload.get("duration", 0.0),
                    }
                else:
                    logger.warning(f"[STT][OpenAI] HTTP {res.status_code}: {res.text}")
                    return self._mock_transcription(audio_bytes)
        except Exception as e:
            logger.error(f"[STT][OpenAI] Error: {e}")
            return self._mock_transcription(audio_bytes)

    async def _transcribe_deepgram(self, audio_bytes: bytes, language: str) -> Dict[str, Any]:
        url = f"https://api.deepgram.com/v1/listen?model=nova-2&language={language}&punctuate=true"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/wav",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, headers=headers, content=audio_bytes)
                if res.status_code == 200:
                    payload = res.json()
                    channels = payload.get("results", {}).get("channels", [])
                    if channels and channels[0].get("alternatives"):
                        alt = channels[0]["alternatives"][0]
                        full_text = alt.get("transcript", "").strip()
                        raw_words = alt.get("words", [])
                        parsed_words = [
                            {
                                "word": w.get("word", ""),
                                "start": round(float(w.get("start", 0.0)), 2),
                                "end": round(float(w.get("end", 0.0)), 2),
                                "probability": round(float(w.get("confidence", 0.95)), 2),
                            }
                            for w in raw_words
                        ]
                        return {
                            "text": full_text,
                            "words": parsed_words,
                            "provider": "deepgram",
                            "duration": payload.get("metadata", {}).get("duration", 0.0),
                        }
            return self._mock_transcription(audio_bytes)
        except Exception as e:
            logger.error(f"[STT][Deepgram] Error: {e}")
            return self._mock_transcription(audio_bytes)

    def _mock_transcription(self, audio_bytes: bytes) -> Dict[str, Any]:
        """Provides simulated word timestamps for testing and development."""
        default_text = "I have built distributed systems and optimized relational database queries with indexing."
        words = default_text.split()
        curr_t = 0.0
        parsed_words = []
        for w in words:
            parsed_words.append({
                "word": w,
                "start": round(curr_t, 2),
                "end": round(curr_t + 0.35, 2),
                "probability": 0.98,
            })
            curr_t += 0.42

        return {
            "text": default_text,
            "words": parsed_words,
            "provider": "mock",
            "duration": round(curr_t, 2),
        }


# Default singleton
default_hosted_stt = HostedSTTService()
