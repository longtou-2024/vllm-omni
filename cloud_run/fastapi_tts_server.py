"""FastAPI server for Qwen3-TTS streaming speech synthesis (multi-model).

Serves a web UI (index.html) and proxies TTS requests to one or more
vllm-omni backends, supporting HTTP streaming, WebSocket, and full modes.

Each backend serves a single model (CustomVoice / VoiceDesign / Base).
The server routes requests to the correct backend based on task_type.

Usage:
    # Single backend (all task types go to one server):
    python fastapi_tts_server.py --api-base http://localhost:8091

    # Multi-backend (one backend per model):
    python fastapi_tts_server.py \
        --backend CustomVoice=http://localhost:8091 \
        --backend VoiceDesign=http://localhost:8092 \
        --backend Base=http://localhost:8093

    # Via environment variables:
    BACKEND_CUSTOMVOICE=http://localhost:8091 \
    BACKEND_VOICEDESIGN=http://localhost:8092 \
    BACKEND_BASE=http://localhost:8093 \
    python fastapi_tts_server.py

    # Open http://localhost:7860 in your browser
"""

import argparse
import asyncio
import json
import logging
import os
import struct
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

# Backend config: task_type -> base URL
# Populated at startup from CLI args or env vars.
BACKENDS: dict[str, str] = {}

# Model name cache per backend URL
_model_cache: dict[str, str] = {}

# Warmup config
WARMUP_TEXT = "Hello. This is a warmup request."
WARMUP_POLL_INTERVAL = 5  # seconds between retries while backend loads
WARMUP_TIMEOUT = 600  # give up after 10 minutes


# ── Warmup ──────────────────────────────────────────────────────────

async def _warmup_backend(task_type: str, backend_url: str):
    """Wait for a backend to become ready, then send a warmup TTS request."""
    start = time.monotonic()
    model = None

    # Phase 1: poll until backend is up and model name is available
    while time.monotonic() - start < WARMUP_TIMEOUT:
        model = await _get_model_name(backend_url)
        if model:
            break
        logger.info("Warmup [%s]: waiting for backend %s ...", task_type, backend_url)
        await asyncio.sleep(WARMUP_POLL_INTERVAL)

    if not model:
        logger.warning("Warmup [%s]: backend not ready after %ds, skipping", task_type, WARMUP_TIMEOUT)
        return

    # Phase 2: send a short TTS request to warm up the pipeline
    payload = {
        "model": model,
        "input": WARMUP_TEXT,
        "task_type": task_type,
        "response_format": "pcm",
        "stream": False,
    }
    if task_type == "CustomVoice":
        payload["voice"] = "Vivian"
    elif task_type == "VoiceDesign":
        payload["instructions"] = "A calm female voice"

    logger.info("Warmup [%s]: sending test request ...", task_type)
    warmup_start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{backend_url}/v1/audio/speech",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer EMPTY",
                },
            )
        elapsed = time.monotonic() - warmup_start
        if resp.status_code == 200:
            pcm_bytes = len(resp.content)
            audio_dur = pcm_bytes / (24000 * 2)
            logger.info(
                "Warmup [%s]: done in %.1fs (%.1fs audio, %d bytes)",
                task_type, elapsed, audio_dur, pcm_bytes,
            )
        else:
            logger.warning("Warmup [%s]: backend returned %d (%s)", task_type, resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Warmup [%s]: failed — %s", task_type, e)


async def _warmup_all():
    """Warm up all unique backends concurrently."""
    # Deduplicate: multiple task_types may point to the same URL
    seen: dict[str, str] = {}
    for task_type, url in BACKENDS.items():
        if task_type == "default" or url in seen.values():
            continue
        seen[task_type] = url

    if not seen:
        return

    logger.info("Starting warmup for %d backend(s) ...", len(seen))
    tasks = [_warmup_backend(tt, url) for tt, url in seen.items()]
    await asyncio.gather(*tasks)
    logger.info("Warmup complete")


# ── App lifespan ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: launch warmup in background so the server accepts requests immediately
    warmup_task = asyncio.create_task(_warmup_all())
    yield
    # Shutdown: cancel warmup if still running
    warmup_task.cancel()
    try:
        await warmup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Qwen3-TTS", lifespan=lifespan)


def _get_backend(task_type: str) -> str | None:
    """Resolve backend URL for the given task_type."""
    if task_type in BACKENDS:
        return BACKENDS[task_type]
    # Fallback: use "default" if configured (single-backend mode)
    return BACKENDS.get("default")


async def _get_model_name(backend_url: str) -> str | None:
    """Get the model name from a backend's /v1/models (cached)."""
    if backend_url in _model_cache:
        return _model_cache[backend_url]
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{backend_url}/v1/models")
            data = resp.json()
            name = data["data"][0]["id"]
            _model_cache[backend_url] = name
            logger.info("Detected model for %s: %s", backend_url, name)
            return name
        except Exception:
            logger.warning("Backend %s not ready", backend_url)
            return None


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/health")
async def health():
    """Health check — reports status of each configured backend."""
    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for task_type, url in BACKENDS.items():
            try:
                resp = await client.get(f"{url}/health")
                results[task_type] = {"url": url, "ok": resp.status_code == 200}
            except Exception:
                results[task_type] = {"url": url, "ok": False}
    all_ok = any(r["ok"] for r in results.values()) if results else False
    return {"status": "ok" if all_ok else "degraded", "backends": results}


@app.get("/api/backends")
async def get_backends():
    """Return configured backends with their status and model names."""
    info = {}
    for task_type, url in BACKENDS.items():
        if task_type == "default":
            continue
        model = await _get_model_name(url)
        info[task_type] = {"url": url, "model": model, "ready": model is not None}
    return info


@app.get("/api/voices")
async def get_voices():
    """Proxy voice list from CustomVoice backend."""
    backend = _get_backend("CustomVoice")
    if not backend:
        return {"voices": [], "error": "No CustomVoice backend configured"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{backend}/v1/audio/voices",
                headers={"Authorization": "Bearer EMPTY"},
            )
            return resp.json()
        except Exception:
            return {"voices": [], "loading": True}


@app.post("/api/tts/stream")
async def tts_stream_http(payload: dict):
    """HTTP streaming TTS — routes to the correct backend by task_type.

    Returns chunked PCM audio (int16, 24kHz, mono) with a JSON
    metadata trailer at the end.
    """
    task_type = payload.get("task_type", "CustomVoice")
    backend = _get_backend(task_type)
    if not backend:
        return JSONResponse(status_code=400, content={"error": f"No backend for task_type={task_type}"})

    model = await _get_model_name(backend)
    if model is None:
        return JSONResponse(status_code=503, content={"error": f"Backend for {task_type} is still loading."})

    payload.setdefault("response_format", "pcm")
    payload["model"] = model
    payload["stream"] = True

    async def generate():
        start = time.monotonic()
        total_pcm_bytes = 0
        first_chunk_time = None

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{backend}/v1/audio/speech",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer EMPTY",
                },
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    logger.error("Backend error %d: %s", resp.status_code, resp.text)
                    return
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        if first_chunk_time is None:
                            first_chunk_time = time.monotonic()
                        total_pcm_bytes += len(chunk)
                        yield chunk

        elapsed = time.monotonic() - start
        ttfb = (first_chunk_time - start) if first_chunk_time else elapsed
        audio_duration = total_pcm_bytes / (24000 * 2)
        rtf = elapsed / audio_duration if audio_duration > 0 else 0

        logger.info(
            "Stream TTS [%s]: %.2fs audio, %.2fs processing (TTFB %.3fs), RTF=%.4f",
            task_type, audio_duration, elapsed, ttfb, rtf,
        )

        trailer = json.dumps({
            "_tts_meta": True,
            "audio_duration": round(audio_duration, 3),
            "processing_time": round(elapsed, 3),
            "ttfb": round(ttfb, 3),
            "rtf": round(rtf, 4),
        }).encode("utf-8")
        yield b"\x00\x00\x00\x00" + trailer

    return StreamingResponse(generate(), media_type="audio/pcm")


def _wav_audio_duration(data: bytes) -> float | None:
    """Extract audio duration in seconds from WAV binary data."""
    if len(data) < 44 or data[:4] != b"RIFF":
        return None
    try:
        num_channels = struct.unpack_from("<H", data, 22)[0]
        sample_rate = struct.unpack_from("<I", data, 24)[0]
        bits_per_sample = struct.unpack_from("<H", data, 34)[0]
        data_size = struct.unpack_from("<I", data, 40)[0]
        if sample_rate == 0 or num_channels == 0 or bits_per_sample == 0:
            return None
        bytes_per_sample = bits_per_sample // 8
        return data_size / (sample_rate * num_channels * bytes_per_sample)
    except struct.error:
        return None


@app.post("/api/tts/full")
async def tts_full(payload: dict):
    """Non-streaming TTS — routes to the correct backend by task_type."""
    task_type = payload.get("task_type", "CustomVoice")
    backend = _get_backend(task_type)
    if not backend:
        return JSONResponse(status_code=400, content={"error": f"No backend for task_type={task_type}"})

    model = await _get_model_name(backend)
    if model is None:
        return JSONResponse(status_code=503, content={"error": f"Backend for {task_type} is still loading."})

    payload["stream"] = False
    payload["model"] = model
    payload.setdefault("response_format", "wav")

    start = time.monotonic()

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{backend}/v1/audio/speech",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer EMPTY",
            },
        )

    elapsed = time.monotonic() - start

    content_type = "audio/wav"
    fmt = payload.get("response_format", "wav")
    if fmt == "mp3":
        content_type = "audio/mpeg"
    elif fmt == "flac":
        content_type = "audio/flac"
    elif fmt == "pcm":
        content_type = "audio/pcm"

    response_headers = {
        "Content-Disposition": f"attachment; filename=tts_output.{fmt}",
        "X-Processing-Time": f"{elapsed:.3f}",
    }

    audio_duration = None
    if fmt == "wav":
        audio_duration = _wav_audio_duration(resp.content)
    elif fmt == "pcm":
        audio_duration = len(resp.content) / (24000 * 2)

    if audio_duration and audio_duration > 0:
        rtf = elapsed / audio_duration
        response_headers["X-Audio-Duration"] = f"{audio_duration:.3f}"
        response_headers["X-RTF"] = f"{rtf:.4f}"
        logger.info(
            "Full TTS [%s]: %.2fs audio, %.2fs processing, RTF=%.4f",
            task_type, audio_duration, elapsed, rtf,
        )

    return StreamingResponse(
        iter([resp.content]),
        media_type=content_type,
        headers=response_headers,
    )


def main():
    parser = argparse.ArgumentParser(description="FastAPI server for Qwen3-TTS (multi-model)")
    parser.add_argument(
        "--api-base",
        default=None,
        help="Single backend URL for all task types (default mode)",
    )
    parser.add_argument(
        "--backend",
        action="append",
        metavar="TASK_TYPE=URL",
        help="Backend per task type, e.g. --backend CustomVoice=http://localhost:8091",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()

    global BACKENDS

    # Priority 1: --backend flags
    if args.backend:
        for entry in args.backend:
            if "=" not in entry:
                parser.error(f"Invalid --backend format: {entry} (expected TASK_TYPE=URL)")
            task_type, url = entry.split("=", 1)
            BACKENDS[task_type] = url.rstrip("/")

    # Priority 2: environment variables
    env_map = {
        "BACKEND_CUSTOMVOICE": "CustomVoice",
        "BACKEND_VOICEDESIGN": "VoiceDesign",
        "BACKEND_BASE": "Base",
    }
    for env_key, task_type in env_map.items():
        url = os.environ.get(env_key)
        if url and task_type not in BACKENDS:
            BACKENDS[task_type] = url.rstrip("/")

    # Priority 3: --api-base (single backend for all)
    if args.api_base:
        fallback = args.api_base.rstrip("/")
        BACKENDS.setdefault("default", fallback)
        for tt in ["CustomVoice", "VoiceDesign", "Base"]:
            BACKENDS.setdefault(tt, fallback)

    # Priority 4: default fallback
    if not BACKENDS:
        default_url = "http://localhost:8091"
        BACKENDS["default"] = default_url
        for tt in ["CustomVoice", "VoiceDesign", "Base"]:
            BACKENDS[tt] = default_url

    logging.basicConfig(level=logging.INFO)
    logger.info("Configured backends:")
    for tt, url in sorted(BACKENDS.items()):
        logger.info("  %s -> %s", tt, url)
    logger.info("Open http://localhost:%d in your browser", args.port)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
