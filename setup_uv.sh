#!/usr/bin/env bash
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────
PYTHON_VERSION="${1:-3.12}"
VENV_DIR="${2:-.venv}"

# ── uv 설치 확인 ──────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "Installing uv …"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "uv $(uv --version)"

# ── venv 생성 ─────────────────────────────────────────────────────────
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating venv in ${VENV_DIR} (Python ${PYTHON_VERSION}) …"
    uv venv --python "${PYTHON_VERSION}" "${VENV_DIR}"
else
    echo "Reusing existing venv at ${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# ── PyTorch (CUDA) ────────────────────────────────────────────────────
# setup.py의 detect_target_device()가 torch 존재 시 CUDA를 자동 감지하므로
# torch를 먼저 설치해야 플랫폼별 의존성이 올바르게 해석됨.
if ! python -c "import torch" &>/dev/null; then
    echo "Installing PyTorch (CUDA) …"
    uv pip install torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cu128
fi

# ── vllm (base) ──────────────────────────────────────────────────────
# vllm-omni는 vllm에 의존하지만 entrypoint 충돌 때문에 requirements에서
# 의도적으로 제외되어 있음. vllm을 먼저 설치하고 vllm-omni를 나중에 설치하면
# vllm-omni의 엔트리포인트가 우선됨.
VLLM_VERSION="${VLLM_VERSION:-0.18.0}"
if ! python -c "import vllm" &>/dev/null; then
    echo "Installing vllm ${VLLM_VERSION} …"
    uv pip install "vllm==${VLLM_VERSION}"
fi

# ── vllm-omni 의존성 + editable 설치 ─────────────────────────────────
# requirements/cuda.txt (common.txt 포함)를 먼저 설치하고,
# vllm-omni 자체는 --no-deps로 설치하여 vllm 재설치/엔트리포인트 충돌 방지.
echo "Installing vllm-omni dependencies …"
uv pip install -r requirements/cuda.txt

echo "Installing dev dependencies …"
uv pip install -e ".[dev]" --no-deps

# ── 확인 ──────────────────────────────────────────────────────────────
echo ""
echo "Done. Activate with:"
echo "  source ${VENV_DIR}/bin/activate"
echo ""
python -c "
import torch, vllm_omni
print(f'  Python : {__import__(\"sys\").version.split()[0]}')
print(f'  torch  : {torch.__version__}  (CUDA {torch.version.cuda})')
print(f'  vllm-omni : {vllm_omni.__version__}')
"
