"""Buster-style reCAPTCHA solver — fully automatic, no user touch.

How it works (same idea as the Buster extension, but headless-friendly and
with no button to press):
  1. If a reCAPTCHA checkbox iframe exists, click it.
  2. If a visual challenge appears, switch to the *audio* challenge.
  3. Download the audio, transcribe it with speech recognition, type the
     answer, submit. On failure, request a new challenge and retry.

Speech-to-text needs ONE of:
  * internet access (default Google web recogniser — free, no key), or
  * Vosk offline model (set VOSK_MODEL_PATH) — needs `pip install vosk`.

MP3 decoding needs `ffmpeg` on PATH (or `pip install pydub` + ffmpeg).
IRCTC login itself uses a text captcha (see OcrSolver); this module covers
payment gateways / flows embedding Google reCAPTCHA.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger("ticket_booker.captcha.recaptcha")


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ensure_wav(src: Path) -> Path:
    """Convert mp3 audio to wav for speech recognition. Returns wav path."""
    if src.suffix.lower() == ".wav":
        return src
    dst = src.with_suffix(".wav")
    # Path 1: pydub (uses ffmpeg under the hood)
    try:
        from pydub import AudioSegment

        AudioSegment.from_file(str(src)).export(str(dst), format="wav")
        return dst
    except Exception as exc:
        log.debug("pydub convert failed: %s", exc)
    # Path 2: raw ffmpeg binary
    if _ffmpeg_available():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), str(dst)],
            check=True, timeout=60,
        )
        return dst
    raise RuntimeError(
        "Cannot decode reCAPTCHA mp3 audio: install ffmpeg "
        "(`sudo apt install ffmpeg` / `brew install ffmpeg`) "
        "or `pip install pydub`."
    )


def transcribe_audio(wav_path: Path, language: str = "en") -> str:
    """Speech-to-text. Tries Google web API, then offline Vosk if configured."""
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise RuntimeError("pip install SpeechRecognition to transcribe audio.") from exc

    recognizer = sr.Recognizer()
    with sr.AudioFile(str(wav_path)) as source:
        audio = recognizer.record(source)

    # 1) Google free web recogniser (needs internet, no key)
    try:
        text = recognizer.recognize_google(audio, language=language)
        return re.sub(r"[^a-zA-Z0-9 ]", "", text).strip()
    except sr.UnknownValueError:
        log.debug("Google STT could not understand audio.")
    except sr.RequestError as exc:
        log.debug("Google STT unreachable: %s", exc)

    # 2) Offline Vosk fallback
    model_path = os.environ.get("VOSK_MODEL_PATH", "")
    if model_path and Path(model_path).exists():
        try:
            return _transcribe_vosk(wav_path, model_path)
        except Exception as exc:
            log.debug("Vosk failed: %s", exc)
    raise RuntimeError("Audio transcription failed (Google STT + Vosk both failed).")


def _transcribe_vosk(wav_path: Path, model_path: str) -> str:
    import json
    import wave

    from vosk import KaldiRecognizer, Model

    wf = wave.open(str(wav_path), "rb")
    if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
        raise RuntimeError("Vosk needs mono 16-bit WAV.")
    rec = KaldiRecognizer(Model(model_path), wf.getframerate())
    parts: list[str] = []
    while True:
        data = wf.readframes(4000)
        if not data:
            break
        if rec.AcceptWaveform(data):
            parts.append(json.loads(rec.Result()).get("text", ""))
    parts.append(json.loads(rec.FinalResult()).get("text", ""))
    return " ".join(parts).strip()


def _anchor_frame(page):
    try:
        for frame in page.frames:
            if "recaptcha/api2/anchor" in (frame.url or ""):
                return frame
    except Exception:
        pass
    return None


def _challenge_frame(page):
    try:
        for frame in page.frames:
            if "recaptcha/api2/bframe" in (frame.url or "") or "recaptcha/api2/mframe" in (frame.url or ""):
                return frame
    except Exception:
        pass
    return None


def _anchor_checked(anchor) -> bool:
    try:
        state = anchor.locator("#recaptcha-anchor").get_attribute("aria-checked")
        return state == "true"
    except Exception:
        return False


def solve_recaptcha_if_present(page, language: str = "en", max_audio_attempts: int = 3) -> bool:
    """Click reCAPTCHA checkbox if present; auto-solve audio challenge.

    Returns True when there is no captcha OR it is solved. False = still
    unsolved after retries.
    """
    anchor = _anchor_frame(page)
    if anchor is None:
        return True  # no reCAPTCHA on this page
    log.info("reCAPTCHA detected — attempting zero-touch solve.")
    try:
        anchor.locator("#recaptcha-anchor").click(timeout=8000)
    except Exception as exc:
        log.debug("Could not click reCAPTCHA anchor: %s", exc)
        return False

    for _ in range(30):  # ~15s for a no-challenge pass
        time.sleep(0.5)
        if _anchor_checked(anchor):
            log.info("reCAPTCHA passed with checkbox click alone.")
            return True
        if _challenge_frame(page) is not None:
            break
    else:
        return _anchor_checked(anchor)

    return solve_recaptcha_audio(page, language=language, max_attempts=max_audio_attempts)


def solve_recaptcha_audio(page, language: str = "en", max_attempts: int = 3) -> bool:
    """Solve the reCAPTCHA audio challenge automatically (Buster-style)."""
    import requests

    for attempt in range(1, max_attempts + 1):
        try:
            challenge = _challenge_frame(page)
            if challenge is None:
                # Challenge may have closed = solved
                anchor = _anchor_frame(page)
                if anchor and _anchor_checked(anchor):
                    return True
                log.debug("Challenge frame vanished without success.")
                return False

            # Switch to audio challenge
            audio_btn = challenge.locator("#recaptcha-audio-button")
            if audio_btn.count():
                try:
                    audio_btn.click(timeout=5000)
                    time.sleep(1.5)
                except Exception:
                    pass  # maybe already on audio tab

            src = challenge.locator("#audio-source").get_attribute("src", timeout=10000)
            if not src:
                raise RuntimeError("Audio source not found.")
            log.info("Downloading reCAPTCHA audio (attempt %d/%d)...", attempt, max_attempts)
            resp = requests.get(src, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()

            with tempfile.TemporaryDirectory(prefix="recaptcha_") as tmp:
                mp3 = Path(tmp) / "audio.mp3"
                mp3.write_bytes(resp.content)
                wav = ensure_wav(mp3)
                answer = transcribe_audio(wav, language=language)
            if not answer:
                raise RuntimeError("Empty transcription.")

            log.info("Audio transcribed, submitting answer.")
            box = challenge.locator("#audio-response")
            box.fill("", timeout=5000)
            page.wait_for_timeout(300)
            box.press_sequentially(answer, delay=40)
            page.wait_for_timeout(400)
            challenge.locator("#recaptcha-verify-button").click(timeout=5000)

            # Verdict: wait for either error text or anchor-checked
            time.sleep(2.5)
            anchor = _anchor_frame(page)
            if anchor and _anchor_checked(anchor):
                log.info("reCAPTCHA audio challenge SOLVED.")
                return True
            # "Get a new challenge" and retry
            try:
                reload_btn = (_challenge_frame(page) or challenge).locator(
                    "#recaptcha-reload-button"
                )
                if reload_btn.count():
                    reload_btn.click(timeout=4000)
                    time.sleep(1.5)
            except Exception:
                pass
            log.info("Audio answer rejected, retrying with fresh challenge...")
        except Exception as exc:
            log.warning("Audio attempt %d failed: %s", attempt, exc)
            time.sleep(1.5)
    log.error("reCAPTCHA audio solve failed after %d attempts.", max_attempts)
    return False
