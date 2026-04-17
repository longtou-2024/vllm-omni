#!/bin/bash
# Launch vLLM-Omni server for Qwen3-TTS on L4 GPU
#
# Usage:
#   ./run_server_l4.sh                          # Default: 0.6B, CustomVoice
#   ./run_server_l4.sh 0.6B CustomVoice 8091    # explicit
#   ./run_server_l4.sh 1.7B Base 8091           # 1.7B Base model

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

MODEL_SIZE="${1:-0.6B}"
TASK_TYPE="${2:-CustomVoice}"
PORT="${3:-8091}"
STAGE_CONFIG="${REPO_ROOT}/cloud_run/stage_config.yaml"

case "$MODEL_SIZE/$TASK_TYPE" in
    1.7B/CustomVoice)  MODEL="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice" ;;
    1.7B/VoiceDesign)  MODEL="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign" ;;
    1.7B/Base)         MODEL="Qwen/Qwen3-TTS-12Hz-1.7B-Base" ;;
    0.6B/CustomVoice)  MODEL="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice" ;;
    0.6B/Base)         MODEL="Qwen/Qwen3-TTS-12Hz-0.6B-Base" ;;
    *)
        echo "Unknown combination: MODEL_SIZE=$MODEL_SIZE, TASK_TYPE=$TASK_TYPE"
        echo "Supported sizes: 1.7B, 0.6B"
        echo "Supported types: CustomVoice, VoiceDesign (1.7B only), Base"
        exit 1
        ;;
esac

echo "============================================"
echo " Qwen3-TTS L4 Server"
echo "============================================"
echo " Model:        $MODEL"
echo " Stage Config: $STAGE_CONFIG"
echo " Port:         $PORT"
echo "============================================"
echo ""

cd "$REPO_ROOT"

vllm-omni serve "$MODEL" \
    --stage-configs-path "$STAGE_CONFIG" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --gpu-memory-utilization 0.9 \
    --trust-remote-code \
    --enforce-eager \
    --omni
