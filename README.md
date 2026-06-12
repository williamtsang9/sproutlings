# 🌱 Sproutlings

Fresh worksheets, every time. A localhost app that generates never-repeating,
grade-and-level-targeted worksheet packets for your kids, tracks completion
per child, and adapts future packets to recent test scores — powered by a
local Qwen3 model on your GPU.

## Quick start

```bash
# One-time setup: creates a venv and installs deps
./scripts/llm_manager.sh setup

# Start llama-server (GPU-loaded Qwen3-8B) + the app together
./scripts/llm_manager.sh start      # -> http://localhost:8000
```

`start` opens a tmux session with the llama.cpp server (full GPU offload,
`-ngl 99`) loading `/mnt/d/models/Qwen_Qwen3-8B-Q4_K_M.gguf` on GPU 1, plus
the FastAPI app, side by side. Other useful commands:

```bash
./scripts/llm_manager.sh status     # check what's running
./scripts/llm_manager.sh attach     # re-attach to the tmux session
./scripts/llm_manager.sh logs       # tail llm.log / fastapi.log
./scripts/llm_manager.sh stop       # stop everything
```

Override defaults with env vars (see `./scripts/llm_manager.sh help`),
e.g. a different model file, GPU index, or port:

```bash
SPROUTLINGS_LLM_MODEL_PATH=/mnt/d/models/other.gguf \
SPROUTLINGS_LLM_GPU_INDEX=0 \
./scripts/llm_manager.sh start
```

Without tmux, you can still run things manually:

```bash
pip install -r requirements.txt
llama-server --model /mnt/d/models/Qwen_Qwen3-8B-Q4_K_M.gguf \
              --port 8081 --n-gpu-layers 99 --ctx-size 8192 --flash-attn 1
python run.py               # -> http://localhost:8000
```

Data persists in `sproutlings.db` (SQLite) next to the repo — child
profiles, packet history, completion counts and test scores all survive
restarts.

## How it works

```
frontend (vanilla JS, printable pages)
        │ JSON
FastAPI shell (api.py — thin, no logic)
        │
service.py ── uniqueness loop ── uniqueness.py (SHA-256 canonical hash)
   │    │                          + UNIQUE(child, hash) DB constraint
   │    ├─ Mathematics ──────────► generators/math_gen.py  (programmatic)
   │    └─ other fields ─────────► llm.py ► llama-server (GPU) ► Qwen3-8B
   │
repository.py ► SQLite (db.py)         adaptive.py (weights, level steps)
```

### Design decisions you should know about

**Mathematics is never LLM-generated.** Answer keys for arithmetic, fractions,
equations, etc. are *computed* by the same code that writes the problem, so
they are correct by construction. The test suite proves this by independently
re-solving 1,500+ generated problems. Math packets are auto-approved.

**LLM fields go through a review queue.** Penmanship, Coloring, Literature,
Memorization and Drawing packets are drafted by the local model and land in
`needs_review`. The review banner in the packet viewer reminds you to read
before printing, then you click **Approve**. No local model can guarantee
zero errors — the architecture treats your moderation pass as a first-class
step, not an afterthought.

**Uniqueness is enforced twice.** Content is normalized (whitespace/case
folded, volatile keys dropped) and SHA-256 hashed; generation reseeds and
retries on a hash collision, and a `UNIQUE(child_id, content_hash)` database
constraint makes a duplicate physically impossible even under racing
requests. Recent topics are also fed back into LLM prompts as
"avoid these."

**Adaptive engine.** Recording a test score updates a rolling per-field
average (last 5 tests). Test packets allocate more questions to weaker
fields (largest-remainder allocation with a floor so strong fields never
vanish), per-field difficulty steps up at ≥90% and down at <60%, and LLM
prompts receive focus hints like "Literature: recent average 55% — emphasize
foundational practice."

**Model choice: Qwen3-8B over 14B.** On a 12 GB 3080 Ti, 14B at Q4 uses
~9 GB before KV cache, starving the context window your prompts need
(child history + instructions). 8B at Q4 (~5 GB) runs an 8K context
comfortably and generates faster. To try a different model, point
`SPROUTLINGS_LLM_MODEL_PATH` at another GGUF:

```bash
SPROUTLINGS_LLM_MODEL_PATH=/mnt/d/models/Qwen_Qwen3-14B-Q4_K_M.gguf \
./scripts/llm_manager.sh start
```

### Extending the selectors

Grades, fields and levels live in `sproutlings/config.py`. Adding a new
LLM-backed field is two edits: append to `FIELDS`, and add a brief to
`_FIELD_BRIEFS` in `llm.py`. New programmatic fields implement a generator
and join `PROGRAMMATIC_FIELDS`.

## Tests

```bash
python -m pytest tests/ -v        # or: python -m unittest discover -s tests
```

40 tests cover: math correctness by independent recomputation across every
grade × level, determinism, intra-sheet uniqueness, hash normalization,
adaptive weighting/allocation/level-stepping, repository CRUD + constraint
enforcement, the full worksheet/test/score service flow with a mocked LLM,
and the HTTP API (these self-skip where FastAPI isn't installed).

## Workflow

1. Add a profile per child (the sidebar sprout meter 🌰→🌱→🌿→🌳 grows with
   every 5 completed packets).
2. Pick **Worksheet packet** (single field) or **Test packet** (multi-field
   quiz), choose grade/level, Generate.
3. Review → Approve (LLM fields) → Print (answer-key toggle prints a parent
   copy) → **Mark completed** when done.
4. For tests: **Record test score** per field — future generations adapt
   automatically.
