"""Central configuration for Sproutlings.

Override any value with an environment variable of the same name
prefixed with SPROUTLINGS_, e.g. SPROUTLINGS_LLM_MODEL_PATH=/mnt/d/models/other.gguf
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default):
    return os.environ.get(f"SPROUTLINGS_{name}", default)


# --- Database ---------------------------------------------------------------
DB_PATH = Path(_env("DB_PATH", BASE_DIR / "sproutlings.db"))

# --- LLM (llama.cpp server) --------------------------------------------------
# Qwen3-8B at Q4_K_M is the recommended default for a 12 GB RTX 3080 Ti:
#   ~5 GB VRAM at Q4 quantization, leaving headroom for an 8K context window
#   that comfortably fits child history + generation instructions.
# Served locally via `llama-server` (llama.cpp), auto-started by
# scripts/llm_manager.sh with full GPU offload (-ngl 99) on GPU 1
# (RTX 3080 Ti). See that script to change the GPU index or model path.
LLM_MODEL_PATH = _env("LLM_MODEL_PATH", "/mnt/d/models/Qwen_Qwen3-8B-Q4_K_M.gguf")
LLM_SERVER_URL = _env("LLM_SERVER_URL", "http://localhost:8081")
LLM_GPU_INDEX = int(_env("LLM_GPU_INDEX", "1"))
LLM_N_GPU_LAYERS = int(_env("LLM_N_GPU_LAYERS", "99"))
LLM_TIMEOUT_S = int(_env("LLM_TIMEOUT_S", "300"))
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.4"))
LLM_NUM_CTX = int(_env("LLM_NUM_CTX", "8192"))
LLM_MAX_RETRIES = int(_env("LLM_MAX_RETRIES", "3"))

# --- Domain vocabulary (extensible: append here, no other code changes) -----
GRADES = ["TK", "K", "1", "2", "3", "4", "5",
          "6", "7", "8", "9", "10", "11", "12"]

FIELDS = ["Penmanship", "Coloring", "Mathematics",
          "Literature", "Memorization", "Drawing"]

LEVELS = ["Easy", "Moderate", "Medium", "Semi hard", "Hard", "EXTREME"]

# Fields whose content is produced deterministically in code (provably
# correct, never hallucinated). Everything else goes through the LLM and
# lands in the parent-review queue before printing.
PROGRAMMATIC_FIELDS = {"Mathematics"}

# --- Generation -------------------------------------------------------------
PROBLEMS_PER_SHEET = int(_env("PROBLEMS_PER_SHEET", "12"))
SHEETS_PER_PACKET = int(_env("SHEETS_PER_PACKET", "3"))
UNIQUENESS_MAX_ATTEMPTS = int(_env("UNIQUENESS_MAX_ATTEMPTS", "25"))

# --- Adaptive engine --------------------------------------------------------
# Minimum share of a Test packet any field receives, so strong subjects
# still get refreshed instead of vanishing entirely.
TEST_FIELD_FLOOR = 0.10
# Scores at/above this suggest stepping difficulty up; below the low bound,
# stepping down.
LEVEL_UP_THRESHOLD = 0.90
LEVEL_DOWN_THRESHOLD = 0.60
# How many most-recent test results per field feed the weakness model.
ADAPTIVE_WINDOW = 5
