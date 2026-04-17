"""Batch streaming benchmark for Qwen3-TTS on L4 GPU.

Sends N concurrent streaming TTS requests and measures per-request metrics:
  - TTFB (Time To First Byte): latency until first audio chunk
  - RTF (Real-Time Factor): processing_time / audio_duration (< 1.0 = real-time)
  - Audio duration, total processing time

Usage:
    # Single request baseline
    python batch_streaming_bench.py --concurrency 1

    # Batch of 4 concurrent requests
    python batch_streaming_bench.py --concurrency 4

    # Custom text and multiple rounds
    python batch_streaming_bench.py --concurrency 4 --rounds 3 --text "안녕하세요"

    # Sweep concurrency levels 1,2,4,8
    python batch_streaming_bench.py --sweep
"""

import argparse
import asyncio
import statistics
import time

import httpx

# Test sentences of varying lengths for realistic workload
DEFAULT_TEXTS = [
    "The quick brown fox jumps over the lazy dog.",
    "Hello, welcome to our text to speech streaming benchmark test.",
    "Today is a beautiful day, the sun is shining and the birds are singing.",
    "Artificial intelligence is transforming the way we interact with technology.",
    "In a quiet village nestled between rolling hills, an old clockmaker spent his days crafting timepieces of extraordinary beauty.",
    "The advancement of neural network architectures has enabled significant breakthroughs in natural language processing and speech synthesis.",
    "When the autumn leaves begin to fall, painting the landscape in shades of gold and crimson, there is a peaceful stillness that settles over the countryside.",
    "Modern cloud computing platforms provide scalable infrastructure that enables businesses of all sizes to deploy sophisticated machine learning models.",
]

SAMPLE_RATE = 24000
BYTES_PER_SAMPLE = 2  # int16
BYTES_PER_SEC = SAMPLE_RATE * BYTES_PER_SAMPLE


async def stream_tts_request(
    client: httpx.AsyncClient,
    api_base: str,
    text: str,
    voice: str,
    request_id: int,
    model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
) -> dict:
    """Send a single streaming TTS request and collect metrics."""
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "pcm",
        "stream": True,
    }

    start = time.monotonic()
    first_chunk_time = None
    total_pcm_bytes = 0
    chunk_count = 0
    chunk_times = []

    try:
        async with client.stream(
            "POST",
            f"{api_base}/v1/audio/speech",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer EMPTY",
            },
        ) as resp:
            if resp.status_code != 200:
                await resp.aread()
                return {
                    "request_id": request_id,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                }

            async for chunk in resp.aiter_bytes():
                if chunk:
                    now = time.monotonic()
                    if first_chunk_time is None:
                        first_chunk_time = now
                    total_pcm_bytes += len(chunk)
                    chunk_count += 1
                    chunk_times.append(now - start)

    except Exception as e:
        return {"request_id": request_id, "error": str(e)}

    elapsed = time.monotonic() - start
    ttfb = (first_chunk_time - start) if first_chunk_time else elapsed
    audio_duration = total_pcm_bytes / BYTES_PER_SEC
    rtf = elapsed / audio_duration if audio_duration > 0 else float("inf")

    # Compute inter-chunk intervals for jitter analysis
    intervals = []
    for i in range(1, len(chunk_times)):
        intervals.append(chunk_times[i] - chunk_times[i - 1])

    return {
        "request_id": request_id,
        "text_len": len(text),
        "audio_duration": round(audio_duration, 3),
        "processing_time": round(elapsed, 3),
        "ttfb": round(ttfb, 3),
        "rtf": round(rtf, 4),
        "chunks": chunk_count,
        "pcm_bytes": total_pcm_bytes,
        "realtime": rtf < 1.0,
        "avg_chunk_interval": round(statistics.mean(intervals), 4) if intervals else 0,
        "max_chunk_interval": round(max(intervals), 4) if intervals else 0,
    }


async def run_batch(
    api_base: str,
    texts: list[str],
    concurrency: int,
    voice: str,
    round_num: int,
    model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
) -> list[dict]:
    """Send `concurrency` requests simultaneously and return all results."""
    # Use texts cyclically if concurrency > len(texts)
    batch_texts = [texts[i % len(texts)] for i in range(concurrency)]

    async with httpx.AsyncClient(timeout=300.0) as client:
        tasks = [
            stream_tts_request(client, api_base, text, voice, i, model=model)
            for i, text in enumerate(batch_texts)
        ]

        print(f"\n--- Round {round_num} | Concurrency={concurrency} | Sending {len(tasks)} requests ---")
        batch_start = time.monotonic()
        results = await asyncio.gather(*tasks)
        batch_elapsed = time.monotonic() - batch_start
        print(f"    Batch completed in {batch_elapsed:.2f}s")

    return results


def print_results(results: list[dict], concurrency: int):
    """Pretty-print per-request and aggregate metrics."""
    successful = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]

    if failed:
        for r in failed:
            print(f"  [FAIL] req#{r['request_id']}: {r['error']}")

    if not successful:
        print("  No successful requests!")
        return

    # Per-request table
    print(f"\n  {'Req':>3} | {'TextLen':>7} | {'AudioDur':>8} | {'ProcTime':>8} | {'TTFB':>6} | {'RTF':>6} | {'RT?':>3} | {'Chunks':>6} | {'AvgInt':>6} | {'MaxInt':>6}")
    print(f"  {'-'*3}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}-+-{'-'*6}-+-{'-'*3}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}")
    for r in successful:
        rt_mark = "OK" if r["realtime"] else "NO"
        print(
            f"  {r['request_id']:>3} | {r['text_len']:>7} | {r['audio_duration']:>7.2f}s | {r['processing_time']:>7.2f}s | {r['ttfb']:>5.3f} | {r['rtf']:>6.4f} | {rt_mark:>3} | {r['chunks']:>6} | {r['avg_chunk_interval']:>6.4f} | {r['max_chunk_interval']:>6.4f}"
        )

    # Aggregate stats
    rtfs = [r["rtf"] for r in successful]
    ttfbs = [r["ttfb"] for r in successful]
    audio_durs = [r["audio_duration"] for r in successful]
    proc_times = [r["processing_time"] for r in successful]
    all_realtime = all(r["realtime"] for r in successful)

    print(f"\n  === Aggregate (concurrency={concurrency}) ===")
    print(f"  Requests: {len(successful)} ok / {len(failed)} failed")
    print(f"  RTF:  mean={statistics.mean(rtfs):.4f}  max={max(rtfs):.4f}  min={min(rtfs):.4f}  stdev={statistics.stdev(rtfs):.4f}" if len(rtfs) > 1 else f"  RTF:  {rtfs[0]:.4f}")
    print(f"  TTFB: mean={statistics.mean(ttfbs):.3f}s  max={max(ttfbs):.3f}s  min={min(ttfbs):.3f}s")
    print(f"  Audio: total={sum(audio_durs):.2f}s  mean={statistics.mean(audio_durs):.2f}s")
    print(f"  Processing: max={max(proc_times):.2f}s (batch wall-clock)")
    print(f"  All real-time (RTF<1.0): {'YES' if all_realtime else 'NO'}")
    total_throughput = sum(audio_durs) / max(proc_times) if max(proc_times) > 0 else 0
    print(f"  Throughput: {total_throughput:.2f}x real-time (total audio / wall-clock)")


def print_sweep_summary(sweep_results: dict):
    """Print a summary table across all concurrency levels."""
    print("\n" + "=" * 80)
    print("SWEEP SUMMARY")
    print("=" * 80)
    print(f"  {'Conc':>4} | {'MeanRTF':>8} | {'MaxRTF':>8} | {'MeanTTFB':>8} | {'AllRT?':>6} | {'Throughput':>10}")
    print(f"  {'-'*4}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}-+-{'-'*10}")

    for conc, all_results in sorted(sweep_results.items()):
        # Flatten results across rounds
        successful = [r for results in all_results for r in results if "error" not in r]
        if not successful:
            print(f"  {conc:>4} | {'FAIL':>8} |")
            continue

        rtfs = [r["rtf"] for r in successful]
        ttfbs = [r["ttfb"] for r in successful]
        audio_durs = [r["audio_duration"] for r in successful]
        proc_times = [r["processing_time"] for r in successful]
        all_rt = all(r["realtime"] for r in successful)
        throughput = sum(audio_durs) / max(proc_times) if max(proc_times) > 0 else 0

        print(
            f"  {conc:>4} | {statistics.mean(rtfs):>8.4f} | {max(rtfs):>8.4f} | {statistics.mean(ttfbs):>7.3f}s | {'YES' if all_rt else 'NO':>6} | {throughput:>9.2f}x"
        )

    print("=" * 80)


async def main():
    parser = argparse.ArgumentParser(description="Qwen3-TTS batch streaming benchmark")
    parser.add_argument("--api-base", default="http://localhost:8091", help="vllm-omni server URL")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of concurrent requests")
    parser.add_argument("--rounds", type=int, default=1, help="Number of rounds to repeat")
    parser.add_argument("--voice", default="Vivian", help="Voice name (default: Vivian)")
    parser.add_argument("--text", default=None, help="Custom text (overrides built-in texts)")
    parser.add_argument("--sweep", action="store_true", help="Sweep concurrency levels: 1,2,4,8")
    parser.add_argument("--sweep-levels", default="1,2,4,8", help="Comma-separated concurrency levels for sweep")
    parser.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", help="Model name")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup requests before benchmark (default: 1)")
    args = parser.parse_args()

    texts = [args.text] if args.text else DEFAULT_TEXTS

    # Warmup
    if args.warmup > 0:
        print(f"Warming up with {args.warmup} request(s)...")
        async with httpx.AsyncClient(timeout=300.0) as client:
            for i in range(args.warmup):
                result = await stream_tts_request(
                    client, args.api_base, "Hello, this is a warmup request.", args.voice, i,
                    model=args.model,
                )
                if "error" in result:
                    print(f"  Warmup failed: {result['error']}")
                    print("  Is the server running? Check: curl " + args.api_base + "/health")
                    return
                else:
                    print(f"  Warmup #{i}: RTF={result['rtf']:.4f}, TTFB={result['ttfb']:.3f}s")

    if args.sweep:
        levels = [int(x) for x in args.sweep_levels.split(",")]
        sweep_results = {}
        for conc in levels:
            round_results = []
            for r in range(1, args.rounds + 1):
                results = await run_batch(args.api_base, texts, conc, args.voice, r, model=args.model)
                print_results(results, conc)
                round_results.append(results)
            sweep_results[conc] = round_results

        print_sweep_summary(sweep_results)
    else:
        for r in range(1, args.rounds + 1):
            results = await run_batch(args.api_base, texts, args.concurrency, args.voice, r, model=args.model)
            print_results(results, args.concurrency)


if __name__ == "__main__":
    asyncio.run(main())
