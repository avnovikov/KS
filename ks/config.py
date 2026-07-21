from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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
class AppConfig:
    dry_run: bool
    adb: dict[str, Any]
    account: AccountConfig
    scoring: ScoringConfig
    resources: dict[str, Any]
    executor: ExecutorConfig
    vision: VisionConfig
    navigation: dict[str, Any]


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path if path is not None else Path("config/params.yaml")

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
        navigation=data.get("navigation", {}),
    )
