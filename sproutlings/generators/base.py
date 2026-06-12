"""Shared worksheet data structures (plain dicts at the edges, dataclasses
inside generators)."""
from dataclasses import dataclass, field, asdict


@dataclass
class Problem:
    prompt: str
    answer: str            # always present: parent answer key
    work_space: bool = True
    graphic: str | None = None   # optional inline SVG markup


@dataclass
class Sheet:
    title: str
    topic: str
    instructions: str
    problems: list[Problem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Packet:
    kind: str               # "worksheet" | "test"
    field_name: str | None  # None for multi-field test packets
    grade: str
    level: str
    sheets: list[Sheet] = field(default_factory=list)
    source: str = "programmatic"   # "programmatic" | "llm"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "field": self.field_name,
            "grade": self.grade,
            "level": self.level,
            "source": self.source,
            "sheets": [s.to_dict() for s in self.sheets],
        }
