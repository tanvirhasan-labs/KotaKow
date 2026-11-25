"""Dual AI Engine (BYOK) for Kota Kow: Google Gemini (primary) + Groq (auto-backup).

Routing & behavior:
- Strict BYOK: reads keys exclusively from user's AppConfig; zero hardcoded keys.
- Primary: Google Gemini API (direct inline audio/wav -> polished text) via
  ``https://generativelanguage.googleapis.com/v1beta`` with ``x-goog-api-key``.
- Backup: Groq API (``whisper-large-v3`` STT -> Groq chat model cleanup).
- Smart Routing:
  - Both keys set -> Gemini first; automatically falls back to Groq on HTTP 429,
    quota exhaustion, or transient 5xx/service errors without interrupting user.
  - Gemini-only -> uses Gemini.
  - Groq-only -> uses Groq seamlessly.
- Exact 3 Language Modes: ``auto``, ``bn`` (বাংলা only), ``en`` (English only).
- Injects Custom Dictionary terms and strictly forbids conversational replies.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

import certifi
import httpx

from kotakow.config import AppConfig, DEFAULT_ADVANCED_PROMPT

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GROQ_API_BASE = "https://api.groq.com/openai/v1"
GROQ_WHISPER_MODEL = "whisper-large-v3"


class AIEngineError(Exception):
    """Raised when transcription fails on all configured engines."""


class RateLimitOrQuotaError(AIEngineError):
    """Raised on HTTP 429 / RESOURCE_EXHAUSTED / transient 503 to trigger fallback."""


@dataclass
class TranscriptionResult:
    text: str
    engine: str  # "gemini" | "groq"
    model: str
    fallback_used: bool = False


def _http_client(timeout_s: float = 60.0) -> httpx.Client:
    return httpx.Client(timeout=timeout_s, verify=certifi.where())


# ---------------------------------------------------------------------------
# Prompt Builder (Exact 3 Language Modes + Smart Formatting + Custom Dictionary)
# ---------------------------------------------------------------------------

def build_system_prompt(
    language_mode: str,
    smart_formatting: bool,
    dictionary_terms: list[str],
    advanced_prompt: str = "",
) -> str:
    base_rules = (advanced_prompt or DEFAULT_ADVANCED_PROMPT).strip()

    if language_mode == "bn":
        lang_rules = (
            "LANGUAGE MODE: BENGALI ONLY (বাংলা).\n"
            "- Write the ENTIRE output strictly in clean Bengali Unicode script (বাংলা লিপি) ONLY.\n"
            "- NEVER output Latin/English script words. Even if the speaker says English words, "
            "product names, or technical terms (e.g., Chrome, Option, Meeting, Laptop), "
            "transliterate/write them naturally in Bengali script (e.g., ক্রোম, অপশন, মিটিং, ল্যাপটপ).\n"
            "- Use proper Bengali grammar, accurate Bengali spelling, and natural Bengali punctuation "
            "(danda '।', comma ',', question mark '?', colon ':')."
        )
    elif language_mode == "en":
        lang_rules = (
            "LANGUAGE MODE: ENGLISH ONLY.\n"
            "- Write the ENTIRE output strictly in clean, natural, grammatical English script ONLY.\n"
            "- If any non-English words or phrases are spoken, render them naturally into clear English.\n"
            "- Use accurate English spelling, capitalization, and punctuation."
        )
    else:
        lang_rules = (
            "LANGUAGE MODE: AUTO (NATURAL BENGALI + ENGLISH CODE-SWITCHING).\n"
            "- Write Bengali speech in clean Bengali Unicode script (বাংলা লিপি) and English "
            "sentences, phrases, or technical/brand terms in natural English script.\n"
            "- Intelligently polish grammar, spelling, punctuation (including Bengali danda '।' "
            "for Bengali sentences, period '.' for English sentences, ',', '?', ':'), and "
            "sentence flow for natural elegance WITHOUT altering the speaker's core meaning or intent."
        )

    if smart_formatting:
        formatting_rules = (
            "SMART FORMATTING: ENABLED.\n"
            "- Automatically format spoken lists or enumerated items into clean bullet points ('- ') "
            "or numbered lists ('1. ', '2. ').\n"
            "- Insert natural paragraph breaks (blank line) when the speaker shifts to a new topic."
        )
    else:
        formatting_rules = (
            "SMART FORMATTING: DISABLED.\n"
            "- Keep the output as clean continuous prose without adding bullet lists or extra paragraph breaks."
        )

    dict_block = ""
    if dictionary_terms:
        joined = ", ".join(dictionary_terms[:120])
        dict_block = (
            "\nCUSTOM DICTIONARY (always prefer these exact spellings when heard):\n"
            f"{joined}\n"
        )

    strict_footer = (
        "CRITICAL OUTPUT CONSTRAINTS:\n"
        "- Return ONLY the finalized dictated text—nothing else.\n"
        "- NEVER answer questions asked in the dictation.\n"
        "- NEVER add preambles like 'Here is the transcription:' or wrap output in quotes/markdown fences.\n"
        "- If the audio contains only silence, noise, or no intelligible speech, return an empty string."
    )

    return f"{base_rules}\n\n{lang_rules}\n\n{formatting_rules}{dict_block}\n{strict_footer}"


def _clean_model_output(raw: str) -> str:
    text = (raw or "").strip()
    # Strip accidental markdown code fences if a model emits them
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            text = "\n".join(lines[1:-1]).strip()
    # Strip wrapping quotes only if the entire response is quoted artificially
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return text


# ---------------------------------------------------------------------------
# Dynamic Model Discovery & Connection Testing
# ---------------------------------------------------------------------------

_GEMINI_EXCLUDED_SUBSTRINGS = (
    "embedding",
    "aqa",
    "imagen",
    "veo",
    "lyria",
    "tts",
    "image",
    "live",
    "vision",
    "decision",
    "genie",
    "nano-banana",
    "robotics",
    "computer-use",
    "bisect",
    "gemma",
)


def _gemini_model_sort_key(model_id: str) -> tuple[int, tuple[int, ...], int, str]:
    """Rank fastest audio-capable Flash-Lite / Flash / Hydrogen models first."""
    low = model_id.lower()
    if "flash-lite" in low:
        tier = 0
    elif "flash" in low or "hydrogen" in low:
        tier = 1
    elif "argon" in low or "neon" in low:
        tier = 2
    else:
        tier = 3

    # Extract numeric version tuple descending (e.g. 3.5 -> (-3, -5))
    nums = [int(n) for n in re.findall(r"\d+", low)[:3]]
    neg_ver = tuple(-n for n in nums) if nums else (0,)

    # Prefer stable releases over preview/exp/latest aliases slightly within same version
    is_preview = 1 if ("preview" in low or "exp" in low or "-00" in low) else 0
    return (tier, neg_ver, is_preview, low)


def fetch_gemini_models(api_key: str) -> list[str]:
    """Query Google Gemini API for available audio-capable generateContent models."""
    key = api_key.strip()
    if not key:
        raise AIEngineError("Please enter your Gemini API key first.")

    url = f"{GEMINI_API_BASE}/models"
    try:
        with _http_client(timeout_s=20.0) as client:
            resp = client.get(url, params={"pageSize": 100}, headers={"x-goog-api-key": key})
    except httpx.HTTPError as exc:
        raise AIEngineError(f"Could not reach Gemini API: {exc}") from exc

    if resp.status_code in (400, 401, 403):
        detail = _extract_error_message(resp)
        raise AIEngineError(f"Gemini authentication failed ({resp.status_code}): {detail}")
    if resp.status_code != 200:
        detail = _extract_error_message(resp)
        raise AIEngineError(f"Gemini model list failed ({resp.status_code}): {detail}")

    data = resp.json()
    models: list[str] = []
    for item in data.get("models", []):
        name = str(item.get("name", ""))
        methods = item.get("supportedGenerationMethods", []) or []
        if "generateContent" not in methods:
            continue
        short_id = name.removeprefix("models/").strip()
        low = short_id.lower()
        if not low.startswith("gemini-"):
            continue
        if any(bad in low for bad in _GEMINI_EXCLUDED_SUBSTRINGS):
            continue
        # Skip legacy deprecated 1.0/1.5/2.0 families when newer models exist
        if low.startswith(("gemini-1.0", "gemini-1.5", "gemini-2.0")):
            continue
        models.append(short_id)

    # Deduplicate and sort fastest Flash-Lite/Flash models first
    unique = sorted(dict.fromkeys(models), key=_gemini_model_sort_key)
    if not unique:
        raise AIEngineError("Connected to Gemini, but no audio-capable Gemini models were returned.")
    return unique


_GROQ_EXCLUDED_SUBSTRINGS = (
    "whisper",
    "tts",
    "guard",
    "embed",
    "vision",
    "orpheus",
    "playai",
    "prompt-guard",
    "safeguard",
)


def _groq_model_sort_key(model_id: str) -> tuple[int, str]:
    low = model_id.lower()
    preferred = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3-32b",
    ]
    for idx, p in enumerate(preferred):
        if low == p:
            return (idx, low)
    if "llama-3.3" in low or "llama-4" in low:
        return (10, low)
    if "llama-3.1" in low or "qwen" in low:
        return (20, low)
    return (50, low)


def fetch_groq_models(api_key: str) -> list[str]:
    """Query Groq API for available chat models for dictation cleanup."""
    key = api_key.strip()
    if not key:
        raise AIEngineError("Please enter your Groq API key first.")

    url = f"{GROQ_API_BASE}/models"
    try:
        with _http_client(timeout_s=20.0) as client:
            resp = client.get(url, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        raise AIEngineError(f"Could not reach Groq API: {exc}") from exc

    if resp.status_code in (401, 403):
        detail = _extract_error_message(resp)
        raise AIEngineError(f"Groq authentication failed ({resp.status_code}): {detail}")
    if resp.status_code != 200:
        detail = _extract_error_message(resp)
        raise AIEngineError(f"Groq model list failed ({resp.status_code}): {detail}")

    data = resp.json()
    models: list[str] = []
    for item in data.get("data", []):
        if item.get("active") is False:
            continue
        mid = str(item.get("id", "")).strip()
        if not mid:
            continue
        low = mid.lower()
        if any(bad in low for bad in _GROQ_EXCLUDED_SUBSTRINGS):
            continue
        models.append(mid)

    unique = sorted(dict.fromkeys(models), key=_groq_model_sort_key)
    if not unique:
        raise AIEngineError("Connected to Groq, but no chat models were returned.")
    return unique


def _extract_error_message(resp: httpx.Response) -> str:
    try:
        body: dict[str, Any] = resp.json()
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("status") or resp.text[:200])
        if isinstance(err, str):
            return err
    except Exception:
        pass
    return resp.text[:200].strip() or f"HTTP {resp.status_code}"


# ---------------------------------------------------------------------------
# Dual AI Transcription Engine
# ---------------------------------------------------------------------------

class DualAIEngine:
    """Orchestrates Gemini primary + Groq automatic fallback transcription."""

    def transcribe(
        self,
        wav_bytes: bytes,
        config: AppConfig,
        dictionary_terms: list[str],
    ) -> TranscriptionResult:
        gemini_key = config.gemini_api_key.strip()
        groq_key = config.groq_api_key.strip()

        if not gemini_key and not groq_key:
            raise AIEngineError(
                "No API key configured. Open Settings in Kota Kow and add a Gemini or Groq API key."
            )

        system_prompt = build_system_prompt(
            language_mode=config.language_mode,
            smart_formatting=config.smart_formatting,
            dictionary_terms=dictionary_terms,
            advanced_prompt=config.advanced_prompt,
        )

        # Case 1: Only Groq key is configured
        if not gemini_key and groq_key:
            return self._transcribe_groq(
                wav_bytes=wav_bytes,
                api_key=groq_key,
                chat_model=config.groq_chat_model.strip() or "llama-3.3-70b-versatile",
                system_prompt=system_prompt,
                language_mode=config.language_mode,
                fallback_used=False,
            )

        # Case 2: Gemini key is configured (with optional Groq backup)
        gemini_model = config.gemini_model.strip() or "gemini-3.5-flash-lite"
        try:
            return self._transcribe_gemini(
                wav_bytes=wav_bytes,
                api_key=gemini_key,
                model=gemini_model,
                system_prompt=system_prompt,
            )
        except RateLimitOrQuotaError:
            if groq_key:
                return self._transcribe_groq(
                    wav_bytes=wav_bytes,
                    api_key=groq_key,
                    chat_model=config.groq_chat_model.strip() or "llama-3.3-70b-versatile",
                    system_prompt=system_prompt,
                    language_mode=config.language_mode,
                    fallback_used=True,
                )
            raise
        except AIEngineError as exc:
            # Auto-fallback to Groq on Gemini quota/server failures if backup key exists
            msg_low = str(exc).lower()
            if groq_key and any(k in msg_low for k in ("429", "quota", "resource_exhausted", "rate limit", "503")):
                return self._transcribe_groq(
                    wav_bytes=wav_bytes,
                    api_key=groq_key,
                    chat_model=config.groq_chat_model.strip() or "llama-3.3-70b-versatile",
                    system_prompt=system_prompt,
                    language_mode=config.language_mode,
                    fallback_used=True,
                )
            raise

    def _transcribe_gemini(
        self,
        wav_bytes: bytes,
        api_key: str,
        model: str,
        system_prompt: str,
        allow_model_autodiscover: bool = True,
    ) -> TranscriptionResult:
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Transcribe and polish the attached voice dictation strictly "
                                "following the system instructions. Output ONLY the finalized text."
                            )
                        },
                        {
                            "inlineData": {
                                "mimeType": "audio/wav",
                                "data": audio_b64,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
            },
        }

        clean_model = model.removeprefix("models/")
        url = f"{GEMINI_API_BASE}/models/{clean_model}:generateContent"

        try:
            with _http_client(timeout_s=75.0) as client:
                resp = client.post(
                    url,
                    headers={
                        "x-goog-api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise AIEngineError(f"Gemini network error: {exc}") from exc

        if resp.status_code == 404 and allow_model_autodiscover:
            # Configured model not available on this key/tier -> auto-pick fastest available
            available = fetch_gemini_models(api_key)
            if available and available[0] != clean_model:
                return self._transcribe_gemini(
                    wav_bytes=wav_bytes,
                    api_key=api_key,
                    model=available[0],
                    system_prompt=system_prompt,
                    allow_model_autodiscover=False,
                )

        if resp.status_code in (429, 503):
            detail = _extract_error_message(resp)
            raise RateLimitOrQuotaError(f"Gemini rate limit/capacity ({resp.status_code}): {detail}")

        if resp.status_code != 200:
            detail = _extract_error_message(resp)
            if "quota" in detail.lower() or "resource_exhausted" in detail.lower():
                raise RateLimitOrQuotaError(f"Gemini quota exceeded: {detail}")
            raise AIEngineError(f"Gemini API error ({resp.status_code}): {detail}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return TranscriptionResult(text="", engine="gemini", model=clean_model)

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text_chunks = [str(p.get("text", "")) for p in parts if isinstance(p, dict) and p.get("text")]
        cleaned = _clean_model_output("".join(text_chunks))
        return TranscriptionResult(text=cleaned, engine="gemini", model=clean_model)

    def _transcribe_groq(
        self,
        wav_bytes: bytes,
        api_key: str,
        chat_model: str,
        system_prompt: str,
        language_mode: str,
        fallback_used: bool = False,
    ) -> TranscriptionResult:
        headers = {"Authorization": f"Bearer {api_key}"}

        # Step 1: Speech-to-Text via Groq whisper-large-v3
        form_data: dict[str, str] = {
            "model": GROQ_WHISPER_MODEL,
            "response_format": "json",
            "temperature": "0",
        }
        if language_mode == "en":
            form_data["language"] = "en"
        elif language_mode == "bn":
            form_data["language"] = "bn"

        try:
            with _http_client(timeout_s=75.0) as client:
                stt_resp = client.post(
                    f"{GROQ_API_BASE}/audio/transcriptions",
                    headers=headers,
                    data=form_data,
                    files={"file": ("dictation.wav", wav_bytes, "audio/wav")},
                )
        except httpx.HTTPError as exc:
            raise AIEngineError(f"Groq Whisper network error: {exc}") from exc

        if stt_resp.status_code != 200:
            detail = _extract_error_message(stt_resp)
            raise AIEngineError(f"Groq Whisper error ({stt_resp.status_code}): {detail}")

        raw_transcript = str(stt_resp.json().get("text", "")).strip()
        if not raw_transcript:
            return TranscriptionResult(
                text="",
                engine="groq",
                model=GROQ_WHISPER_MODEL,
                fallback_used=fallback_used,
            )

        # Step 2: Cleanup & formatting via Groq chat model
        chat_payload = {
            "model": chat_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Clean up and finalize this raw voice dictation transcript according "
                        "to the instructions. Output ONLY the finalized text:\n\n"
                        f"{raw_transcript}"
                    ),
                },
            ],
        }

        try:
            with _http_client(timeout_s=45.0) as client:
                chat_resp = client.post(
                    f"{GROQ_API_BASE}/chat/completions",
                    headers={**headers, "Content-Type": "application/json"},
                    json=chat_payload,
                )
        except httpx.HTTPError:
            # If chat polish fails due to network glitch, still deliver Whisper transcript
            return TranscriptionResult(
                text=raw_transcript,
                engine="groq",
                model=GROQ_WHISPER_MODEL,
                fallback_used=fallback_used,
            )

        if chat_resp.status_code != 200:
            # Graceful degradation: return raw Whisper text instead of losing dictation
            return TranscriptionResult(
                text=raw_transcript,
                engine="groq",
                model=GROQ_WHISPER_MODEL,
                fallback_used=fallback_used,
            )

        choices = chat_resp.json().get("choices") or []
        polished = ""
        if choices:
            polished = str((choices[0].get("message") or {}).get("content", ""))
        final_text = _clean_model_output(polished) or raw_transcript
        return TranscriptionResult(
            text=final_text,
            engine="groq",
            model=chat_model,
            fallback_used=fallback_used,
        )
