"""FastAPI test server for Qwen3-TTS streaming speech synthesis.

Serves a simple web UI (index.html) and proxies TTS requests to the
vllm-omni backend, supporting both HTTP streaming and WebSocket modes.

Usage:
    # Start vllm-omni server first:
    #   ./run_server.sh CustomVoice
    #
    # Then run this test server:
    python fastapi_tts_test.py --api-base http://localhost:8091

    # Open http://localhost:8080 in your browser
"""

import argparse
import asyncio
import json
import logging
import struct
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="Qwen3-TTS")

# Configured at startup
API_BASE = "http://localhost:8091"
MODEL_NAME = None  # Auto-detected from backend


async def _get_model_name() -> str:
    """Get the model name from backend /v1/models (cached after first success)."""
    global MODEL_NAME
    if MODEL_NAME is not None:
        return MODEL_NAME
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{API_BASE}/v1/models")
            data = resp.json()
            MODEL_NAME = data["data"][0]["id"]
            logger.info("Auto-detected model name: %s", MODEL_NAME)
        except Exception:
            # Do NOT cache on failure - retry on next request
            logger.warning("Backend not ready, model name detection deferred")
            return None
    return MODEL_NAME


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/health")
async def health():
    """Health check - verifies backend is reachable."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{API_BASE}/health")
            return {"status": "ok", "backend": resp.status_code == 200}
        except Exception:
            return {"status": "degraded", "backend": False}


@app.get("/api/voices")
async def get_voices():
    """Proxy voice list from vllm-omni server."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{API_BASE}/v1/audio/voices",
                headers={"Authorization": "Bearer EMPTY"},
            )
            return resp.json()
        except Exception:
            return {"voices": [], "loading": True}


@app.post("/api/tts/stream")
async def tts_stream_http(payload: dict):
    """HTTP streaming TTS - proxies to vllm-omni /v1/audio/speech with stream=true.

    Returns chunked PCM audio (int16, 24kHz, mono).
    After all PCM data, appends a JSON metadata trailer prefixed with a 4-byte
    magic marker (0x00 0x00 0x00 0x00) so the client can detect it.
    The trailer contains server-side RTF metrics.
    """
    model = await _get_model_name()
    if model is None:
        return JSONResponse(status_code=503, content={"error": "Backend is still loading, please retry in a moment."})
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
                f"{API_BASE}/v1/audio/speech",
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
        # 24kHz mono int16 = 48000 bytes/sec
        audio_duration = total_pcm_bytes / (24000 * 2)
        rtf = elapsed / audio_duration if audio_duration > 0 else 0

        logger.info(
            "Stream TTS: %.2fs audio, %.2fs processing (TTFB %.3fs), RTF=%.4f",
            audio_duration, elapsed, ttfb, rtf,
        )

        # Append JSON metadata trailer after PCM data.
        # 4 zero-bytes act as a magic marker the client uses to split
        # the trailer from PCM data (valid int16 PCM can contain 0x0000,
        # but 4 consecutive zero-bytes at the very end is our sentinel).
        import json as _json
        trailer = _json.dumps({
            "_tts_meta": True,
            "audio_duration": round(audio_duration, 3),
            "processing_time": round(elapsed, 3),
            "ttfb": round(ttfb, 3),
            "rtf": round(rtf, 4),
        }).encode("utf-8")
        yield b"\x00\x00\x00\x00" + trailer

    return StreamingResponse(generate(), media_type="audio/pcm")


@app.websocket("/api/tts/ws")
async def tts_stream_ws(ws: WebSocket):
    """WebSocket streaming TTS - proxies to vllm-omni /v1/audio/speech/stream.

    Protocol:
      Client sends JSON: { text, voice, task_type, language, instructions, ... }
      Server sends back: binary PCM chunks + JSON control messages
    """
    await ws.accept()

    try:
        # Receive config from client
        raw = await ws.receive_text()
        config = json.loads(raw)
        text = config.pop("text", "")
        voice = config.pop("voice", "Vivian")
        task_type = config.pop("task_type", "CustomVoice")
        language = config.pop("language", "Auto")
        instructions = config.pop("instructions", "")
        response_format = config.pop("response_format", "pcm")

        import websockets

        backend_url = API_BASE.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        backend_url += "/v1/audio/speech/stream"

        async with websockets.connect(backend_url) as backend_ws:
            # Send session config
            session_config = {
                "type": "session.config",
                "voice": voice,
                "task_type": task_type,
                "language": language,
                "response_format": response_format,
            }
            if instructions:
                session_config["instructions"] = instructions
            # Pass through any extra config keys (ref_audio, ref_text, etc.)
            for k, v in config.items():
                if v:
                    session_config[k] = v

            await backend_ws.send(json.dumps(session_config))

            # Send text
            await backend_ws.send(
                json.dumps({"type": "input.text", "text": text})
            )
            await backend_ws.send(json.dumps({"type": "input.done"}))

            # Relay messages from backend to client
            while True:
                message = await backend_ws.recv()
                if isinstance(message, bytes):
                    await ws.send_bytes(message)
                else:
                    await ws.send_text(message)
                    msg = json.loads(message)
                    if msg.get("type") == "session.done":
                        break

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.exception("WebSocket TTS error")
        try:
            await ws.send_text(
                json.dumps({"type": "error", "message": str(e)})
            )
        except Exception:
            pass


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
    """Non-streaming TTS - returns complete WAV file with RTF in headers."""
    model = await _get_model_name()
    if model is None:
        return JSONResponse(status_code=503, content={"error": "Backend is still loading, please retry in a moment."})
    payload["stream"] = False
    payload["model"] = model
    payload.setdefault("response_format", "wav")

    start = time.monotonic()

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{API_BASE}/v1/audio/speech",
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

    # Calculate RTF for WAV/PCM responses
    response_headers = {
        "Content-Disposition": f"attachment; filename=tts_output.{fmt}",
        "X-Processing-Time": f"{elapsed:.3f}",
    }

    audio_duration = None
    if fmt == "wav":
        audio_duration = _wav_audio_duration(resp.content)
    elif fmt == "pcm":
        # Assume 24kHz mono int16
        audio_duration = len(resp.content) / (24000 * 2)

    if audio_duration and audio_duration > 0:
        rtf = elapsed / audio_duration
        response_headers["X-Audio-Duration"] = f"{audio_duration:.3f}"
        response_headers["X-RTF"] = f"{rtf:.4f}"
        logger.info(
            "Full TTS: %.2fs audio, %.2fs processing, RTF=%.4f",
            audio_duration, elapsed, rtf,
        )

    return StreamingResponse(
        iter([resp.content]),
        media_type=content_type,
        headers=response_headers,
    )


def main():
    parser = argparse.ArgumentParser(description="FastAPI test server for Qwen3-TTS")
    parser.add_argument(
        "--api-base",
        default="http://localhost:8091",
        help="vllm-omni backend URL (default: http://localhost:8091)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Listen host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7860, help="Listen port (default: 7860)")
    args = parser.parse_args()

    global API_BASE
    API_BASE = args.api_base.rstrip("/")

    logging.basicConfig(level=logging.INFO)
    logger.info("Backend: %s", API_BASE)
    logger.info("Open http://localhost:%d in your browser", args.port)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
