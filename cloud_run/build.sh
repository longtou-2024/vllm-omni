#!/bin/bash
# Qwen3-TTS Docker image build script
#
# Usage:
#   ./deploy.sh                              # 기본 태그(latest)로 빌드
#   IMAGE_TAG=v1.0 ./deploy.sh               # 커스텀 태그로 빌드
#
# ── 빌드 후 수동 작업 참고 ──
#
# 1) Artifact Registry에 푸쉬:
#    gcloud auth print-access-token | docker login -u oauth2accesstoken --password-stdin https://asia-northeast3-docker.pkg.dev
#    docker push asia-northeast3-docker.pkg.dev/PROJECT_ID/vllm-omni/qwen3-tts:latest
#
# 2) Cloud Run 배포 설정 (웹 콘솔에서 설정 시 참고):
#    - Container image: asia-northeast3-docker.pkg.dev/PROJECT_ID/vllm-omni/qwen3-tts:latest
#    - Port: 8080
#    - CPU: 8
#    - Memory: 32Gi
#    - GPU: 1 x nvidia-l4
#    - Max instances: 3
#    - Min instances: 0 (콜드스타트 허용) or 1 (상시 대기)
#    - Max concurrent requests per instance: 8
#    - Request timeout: 300s
#    - CPU always allocated (no throttling)
#
# 3) 환경변수 (Container > Variables):
#    - MODEL_PATH=/gcs/models/Qwen3-TTS-12Hz-0.6B-CustomVoice
#    - PORT=8080
#    - GPU_MEM_UTIL=0.9  (선택)
#
# 4) GCS 볼륨 마운트 (Container > Volume Mounts):
#    - Volume type: Cloud Storage bucket
#    - Bucket: your-model-bucket
#    - Mount path: /gcs
#

set -e

IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_NAME="${IMAGE_NAME:-qwen3-tts}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Building Docker image ==="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"

cd "$REPO_ROOT"
docker build \
    -f cloud_run/Dockerfile \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    .

echo ""
echo "=== Build complete ==="
echo "Local image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "To tag for Artifact Registry:"
echo "  docker tag ${IMAGE_NAME}:${IMAGE_TAG} asia-northeast3-docker.pkg.dev/dev-ai-project-357507/tts/${IMAGE_NAME}:${IMAGE_TAG}"
