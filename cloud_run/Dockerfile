ARG VLLM_BASE_IMAGE=vllm/vllm-openai
ARG VLLM_BASE_TAG=v0.18.0
FROM ${VLLM_BASE_IMAGE}:${VLLM_BASE_TAG}

ARG APP_DIR=/workspace/vllm-omni
WORKDIR ${APP_DIR}

# ── Layer 1: System dependencies (rarely changes) ──
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        espeak-ng ffmpeg git sox libsox-fmt-all curl apt-transport-https ca-certificates gnupg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
        > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
        | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    apt-get update && apt-get install -y --no-install-recommends google-cloud-cli && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ── Layer 2: Python dependencies (changes when requirements change) ──
COPY requirements/ ${APP_DIR}/requirements/
RUN uv pip install --system --no-cache-dir \
    -r requirements/cuda.txt httpx uvicorn websockets

# ── Layer 3: vllm-omni source install (changes when vllm-omni code changes) ──
COPY pyproject.toml setup.py setup.cfg* ${APP_DIR}/
COPY vllm_omni/ ${APP_DIR}/vllm_omni/
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.18.0 uv pip install --system --no-cache-dir --no-deps .

# ── Layer 4: Cloud Run files (changes most frequently, fast to rebuild) ──
COPY cloud_run/stage_config.yaml /etc/vllm-omni/stage_config.yaml
COPY cloud_run/fastapi_tts_server.py /app/frontend/fastapi_tts_server.py
COPY cloud_run/index.html /app/frontend/index.html
COPY cloud_run/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
