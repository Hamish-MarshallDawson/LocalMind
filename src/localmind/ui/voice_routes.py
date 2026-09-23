"""HTTP endpoints the page's voice mode talks to: audio in, text out; text in, audio out.

Plain routes rather than Gradio events, because audio is binary and a reply is spoken a sentence
at a time. They're added to Gradio's own FastAPI app (through `launch(app_kwargs=...)`), so they
sit behind the same login as the rest of LocalMind.
"""
from __future__ import annotations

import inspect
import logging

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from localmind.voice import VoiceEngine, VoiceUnavailable

logger = logging.getLogger(__name__)

PREFIX = "/localmind/voice"
# Cross-site pages can't add custom headers without a CORS preflight, which these routes never
# answer, so requiring one stops another website from driving them with your login cookie.
HEADER = "x-localmind-voice"


async def signed_in(request: Request) -> bool:
    """The same check Gradio makes for its own routes: no login configured, or a valid session."""
    app = request.app
    if not hasattr(app, "auth"):
        return False  # not the Gradio app we expect, so we can't tell: refuse
    dependency = getattr(app, "auth_dependency", None)
    if app.auth is None and dependency is None:
        return True
    if dependency is not None:
        user = dependency(request)
        if inspect.isawaitable(user):
            user = await user
        return user is not None
    cookie_id = getattr(app, "cookie_id", "")
    token = request.cookies.get(f"access-token-{cookie_id}") or request.cookies.get(f"access-token-unsecure-{cookie_id}")
    return token is not None and token in getattr(app, "tokens", {})


async def _guard(request: Request) -> JSONResponse | None:
    if request.headers.get(HEADER) != "1":
        return JSONResponse({"error": "missing voice header"}, status_code=400)
    if not await signed_in(request):
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    return None


def voice_routes(engine: VoiceEngine) -> list[APIRoute]:
    limit = engine.config.max_upload_mb * 1024 * 1024

    async def transcribe(request: Request):
        if refused := await _guard(request):
            return refused
        audio = await request.body()
        if len(audio) > limit:
            return JSONResponse({"error": "Recording too long"}, status_code=413)
        try:
            result = await run_in_threadpool(engine.transcribe, audio)
        except Exception as e:  # noqa: BLE001
            logger.exception("Transcription failed")
            return JSONResponse({"error": f"Couldn't transcribe that: {e}"}, status_code=500)
        logger.info("Heard %.1fs of speech in %.2fs: %r", result.audio_seconds, result.elapsed, result.text[:80])
        return {"text": result.text, "language": result.language, "seconds": round(result.audio_seconds, 2)}

    async def speak(request: Request):
        if refused := await _guard(request):
            return refused
        try:
            text = str((await request.json()).get("text", ""))
        except ValueError:
            return JSONResponse({"error": "Expected JSON with a text field"}, status_code=400)
        try:
            audio = await run_in_threadpool(engine.speak, text)
        except VoiceUnavailable as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        except Exception as e:  # noqa: BLE001
            logger.exception("Speech synthesis failed")
            return JSONResponse({"error": f"Couldn't speak that: {e}"}, status_code=500)
        if audio is None:
            return Response(status_code=204)
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    async def warm(request: Request):
        if refused := await _guard(request):
            return refused
        if not engine.tts_installed():
            return JSONResponse({"error": "Speech output needs the kokoro-onnx package:  pip install kokoro-onnx"}, status_code=503)
        engine.warm()
        return {"ready": engine.ready}

    return [
        APIRoute(f"{PREFIX}/transcribe", transcribe, methods=["POST"]),
        APIRoute(f"{PREFIX}/speak", speak, methods=["POST"]),
        APIRoute(f"{PREFIX}/warm", warm, methods=["POST"]),
    ]
