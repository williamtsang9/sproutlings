"""Generation service — the orchestration layer.

Routing:
  Mathematics            -> programmatic generator (correct by construction)
  all other fields       -> local LLM via Ollama, parent review required

Uniqueness loop:
  hash candidate content -> if seen for this child, reseed and regenerate
  (up to UNIQUENESS_MAX_ATTEMPTS) -> persist packet + hash atomically.
"""
import random
import time

from . import config, llm, adaptive
from .repository import Repository, DuplicateContentError
from .uniqueness import canonical_hash
from .generators import math_gen
from .generators.base import Packet, Sheet, Problem


class GenerationError(Exception):
    pass


def _fresh_seed() -> int:
    return random.SystemRandom().randrange(2 ** 31)


def _build_worksheet(field: str, grade: str, level: str, seed: int,
                     repo: Repository, child: dict) -> dict:
    if field in config.PROGRAMMATIC_FIELDS:
        return math_gen.generate_math_packet(grade, level, seed).to_dict()

    scores = repo.recent_scores(child["id"])
    hints = adaptive.focus_hints({field: scores[field]}) \
        if field in scores else []
    avoid = repo.recent_topics(child["id"], field)
    sheets = []
    for s in range(config.SHEETS_PER_PACKET):
        sheet = llm.generate_sheet(
            field=field, grade=grade, level=level,
            n_problems=config.PROBLEMS_PER_SHEET,
            avoid_topics=avoid + [sh["topic"] for sh in sheets],
            focus_hints=hints, child_age=child.get("age"),
            seed=seed + s,
        )
        sheets.append(sheet)
    return {"kind": "worksheet", "field": field, "grade": grade,
            "level": level, "source": "llm", "sheets": sheets}


def generate_worksheet_packet(repo: Repository, child_id: int, field: str,
                              grade: str, level: str) -> dict:
    """Generate, dedupe, persist. Returns the stored packet."""
    child = repo.get_child(child_id)
    if child is None:
        raise GenerationError(f"No child with id {child_id}")
    if field not in config.FIELDS:
        raise GenerationError(f"Unknown field: {field!r}")
    if grade not in config.GRADES:
        raise GenerationError(f"Unknown grade: {grade!r}")
    if level not in config.LEVELS:
        raise GenerationError(f"Unknown level: {level!r}")

    last_hash = None
    for _ in range(config.UNIQUENESS_MAX_ATTEMPTS):
        seed = _fresh_seed()
        content = _build_worksheet(field, grade, level, seed, repo, child)
        h = canonical_hash(content)
        if repo.hash_exists(child_id, h):
            last_hash = h
            continue
        try:
            packet_id = repo.save_packet(
                child_id, "worksheet", field, grade, level, content, h)
        except DuplicateContentError:
            last_hash = h
            continue
        # Mathematics is correct by construction -> auto-approved.
        if content["source"] == "programmatic":
            repo.set_packet_status(packet_id, "approved")
        return repo.get_packet(packet_id)
    raise GenerationError(
        f"Could not produce unique content after "
        f"{config.UNIQUENESS_MAX_ATTEMPTS} attempts (last hash {last_hash}). "
        f"Try a different grade/level combination.")


def generate_test_packet(repo: Repository, child_id: int, fields: list[str],
                         grade: str, level: str,
                         total_questions: int = 20) -> dict:
    """Multi-field quiz. Question counts per field are weighted by the
    child's recent weakness; weaker fields get more questions."""
    child = repo.get_child(child_id)
    if child is None:
        raise GenerationError(f"No child with id {child_id}")
    bad = [f for f in fields if f not in config.FIELDS]
    if bad or not fields:
        raise GenerationError(f"Invalid fields: {bad or '(empty)'}")

    scores = repo.recent_scores(child_id)
    weights = adaptive.weakness_weights(scores, fields)
    allocation = adaptive.allocate_questions(total_questions, weights)
    hints = adaptive.focus_hints(scores)

    for _ in range(config.UNIQUENESS_MAX_ATTEMPTS):
        seed = _fresh_seed()
        packet = Packet(kind="test", field_name=None, grade=grade,
                        level=level, source="mixed")
        for field, n in allocation.items():
            eff_level = adaptive.suggest_level(level, scores.get(field))
            if field in config.PROGRAMMATIC_FIELDS:
                problems = math_gen.generate_math_questions(
                    grade, eff_level, seed + hash(field) % 1000, n)
                sheet = Sheet(
                    title=f"Test — {field} ({n} questions, {eff_level})",
                    topic=f"{field} assessment",
                    instructions="Answer every question.",
                    problems=problems)
            else:
                data = llm.generate_sheet(
                    field=field, grade=grade, level=eff_level,
                    n_problems=n,
                    avoid_topics=repo.recent_topics(child_id, field),
                    focus_hints=hints, child_age=child.get("age"),
                    seed=seed)
                sheet = Sheet(
                    title=f"Test — {field} ({n} questions, {eff_level})",
                    topic=data["topic"],
                    instructions=data["instructions"],
                    problems=[Problem(**p) for p in data["problems"][:n]])
            packet.sheets.append(sheet)

        content = packet.to_dict()
        content["allocation"] = allocation
        h = canonical_hash(content)
        if repo.hash_exists(child_id, h):
            continue
        try:
            packet_id = repo.save_packet(
                child_id, "test", None, grade, level, content, h)
        except DuplicateContentError:
            continue
        return repo.get_packet(packet_id)
    raise GenerationError("Could not produce a unique test packet.")


def record_test_result(repo: Repository, packet_id: int,
                       per_field: dict[str, tuple[int, int]]) -> dict:
    packet = repo.get_packet(packet_id)
    if packet is None or packet["kind"] != "test":
        raise GenerationError(f"Packet {packet_id} is not a test packet.")
    repo.record_test_scores(packet_id, packet["child_id"], per_field)
    repo.set_packet_status(packet_id, "completed")
    return {"recorded": {f: f"{c}/{t}" for f, (c, t) in per_field.items()},
            "new_averages": repo.recent_scores(packet["child_id"])}
