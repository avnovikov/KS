from dataclasses import dataclass
from typing import Literal

Resource = Literal["bread", "wood", "stone", "iron"]

@dataclass(frozen=True)
class GatherCandidate:
    resource: str
    tile_amount: float
    march_time_one_way_s: float
    vision_confidence: float

@dataclass(frozen=True)
class ScoredGather:
    candidate: GatherCandidate
    haul: float
    t_gather_s: float
    t_march_round_s: float
    score: float

@dataclass(frozen=True)
class Tap:
    x: int
    y: int

@dataclass(frozen=True)
class Wait:
    ms: int

Action = Tap | Wait

@dataclass(frozen=True)
class Proposal:
    kind: Literal["gather"]
    scored: ScoredGather
    actions: tuple[Action, ...]
    rationale: str
    debug_frame: str | None = None

@dataclass(frozen=True)
class NothingToDo:
    reason: str
