"""Adaptive engine.

Turns recent test scores into:
  * a weakness weight per field (drives how a Test packet's questions are
    allocated — weaker fields get more questions),
  * a difficulty suggestion per field (step level up on strong scores,
    down on weak ones),
  * focus hints injected into LLM prompts ("scored 55% recently in
    Literature — emphasize reading comprehension").

Pure functions only; trivially testable.
"""
from . import config


def weakness_weights(scores: dict[str, float],
                     fields: list[str]) -> dict[str, float]:
    """Map each field to a normalized weight in (0, 1], summing to 1.

    Fields with no score history are treated as moderately unknown (0.5
    weakness) so they're neither ignored nor over-prioritized. A floor
    keeps strong fields from disappearing entirely.
    """
    if not fields:
        return {}
    raw = {}
    for f in fields:
        score = scores.get(f)
        weakness = 0.5 if score is None else max(0.0, 1.0 - score)
        raw[f] = max(weakness, config.TEST_FIELD_FLOOR)
    total = sum(raw.values())
    return {f: w / total for f, w in raw.items()}


def allocate_questions(total_questions: int, weights: dict[str, float]
                       ) -> dict[str, int]:
    """Largest-remainder allocation: every field gets >= 1 question and the
    counts always sum exactly to total_questions."""
    if not weights:
        return {}
    n_fields = len(weights)
    if total_questions < n_fields:
        raise ValueError(
            f"Need at least {n_fields} questions for {n_fields} fields.")
    exact = {f: w * total_questions for f, w in weights.items()}
    base = {f: max(1, int(e)) for f, e in exact.items()}
    # Repair sum: trim from the most over-allocated or top up the largest
    # remainders until exact.
    diff = total_questions - sum(base.values())
    order = sorted(weights, key=lambda f: exact[f] - int(exact[f]),
                   reverse=True)
    i = 0
    while diff != 0:
        f = order[i % len(order)]
        if diff > 0:
            base[f] += 1
            diff -= 1
        elif base[f] > 1:
            base[f] -= 1
            diff += 1
        i += 1
    return base


def suggest_level(current_level: str, score: float | None) -> str:
    """Step difficulty up/down one notch based on the recent average."""
    if score is None or current_level not in config.LEVELS:
        return current_level
    idx = config.LEVELS.index(current_level)
    if score >= config.LEVEL_UP_THRESHOLD and idx < len(config.LEVELS) - 1:
        return config.LEVELS[idx + 1]
    if score < config.LEVEL_DOWN_THRESHOLD and idx > 0:
        return config.LEVELS[idx - 1]
    return current_level


def focus_hints(scores: dict[str, float]) -> list[str]:
    """Human-readable hints for the LLM prompt, weakest first."""
    hints = []
    for field, score in sorted(scores.items(), key=lambda kv: kv[1]):
        pct = round(score * 100)
        if score < config.LEVEL_DOWN_THRESHOLD:
            hints.append(f"{field}: recent test average {pct}% — this is a "
                         f"weak area; emphasize foundational practice.")
        elif score < config.LEVEL_UP_THRESHOLD:
            hints.append(f"{field}: recent test average {pct}% — solid; "
                         f"mix review with mild stretch problems.")
        else:
            hints.append(f"{field}: recent test average {pct}% — strong; "
                         f"introduce enrichment material.")
    return hints
