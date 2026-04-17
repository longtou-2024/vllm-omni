#!/usr/bin/env bash
# Qwen3-TTS 서버 실행 보조 스크립트
#
# Usage:
#   ./cloud_run/run.sh customvoice     # CustomVoice 백엔드 (port 8091)
#   ./cloud_run/run.sh voicedesign     # VoiceDesign 백엔드 (port 8092)
#   ./cloud_run/run.sh base            # Base 백엔드 (port 8093)
#   ./cloud_run/run.sh app             # FastAPI 프론트엔드 (port 7860)
#
# 환경변수:
#   GPU_MEM_UTIL=0.9    GPU 메모리 사용률 (기본: 0.9)
#   MODEL_SIZE=1.7B     모델 크기: 1.7B 또는 0.6B (기본: 1.7B)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STAGE_CONFIG="$SCRIPT_DIR/stage_config.yaml"

GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.9}"
MODEL_SIZE="${MODEL_SIZE:-1.7B}"

serve_model() {
    local task_type="$1"
    local port="$2"
    local model="Qwen/Qwen3-TTS-12Hz-${MODEL_SIZE}-${task_type}"

    echo "============================================"
    echo " Qwen3-TTS: ${task_type}"
    echo " Model:  ${model}"
    echo " Port:   ${port}"
    echo " Config: ${STAGE_CONFIG}"
    echo "============================================"

    cd "$REPO_ROOT"
    exec vllm-omni serve "$model" \
        --stage-configs-path "$STAGE_CONFIG" \
        --host 0.0.0.0 \
        --port "$port" \
        --gpu-memory-utilization "$GPU_MEM_UTIL" \
        --trust-remote-code \
        --enforce-eager \
        --omni
}

case "${1:-help}" in
    customvoice|cv)
        serve_model "CustomVoice" "${2:-8091}"
        ;;
    voicedesign|vd)
        serve_model "VoiceDesign" "${2:-8092}"
        ;;
    base)
        serve_model "Base" "${2:-8093}"
        ;;
    app)
        # 기본 포트 매핑
        declare -A PORTS=(
            [CustomVoice]=8091
            [VoiceDesign]=8092
            [Base]=8093
        )

        # 살아있는 백엔드 자동 감지
        BACKEND_ARGS=()
        echo "Scanning backends..."
        for task_type in CustomVoice VoiceDesign Base; do
            port="${PORTS[$task_type]}"
            url="http://localhost:${port}"
            if curl -sf "${url}/health" >/dev/null 2>&1; then
                echo "  [OK] ${task_type} -> ${url}"
                BACKEND_ARGS+=(--backend "${task_type}=${url}")
            else
                echo "  [--] ${task_type} (port ${port} not responding)"
            fi
        done

        if [ ${#BACKEND_ARGS[@]} -eq 0 ]; then
            echo ""
            echo "WARNING: No backends detected. Start a backend first:"
            echo "  $0 cv    # or: vd, base"
            echo ""
            echo "Starting anyway (will retry when requests come in)..."
            BACKEND_ARGS=(--api-base "http://localhost:8091")
        fi

        APP_PORT="${2:-7860}"
        echo ""
        echo "============================================"
        echo " FastAPI TTS Frontend"
        echo " URL: http://localhost:${APP_PORT}"
        echo "============================================"

        cd "$REPO_ROOT"
        exec python3 "$SCRIPT_DIR/fastapi_tts_server.py" \
            "${BACKEND_ARGS[@]}" \
            --host 0.0.0.0 \
            --port "$APP_PORT"
        ;;
    *)
        echo "Usage: $0 {customvoice|voicedesign|base|app} [port]"
        echo ""
        echo "Commands:"
        echo "  customvoice (cv)  CustomVoice 백엔드 시작 (기본 port: 8091)"
        echo "  voicedesign (vd)  VoiceDesign 백엔드 시작 (기본 port: 8092)"
        echo "  base              Base 백엔드 시작        (기본 port: 8093)"
        echo "  app               FastAPI 프론트엔드 시작 (기본 port: 7860)"
        echo "                    살아있는 백엔드를 자동 감지합니다"
        echo ""
        echo "Examples:"
        echo "  $0 cv              # 터미널1: CustomVoice 백엔드"
        echo "  $0 app             # 터미널2: 프론트엔드 (자동 감지)"
        echo "  MODEL_SIZE=0.6B $0 cv   # 0.6B 모델 사용"
        echo ""
        echo "Environment:"
        echo "  GPU_MEM_UTIL  GPU 메모리 사용률 (기본: 0.9)"
        echo "  MODEL_SIZE    1.7B 또는 0.6B (기본: 1.7B)"
        exit 1
        ;;
esac
