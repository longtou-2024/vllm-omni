#!/bin/bash

# ── Configurable via environment variables ──
#
# Model source (choose one):
#   GCS_MODEL_PATH=gs://bucket/path/to/model  → copies to local disk first (fast, recommended)
#   MODEL_PATH=/gcs/path/to/model              → uses GCS FUSE directly (slow)
#   MODEL_PATH=Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice → downloads from HuggingFace
GCS_MODEL_PATH="${GCS_MODEL_PATH:-}"
MODEL_PATH="${MODEL_PATH:-/home/longtou.2024/mount/longtou/saved/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice}"
LOCAL_MODEL_DIR="/tmp/model"

# Server config
BACKEND_PORT="${BACKEND_PORT:-8091}"
FRONTEND_PORT="${PORT:-8080}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.9}"
STAGE_CONFIG="${STAGE_CONFIG:-/etc/vllm-omni/stage_config.yaml}"
FRONTEND_SCRIPT="${FRONTEND_SCRIPT:-/app/frontend/fastapi_tts_server.py}"

echo "============================================"
echo " Qwen3-TTS Cloud Run Server"
echo "============================================"
echo " GCS Model:     ${GCS_MODEL_PATH:-not set}"
echo " Model Path:    ${MODEL_PATH}"
echo " Backend Port:  ${BACKEND_PORT}"
echo " Frontend Port: ${FRONTEND_PORT}"
echo " GPU Mem Util:  ${GPU_MEM_UTIL}"
echo " Stage Config:  ${STAGE_CONFIG}"
echo "============================================"

# 0) Fix /dev/shm for vllm multiprocessing
if [ -d /mnt/shm ]; then
    echo "Binding /mnt/shm over /dev/shm..."
    mount --bind /mnt/shm /dev/shm 2>/dev/null && echo "OK: /dev/shm now backed by in-memory volume ($(df -h /dev/shm | awk 'NR==2{print $2}'))" || true
fi
echo "/dev/shm size: $(df -h /dev/shm | awk 'NR==2{print $2}')"

# 0.5) Patch vllm-omni startup timeout
INIT_TIMEOUT="${VLLM_OMNI_INIT_TIMEOUT:-3600}"
STAGE_TIMEOUT="${VLLM_OMNI_STAGE_INIT_TIMEOUT:-1800}"
echo "Patching orchestrator timeout: init=${INIT_TIMEOUT}s, stage=${STAGE_TIMEOUT}s"
OMNI_BASE=$(python3 -c "import vllm_omni.entrypoints.omni_base as m; print(m.__file__)")
sed -i "s/\"stage_init_timeout\", 300/\"stage_init_timeout\", ${STAGE_TIMEOUT}/" "$OMNI_BASE"
sed -i "s/\"init_timeout\", 600/\"init_timeout\", ${INIT_TIMEOUT}/" "$OMNI_BASE"

# 1) Download model from GCS to local disk (much faster than GCS FUSE)
if [ -n "${GCS_MODEL_PATH}" ]; then
    echo "Copying model from GCS to local disk..."
    echo "  Source: ${GCS_MODEL_PATH}"
    echo "  Dest:   ${LOCAL_MODEL_DIR}"
    START_TIME=$(date +%s)
    mkdir -p "${LOCAL_MODEL_DIR}"
    gcloud storage cp -r "${GCS_MODEL_PATH}/*" "${LOCAL_MODEL_DIR}/" 2>&1
    END_TIME=$(date +%s)
    ELAPSED=$((END_TIME - START_TIME))
    MODEL_SIZE=$(du -sh "${LOCAL_MODEL_DIR}" 2>/dev/null | cut -f1)
    echo "Model copy complete: ${MODEL_SIZE} in ${ELAPSED}s"
    MODEL_PATH="${LOCAL_MODEL_DIR}"
fi

echo "Using model: ${MODEL_PATH}"

# 2) Start FastAPI frontend in BACKGROUND (for Cloud Run health check)
python3 "${FRONTEND_SCRIPT}" \
    --api-base "http://127.0.0.1:${BACKEND_PORT}" \
    --host 0.0.0.0 \
    --port "${FRONTEND_PORT}" &
FRONTEND_PID=$!
echo "FastAPI frontend started (PID ${FRONTEND_PID}) on port ${FRONTEND_PORT}"

# 3) Start vllm-omni backend in FOREGROUND
exec vllm-omni serve "${MODEL_PATH}" \
    --stage-configs-path "${STAGE_CONFIG}" \
    --host 127.0.0.1 \
    --port "${BACKEND_PORT}" \
    --gpu-memory-utilization "${GPU_MEM_UTIL}" \
    --trust-remote-code \
    --enforce-eager \
    --omni
