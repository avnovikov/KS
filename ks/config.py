from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "params.yaml"


@dataclass
class AccountConfig:
    march_load: int
    gather_rate_per_sec: dict[str, float]


@dataclass
class ScoringConfig:
    candidate_limit: int


@dataclass
class ExecutorConfig:
    max_taps_per_proposal: int
    tap_delay_ms: int
    tap_jitter_ms: int


@dataclass
class VisionConfig:
    match_threshold: float


@dataclass
class TapPoint:
    """A single screen tap coordinate loaded from YAML."""

    x: int
    y: int


@dataclass
class OcrBox:
    """A pixel-space crop box (top-left origin) for OCR, loaded from YAML."""

    x: int
    y: int
    w: int
    h: int


@dataclass
class CandidateRegion:
    """OCR regions for one gather candidate row on screen."""

    resource: str
    amount: OcrBox
    march_time: OcrBox


@dataclass
class NavigationConfig:
    """Ordered tap sequence to navigate to the gather-search screen."""

    taps: list[TapPoint] = field(default_factory=list)


@dataclass
class OcrRegionsConfig:
    """Screen regions to OCR when collecting gather candidates."""

    candidates: list[CandidateRegion] = field(default_factory=list)


@dataclass
class AppConfig:
    dry_run: bool
    adb: dict[str, Any]
    account: AccountConfig
    scoring: ScoringConfig
    resources: dict[str, Any]
    executor: ExecutorConfig
    vision: VisionConfig
    navigation: NavigationConfig
    ocr_regions: OcrRegionsConfig


def _parse_navigation(raw: Any) -> NavigationConfig:
    if not isinstance(raw, dict):
        return NavigationConfig()
    taps_raw = raw.get("taps") or []
    taps = [TapPoint(x=int(t["x"]), y=int(t["y"])) for t in taps_raw]
    return NavigationConfig(taps=taps)


def _parse_ocr_regions(raw: Any) -> OcrRegionsConfig:
    if not isinstance(raw, dict):
        return OcrRegionsConfig()
    candidates_raw = raw.get("candidates") or []
    candidates = []
    for c in candidates_raw:
        amount = OcrBox(**c["amount"])
        march_time = OcrBox(**c["march_time"])
        candidates.append(
            CandidateRegion(resource=c["resource"], amount=amount, march_time=march_time)
        )
    return OcrRegionsConfig(candidates=candidates)


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path if path is not None else _DEFAULT_CONFIG_PATH

    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    account_data = data["account"]
    march_load = account_data["march_load"]
    gather_rates = account_data["gather_rate_per_sec"]

    if march_load <= 0:
        raise ValueError(f"march_load must be positive; got {march_load}")

    for resource, rate in gather_rates.items():
        if rate <= 0:
            raise ValueError(
                f"gather_rate_per_sec[{resource!r}] must be positive; got {rate}"
            )

    return AppConfig(
        dry_run=data["dry_run"],
        adb=data.get("adb", {}),
        account=AccountConfig(
            march_load=march_load,
            gather_rate_per_sec=gather_rates,
        ),
        scoring=ScoringConfig(**data["scoring"]),
        resources=data.get("resources", {}),
        executor=ExecutorConfig(**data["executor"]),
        vision=VisionConfig(**data["vision"]),
        navigation=_parse_navigation(data.get("navigation")),
        ocr_regions=_parse_ocr_regions(data.get("ocr_regions")),
    )
