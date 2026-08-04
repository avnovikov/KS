from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

AssuranceLevel = Literal["high", "medium", "low"]

ASSURANCE_FIELDS = frozenset(
    {
        "power",
        "stars",
        "level",
        "pellets",
        "from_level",
        "from_stars",
        "from_skills",
        "gear_strength",
    }
)


@dataclass(frozen=True)
class FieldAssurance:
    level: AssuranceLevel
    reason: str


def _normalize_level(level: str) -> AssuranceLevel:
    normalized = level.strip().lower()
    if normalized in {"high", "medium", "low"}:
        return normalized
    return "medium"


def field_assurance(level: str, reason: str) -> FieldAssurance:
    return FieldAssurance(level=_normalize_level(level), reason=reason)


def assurance_from_dict(data: Any) -> dict[str, FieldAssurance]:
    if not isinstance(data, Mapping):
        return {}

    assurance: dict[str, FieldAssurance] = {}
    for key, raw_value in data.items():
        parsed = _coerce_assurance_value(raw_value)
        if parsed is not None:
            assurance[str(key)] = parsed
    return assurance


def assurance_to_dict(assurance: Mapping[str, FieldAssurance]) -> dict[str, dict[str, str]]:
    return {
        str(field): {"level": value.level, "reason": value.reason}
        for field, value in assurance.items()
    }


def set_field(
    assurance: Mapping[str, FieldAssurance] | Mapping[str, Any],
    field: str,
    level: str,
    reason: str,
) -> dict[str, FieldAssurance]:
    out = assurance_from_dict(assurance)
    out[field] = field_assurance(level, reason)
    return out


def ensure_legacy(
    assurance: Mapping[str, FieldAssurance] | Mapping[str, Any],
    *,
    present_fields: Mapping[str, Any],
) -> dict[str, FieldAssurance]:
    out = assurance_from_dict(assurance)
    legacy = field_assurance("medium", "legacy_unscored")
    for field in ASSURANCE_FIELDS:
        if field in out:
            continue
        if field in present_fields and present_fields[field] is not None:
            out[field] = legacy
    return out


def has_low(
    assurance: Mapping[str, FieldAssurance] | Mapping[str, Any],
    fields: Iterable[str] | None = None,
) -> bool:
    parsed = assurance_from_dict(assurance)
    candidate_fields = parsed.keys() if fields is None else fields
    for field in candidate_fields:
        field_assurance_value = parsed.get(field)
        if field_assurance_value is not None and field_assurance_value.level == "low":
            return True
    return False


def _coerce_assurance_value(raw_value: Any) -> FieldAssurance | None:
    if isinstance(raw_value, FieldAssurance):
        return field_assurance(raw_value.level, raw_value.reason)

    if isinstance(raw_value, Mapping):
        level = raw_value.get("level", "medium")
        reason = raw_value.get("reason", "legacy_unscored")
        return field_assurance(str(level), str(reason))

    return None
