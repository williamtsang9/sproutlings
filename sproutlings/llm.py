"""llama.cpp server client — stdlib urllib only, no SDK dependency.

Talks to a local `llama-server` instance (started by
scripts/llm_manager.sh, which loads config.LLM_MODEL_PATH onto the GPU)
via its native /completion endpoint.

Accuracy posture for LLM-generated fields:
  * temperature kept low (config.LLM_TEMPERATURE)
  * the model must reply with strict JSON matching our schema; anything
    else is rejected and retried
  * Qwen3 thinking mode is disabled via "/no_think" for predictable,
    fast structured output
  * every LLM packet is created with status 'needs_review' so a parent
    approves it before printing — the LLM is a drafting tool, not an
    unsupervised teacher.
"""
import json
import re
import urllib.request
import urllib.error

from . import config


class LLMError(Exception):
    pass


class LLMValidationError(LLMError):
    """Model replied, but not with valid worksheet JSON."""


SYSTEM_PROMPT = """\
You are an expert elementary-through-high-school curriculum writer.
You produce printable worksheet content for a parent to review.

Hard rules:
- Respond with ONLY a JSON object. No prose, no markdown fences, no preamble.
- Use only well-established, uncontroversial educational facts.
- Never invent quotations, book excerpts, dates, or statistics.
- Age-appropriate vocabulary for the stated grade.
- Each item must include a model answer or completion guidance for the parent.

JSON schema (exactly these keys):
{
  "title": str,
  "topic": str,             // short topic label, e.g. "Cursive lowercase a-e"
  "instructions": str,      // what the child should do
  "problems": [             // the requested number of items
    {"prompt": str, "answer": str}
  ]
}
"""

_FIELD_BRIEFS = {
    "Penmanship": ("Letter/word/sentence tracing and copying practice. "
                   "prompt = the text to trace or copy (with a hint like "
                   "'Trace, then write 3 times'); answer = what correct "
                   "letter formation looks like, for the parent."),
    "Coloring": ("Color-by-instruction activities the parent can draw or "
                 "print alongside: e.g. 'Draw and color 3 red apples and 2 "
                 "green pears', counting-and-coloring, pattern coloring. "
                 "answer = what a correct finished page contains."),
    "Literature": ("Reading comprehension. Write an ORIGINAL short passage "
                   "(2-6 sentences for young grades, longer for older) "
                   "inside the first problem's prompt, then comprehension "
                   "questions about it in later problems. Never quote or "
                   "imitate existing copyrighted works."),
    "Memorization": ("Recall drills on well-established facts only: "
                     "days of the week, months, skip counting, state "
                     "capitals, multiplication tables, common-knowledge "
                     "science facts. answer = the exact correct recall."),
    "Drawing": ("Step-by-step guided drawing prompts and observational "
                "drawing tasks. answer = what to look for in a completed "
                "drawing."),
}


def build_prompt(field: str, grade: str, level: str, n_problems: int,
                 avoid_topics: list[str], focus_hints: list[str],
                 child_age: int | None, seed: int) -> str:
    if field not in _FIELD_BRIEFS:
        raise ValueError(f"No LLM brief for field {field!r}")
    avoid = ("\nAlready covered recently — choose a DIFFERENT topic than: "
             + "; ".join(avoid_topics)) if avoid_topics else ""
    focus = ("\nChild performance context:\n- " + "\n- ".join(focus_hints)
             ) if focus_hints else ""
    age = f" The child is {child_age} years old." if child_age else ""
    return (f"/no_think\nCreate ONE {field} worksheet.\n"
            f"Grade: {grade}. Difficulty: {level}.{age}\n"
            f"Field brief: {_FIELD_BRIEFS[field]}\n"
            f"Number of items: exactly {n_problems}."
            f"{avoid}{focus}\n"
            f"Variation seed (use it to pick a fresh angle): {seed}\n"
            f"Reply with the JSON object only.")


def _post(payload: dict) -> dict:
    req = urllib.request.Request(
        f"{config.LLM_SERVER_URL}/completion",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise LLMError(
            f"Cannot reach llama-server at {config.LLM_SERVER_URL}. "
            f"Is it running? (./scripts/llm_manager.sh start)  [{e}]") from e


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_sheet_json(raw: str, expected_problems: int) -> dict:
    """Strict validation of model output against our schema."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    m = _JSON_RE.search(raw)
    if not m:
        raise LLMValidationError("No JSON object found in model output.")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise LLMValidationError(f"Malformed JSON: {e}") from e

    for key in ("title", "topic", "instructions", "problems"):
        if key not in data:
            raise LLMValidationError(f"Missing key: {key}")
    if not isinstance(data["problems"], list) or not data["problems"]:
        raise LLMValidationError("problems must be a non-empty list")
    for i, p in enumerate(data["problems"]):
        if not isinstance(p, dict) or not p.get("prompt") \
                or not str(p.get("answer", "")).strip():
            raise LLMValidationError(f"problem {i} missing prompt/answer")
    if len(data["problems"]) < max(1, expected_problems // 2):
        raise LLMValidationError(
            f"Model returned {len(data['problems'])} items, expected "
            f"~{expected_problems}.")
    return {
        "title": str(data["title"]),
        "topic": str(data["topic"]),
        "instructions": str(data["instructions"]),
        "problems": [{"prompt": str(p["prompt"]),
                      "answer": str(p["answer"]),
                      "work_space": True}
                     for p in data["problems"]],
    }


# Qwen3's chat template wraps turns in these tags; llama-server's
# /completion endpoint takes a raw prompt string, so we build it ourselves.
# (Plain concatenation, not str.format — SYSTEM_PROMPT contains literal
# { } braces in its JSON schema example.)
def _build_full_prompt(system: str, user: str) -> str:
    return (f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n")


def generate_sheet(field: str, grade: str, level: str, n_problems: int,
                   avoid_topics: list[str], focus_hints: list[str],
                   child_age: int | None, seed: int) -> dict:
    """One validated sheet dict from the local model, with retries."""
    user_prompt = build_prompt(field, grade, level, n_problems,
                               avoid_topics, focus_hints, child_age, seed)
    full_prompt = _build_full_prompt(SYSTEM_PROMPT, user_prompt)
    last_err: Exception | None = None
    for attempt in range(config.LLM_MAX_RETRIES):
        resp = _post({
            "prompt": full_prompt,
            "temperature": config.LLM_TEMPERATURE + 0.1 * attempt,
            "n_ctx": config.LLM_NUM_CTX,
            "n_predict": -1,
            "seed": seed + attempt,
            "cache_prompt": True,
        })
        try:
            return parse_sheet_json(resp.get("content", ""), n_problems)
        except LLMValidationError as e:
            last_err = e
    raise LLMError(
        f"Model failed validation after {config.LLM_MAX_RETRIES} attempts: "
        f"{last_err}")
