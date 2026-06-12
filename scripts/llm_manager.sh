#!/bin/bash
# Sproutlings TMUX Session Manager
# Manages the local llama.cpp server (GPU-loaded Qwen3-8B) + FastAPI app
# in a single tmux session.
#
# Usage:
#   ./scripts/llm_manager.sh setup   - Create venv and install deps
#   ./scripts/llm_manager.sh start   - Start llama-server + app
#   ./scripts/llm_manager.sh stop    - Stop everything
#   ./scripts/llm_manager.sh restart - Restart everything
#   ./scripts/llm_manager.sh status  - Show status of all processes
#   ./scripts/llm_manager.sh attach  - Attach to the tmux session
#   ./scripts/llm_manager.sh logs    - Tail all logs
set -euo pipefail

SESSION="sproutlings"

# Configuration (override via env vars)
LLAMA_BIN="${SPROUTLINGS_LLAMA_BIN:-/usr/local/bin/llama-server}"
MODEL_PATH="${SPROUTLINGS_LLM_MODEL_PATH:-/mnt/d/models/Qwen_Qwen3-8B-Q4_K_M.gguf}"

# GPU physical index (verify with: nvidia-smi -L)
# Index 1 = RTX 3080 Ti (12 GB) — matches sleepytrade's GPU1 layout.
LLM_GPU="${SPROUTLINGS_LLM_GPU_INDEX:-1}"
LLM_PORT="${SPROUTLINGS_LLM_PORT:-8081}"
LLM_CTX="${SPROUTLINGS_LLM_NUM_CTX:-8192}"
LLM_NGL="${SPROUTLINGS_LLM_N_GPU_LAYERS:-99}"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
FASTAPI_HOST="0.0.0.0"
FASTAPI_PORT="${SPROUTLINGS_PORT:-8000}"
LOG_DIR="${PROJECT_DIR}/logs"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

mkdir -p "$LOG_DIR"

log_info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_err()   { echo -e "${RED}[ERROR]${NC} $1"; }

find_python() {
    local py=""
    for candidate in python3.12 python3.11 python3; do
        if command -v "$candidate" &>/dev/null; then
            local ver major minor
            ver=$("$candidate" --version 2>&1 | grep -oP '\d+\.\d+')
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
                py="$candidate"
                break
            fi
        fi
    done
    if [ -z "$py" ]; then
        log_err "Python 3.11+ required. Run: sudo apt install python3.11 python3.11-venv"
        exit 1
    fi
    echo "$py"
}

ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        log_warn "Virtualenv not found at ${VENV_DIR}"
        log_info "Creating virtualenv ..."
        local py
        py=$(find_python)
        "$py" -m venv "$VENV_DIR"
        source "${VENV_DIR}/bin/activate"
        pip install --upgrade pip -q
        pip install -r "${PROJECT_DIR}/requirements.txt"
        deactivate
        log_ok "Virtualenv created and dependencies installed."
    else
        log_ok "Virtualenv found at ${VENV_DIR}"
    fi
}

check_port() {
    local port=$1
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        return 0
    fi
    return 1
}

do_setup() {
    log_info "Running environment setup ..."
    ensure_venv
    if [ ! -f "$MODEL_PATH" ]; then
        log_warn "Model file not found at ${MODEL_PATH}"
        log_warn "Set SPROUTLINGS_LLM_MODEL_PATH or place the GGUF there."
    else
        log_ok "Model found at ${MODEL_PATH}"
    fi
    if ! command -v "$LLAMA_BIN" &>/dev/null; then
        log_warn "llama-server not found at ${LLAMA_BIN} (set SPROUTLINGS_LLAMA_BIN)"
    else
        log_ok "llama-server found at ${LLAMA_BIN}"
    fi
}

do_start() {
    log_info "Starting Sproutlings services ..."
    ensure_venv

    tmux kill-session -t "$SESSION" 2>/dev/null || true
    sleep 1

    # Create session and configure colored pane borders
    tmux new-session -d -s "$SESSION" -n "main" -x 220 -y 50
    tmux set-option -t "$SESSION" pane-border-status top
    tmux set-option -t "$SESSION" pane-active-border-style "fg=colour15,bold"
    tmux set-option -t "$SESSION" pane-border-style "fg=colour6"
    tmux set-option -t "$SESSION" pane-border-format "\
#{?#{==:#{pane_index},0},#[fg=colour82 bold],}\
#{?#{==:#{pane_index},1},#[fg=colour117 bold],}\
 #{pane_title} #[default]"

    # ┌──────────────────────┬──────────────────────┐
    # │  LLM (Qwen3-8B GPU1)  │  FastAPI              │
    # └──────────────────────┴──────────────────────┘
    tmux split-window -h -t "$SESSION:main.0"

    tmux select-pane -t "$SESSION:main.0" -T "LLM — Qwen3-8B | GPU${LLM_GPU} | :${LLM_PORT} | loading..."
    tmux select-pane -t "$SESSION:main.1" -T "FastAPI | :${FASTAPI_PORT}"

    # Pane 0: llama-server, full GPU offload onto LLM_GPU
    tmux send-keys -t "$SESSION:main.0" \
        "CUDA_VISIBLE_DEVICES=${LLM_GPU} ${LLAMA_BIN} \
        --model ${MODEL_PATH} \
        --port ${LLM_PORT} --host 0.0.0.0 \
        --n-gpu-layers ${LLM_NGL} --ctx-size ${LLM_CTX} \
        --flash-attn 1 2>&1 | tee ${LOG_DIR}/llm.log" C-m

    # Pane 1: FastAPI app
    tmux send-keys -t "$SESSION:main.1" \
        "cd ${PROJECT_DIR} && \
        SPROUTLINGS_LLM_SERVER_URL=http://localhost:${LLM_PORT} \
        SPROUTLINGS_LLM_MODEL_PATH=${MODEL_PATH} \
        ${VENV_DIR}/bin/python run.py 2>&1 | tee ${LOG_DIR}/fastapi.log" C-m

    # GPU stat updater in pane titles (every 3s)
    if command -v nvidia-smi &>/dev/null; then
        tmux new-window -t "$SESSION" -n "gpu-stats"
        tmux send-keys -t "$SESSION:gpu-stats" '
gpu_label() {
    local idx=$1 label=$2 port=$3
    nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total \
        --format=csv,noheader,nounits --id="$idx" 2>/dev/null \
    | awk -F", " -v label="$label" -v port="$port" '"'"'
    {
        temp=$1; util=$2; vram_used=$3; vram_total=$4
        if (temp < 70)       tc="#[fg=colour82]"
        else if (temp < 85)  tc="#[fg=colour208]"
        else                 tc="#[fg=colour196]"
        if (util < 60)       uc="#[fg=colour82]"
        else if (util < 90)  uc="#[fg=colour208]"
        else                 uc="#[fg=colour196]"
        rst="#[default]"
        printf "%s | %s | Temp: %s%s°C%s  Util: %s%s%%%s  VRAM: %s/%s MiB",
            label, port, tc, temp, rst, uc, util, rst, vram_used, vram_total
    }'"'"'
}
while true; do
    G0=$(gpu_label '"${LLM_GPU}"' "LLM — Qwen3-8B" ":'"${LLM_PORT}"'")
    tmux select-pane -t '"$SESSION"':main.0 -T "$G0"
    tmux select-pane -t '"$SESSION"':main.1 -T "FastAPI | :'"${FASTAPI_PORT}"'"
    sleep 3
done' C-m
        tmux select-window -t "$SESSION:main"
        log_ok "GPU stat updater running (updates every 3s)"
    else
        log_warn "nvidia-smi not found — pane titles will be static"
    fi

    log_ok "All services launched in tmux session '${SESSION}'"
    tmux attach -t "${SESSION}"
}

do_stop() {
    log_info "Stopping Sproutlings services ..."
    tmux kill-session -t "$SESSION" 2>/dev/null && log_ok "Session killed" || log_warn "Session not found"
}

do_restart() {
    do_stop
    sleep 2
    do_start
}

do_status() {
    echo -e "\n${CYAN}=== Sproutlings Service Status ===${NC}\n"
    for port_info in "${LLM_PORT}:LLM (Qwen3-8B, GPU${LLM_GPU})" "${FASTAPI_PORT}:FastAPI"; do
        port="${port_info%%:*}"
        name="${port_info#*:}"
        if check_port "$port"; then
            echo -e "  ${GREEN}*${NC} ${name} -- port ${port} ${GREEN}UP${NC}"
        else
            echo -e "  ${RED}*${NC} ${name} -- port ${port} ${RED}DOWN${NC}"
        fi
    done
    echo ""
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo -e "  ${GREEN}*${NC} tmux '${SESSION}' ${GREEN}ACTIVE${NC}"
    else
        echo -e "  ${RED}*${NC} tmux '${SESSION}' ${RED}NOT FOUND${NC}"
    fi
    echo ""
}

do_attach() {
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux attach -t "$SESSION"
    else
        log_err "Session not found. Run: $0 start"
        exit 1
    fi
}

do_logs() {
    if command -v multitail &>/dev/null; then
        multitail -l "tail -f ${LOG_DIR}/llm.log" -l "tail -f ${LOG_DIR}/fastapi.log"
    else
        tail -f "${LOG_DIR}"/*.log
    fi
}

case "${1:-help}" in
    setup)   do_setup ;;
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    status)  do_status ;;
    attach)  do_attach ;;
    logs)    do_logs ;;
    help|*)
        echo ""
        echo -e "${CYAN}Sproutlings LLM/App Manager${NC}"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  setup     Create virtualenv, install deps, check model/binary"
        echo "  start     Start llama-server (GPU) + FastAPI app"
        echo "  stop      Stop everything"
        echo "  restart   Restart everything"
        echo "  status    Show service status"
        echo "  attach    Attach to the tmux session"
        echo "  logs      Tail all log files"
        echo ""
        echo "Config (env vars):"
        echo "  SPROUTLINGS_LLAMA_BIN       path to llama-server (default /usr/local/bin/llama-server)"
        echo "  SPROUTLINGS_LLM_MODEL_PATH  GGUF path (default /mnt/d/models/Qwen_Qwen3-8B-Q4_K_M.gguf)"
        echo "  SPROUTLINGS_LLM_GPU_INDEX   GPU index for CUDA_VISIBLE_DEVICES (default 1)"
        echo "  SPROUTLINGS_LLM_PORT        llama-server port (default 8081)"
        echo "  SPROUTLINGS_LLM_NUM_CTX     context size (default 8192)"
        echo "  SPROUTLINGS_LLM_N_GPU_LAYERS  GPU layers to offload (default 99 = all)"
        echo "  SPROUTLINGS_PORT            FastAPI port (default 8000)"
        echo ""
        ;;
esac
