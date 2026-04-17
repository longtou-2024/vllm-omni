# qwen3-tts model download
## HuggingFace Hub CLI로 다운로드 (캐시 디렉토리: ~/.cache/huggingface/)
  huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice --local-dir ./Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
  huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --local-dir ./Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
  huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-Base --local-dir ./Qwen/Qwen3-TTS-12Hz-1.7B-Base

# usage fastapi_tts_server.py 

```bash
# Step 1: 각 모델별로 vllm-omni 백엔드 실행 (각각 다른 터미널/GPU)
vllm-omni serve Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
    --stage-configs-path cloud_run/stage_config.yaml \
    --host 0.0.0.0 --port 8091 \
    --gpu-memory-utilization 0.9 --trust-remote-code --enforce-eager --omni

vllm-omni serve Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign \
    --stage-configs-path cloud_run/stage_config.yaml \
    --host 0.0.0.0 --port 8092 \
    --gpu-memory-utilization 0.9 --trust-remote-code --enforce-eager --omni

vllm-omni serve Qwen/Qwen3-TTS-12Hz-1.7B-Base \
    --stage-configs-path cloud_run/stage_config.yaml \
    --host 0.0.0.0 --port 8093 \
    --gpu-memory-utilization 0.9 --trust-remote-code --enforce-eager --omni

# Step 2: FastAPI 프론트엔드 실행
python3 cloud_run/fastapi_tts_server.py \
    --backend CustomVoice=http://localhost:8091 \
    --backend VoiceDesign=http://localhost:8092 \
    --backend Base=http://localhost:8093

# 또는 환경변수로:
BACKEND_CUSTOMVOICE=http://localhost:8091 \
BACKEND_VOICEDESIGN=http://localhost:8092 \
BACKEND_BASE=http://localhost:8093 \
python3 cloud_run/fastapi_tts_server.py

# 또는 단일 백엔드 모드 (모델 하나만 실행 시):
python3 cloud_run/fastapi_tts_server.py --api-base http://localhost:8091

# Step 3: 브라우저에서 http://localhost:7860 접속
```

| 옵션                  | 기본값                  | 설명                             |
|-----------------------|-------------------------|----------------------------------|
| `--api-base`          | `http://localhost:8091` | 단일 백엔드 URL (모든 task_type) |
| `--backend`           | —                       | task_type별 백엔드 (반복 가능)   |
| `--host`              | `0.0.0.0`               | 리슨 호스트                      |
| `--port`              | `7860`                  | 리슨 포트                        |
| `BACKEND_CUSTOMVOICE` | —                       | 환경변수로 백엔드 설정           |
| `BACKEND_VOICEDESIGN` | —                       | 환경변수로 백엔드 설정           |
| `BACKEND_BASE`        | —                       | 환경변수로 백엔드 설정           |

# Task Type별 기능 정리

## Feature Matrix

| 파라미터                     | CustomVoice                | VoiceDesign          | Base (Voice Clone)   |
|------------------------------|----------------------------|----------------------|----------------------|
| `voice` (스피커 선택)        | **지원** (Vivian, Ryan 등) | 사용 안함            | 업로드된 음성 참조용 |
| `instructions` (스타일/감정) | 선택                       | **필수** (음성 설명) | 사용 안함            |
| `ref_audio` (참조 음성)      | 사용 안함                  | 사용 안함            | **필수**             |
| `ref_text` (참조 텍스트)     | 사용 안함                  | 사용 안함            | ICL 모드 시 필수     |
| `language`                   | 지원                       | 지원                 | 지원                 |
| `response_format`            | 지원                       | 지원                 | 지원                 |
| `stream`                     | 지원                       | 지원                 | 지원                 |

## 각 타입 요약

- **CustomVoice**: 내장 스피커 선택 + 선택적 감정/스타일 지시. 가장 간단
- **VoiceDesign**: 자연어로 원하는 음성을 묘사 ("차분한 남성 목소리, 약간의 영국 억양"). `instructions` 필수
- **Base**: 참조 음성(ref_audio)으로 음성 복제. `ref_text` 제공 시 ICL(In-Context Learning)로 품질 향상

