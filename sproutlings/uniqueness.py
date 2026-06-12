"""Content fingerprinting for the no-repeats guarantee.

Two layers of defense:
1. canonical_hash() — SHA-256 over a *normalized* form of the content
   (whitespace-collapsed, case-folded, key-sorted JSON) so trivially
   reworded duplicates still collide.
2. The (child_id, content_hash) UNIQUE constraint in SQLite — even if two
   generation requests race, only one can ever persist.
"""
import hashlib
import json
import re
from typing import Any

_WS = re.compile(r"\s+")


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return _WS.sub(" ", value).strip().lower()
    if isinstance(value, dict):
        # Drop volatile keys that don't affect what the child sees.
        return {k: _normalize(v) for k, v in sorted(value.items())
                if k not in ("generated_at", "seed", "model")}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def canonical_hash(content: dict) -> str:
    normalized = _normalize(content)
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
