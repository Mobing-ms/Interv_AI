import os
import io
import wave
import struct
import hashlib
import logging
from typing import Optional, Dict, Tuple, Any
from app.config import settings

logger = logging.getLogger("intervai.tts_service")

# Map human-readable language names to ISO 639-1 language codes
LANGUAGE_CODE_MAP = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "hindi": "hi",
    "mandarin": "zh-cn",
    "japanese": "ja",
    "portuguese": "pt",
    "italian": "it",
    "dutch": "nl",
}


def create_minimal_wav_bytes(duration_seconds: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Generates a valid lightweight in-memory PCM WAV audio buffer for offline / mock testing."""
    num_samples = int(sample_rate * duration_seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)  # Mono
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(sample_rate)
        # Gentle sine tone / silence
        data = bytearray(num_samples * 2)
        wav.writeframes(data)
    return buf.getvalue()


class BaseTTSProvider:
    """Abstract base provider for Text-To-Speech synthesis."""

    def synthesize(self, text: str, lang_code: str) -> Tuple[bytes, str]:
        """
        Synthesizes audio bytes.
        Returns: (audio_bytes, mime_type)
        """
        raise NotImplementedError


class CloudTTSProvider(BaseTTSProvider):
    """Cloud TTS provider utilizing gTTS with offline fallback."""

    def synthesize(self, text: str, lang_code: str) -> Tuple[bytes, str]:
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang=lang_code, slow=False)
            fp = io.BytesIO()
            tts.write_to_fp(fp)
            return fp.getvalue(), "audio/mpeg"
        except Exception as e:
            logger.info("Cloud TTS unavailable or failed (%s). Falling back to mock audio generator.", e)
            return create_minimal_wav_bytes(0.5), "audio/wav"


class MockTTSProvider(BaseTTSProvider):
    """Fast deterministic mock TTS provider for testing and offline environments."""

    def synthesize(self, text: str, lang_code: str) -> Tuple[bytes, str]:
        # Generate minimal WAV audio with duration proportional to word count (min 0.3s)
        word_count = len(text.split())
        duration = min(3.0, max(0.3, word_count * 0.15))
        return create_minimal_wav_bytes(duration), "audio/wav"


class TTSService:
    """
    Centralized TTS Service supporting provider abstraction, audio caching
    for repeated phrases, and language selection.
    """

    def __init__(self, provider: Optional[BaseTTSProvider] = None, cache_dir: Optional[str] = None):
        self.provider = provider or CloudTTSProvider()
        self.cache_dir = cache_dir or os.path.join(os.path.dirname(__file__), "..", "..", "cache", "tts")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._memory_cache: Dict[str, Tuple[bytes, str]] = {}

    def _resolve_lang_code(self, language: str) -> str:
        clean = (language or "English").strip().lower()
        return LANGUAGE_CODE_MAP.get(clean, "en")

    def _get_cache_key(self, text: str, lang_code: str) -> str:
        normalized = f"{text.strip().lower()}:{lang_code}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def synthesize_speech(
        self,
        text: str,
        language: str = "English",
        voice_style: str = "neutral",
    ) -> Dict[str, Any]:
        """
        Synthesizes speech audio for the given text.
        Returns:
            {
                "text": text,
                "audio_url": f"/session/tts/audio/{cache_key}",
                "cache_key": cache_key,
                "language": lang_code,
                "is_cached": bool
            }
        """
        lang_code = self._resolve_lang_code(language)
        cache_key = self._get_cache_key(text, lang_code)

        # 1. Check memory cache
        is_cached = cache_key in self._memory_cache

        # 2. Check disk cache
        if not is_cached:
            disk_path = os.path.join(self.cache_dir, f"{cache_key}.bin")
            meta_path = os.path.join(self.cache_dir, f"{cache_key}.meta")
            if os.path.exists(disk_path) and os.path.exists(meta_path):
                with open(disk_path, "rb") as f:
                    audio_bytes = f.read()
                with open(meta_path, "r", encoding="utf-8") as f:
                    mime = f.read().strip()
                self._memory_cache[cache_key] = (audio_bytes, mime)
                is_cached = True

        # 3. Generate if not cached
        if not is_cached:
            audio_bytes, mime = self.provider.synthesize(text, lang_code)
            self._memory_cache[cache_key] = (audio_bytes, mime)
            try:
                disk_path = os.path.join(self.cache_dir, f"{cache_key}.bin")
                meta_path = os.path.join(self.cache_dir, f"{cache_key}.meta")
                with open(disk_path, "wb") as f:
                    f.write(audio_bytes)
                with open(meta_path, "w", encoding="utf-8") as f:
                    f.write(mime)
            except Exception as e:
                logger.warning("Failed to write TTS disk cache: %s", e)

        return {
            "text": text,
            "audio_url": f"/session/tts/audio/{cache_key}",
            "cache_key": cache_key,
            "language": lang_code,
            "is_cached": is_cached,
        }

    def get_cached_audio(self, cache_key: str) -> Optional[Tuple[bytes, str]]:
        """Retrieves raw audio bytes and MIME type by cache key."""
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        disk_path = os.path.join(self.cache_dir, f"{cache_key}.bin")
        meta_path = os.path.join(self.cache_dir, f"{cache_key}.meta")
        if os.path.exists(disk_path) and os.path.exists(meta_path):
            with open(disk_path, "rb") as f:
                audio_bytes = f.read()
            with open(meta_path, "r", encoding="utf-8") as f:
                mime = f.read().strip()
            self._memory_cache[cache_key] = (audio_bytes, mime)
            return audio_bytes, mime

        return None


default_tts_service = TTSService()
