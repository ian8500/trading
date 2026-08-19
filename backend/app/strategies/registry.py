from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class StrategyRole(StrEnum):
    CHAMPION = "CHAMPION"
    CHALLENGER = "CHALLENGER"


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    version_id: str
    name: str
    parameters: dict[str, Any]
    created_at: datetime
    code_hash: str


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    historical_validation: bool
    walk_forward_validation: bool
    robustness_analysis: bool
    forward_demo_evidence: bool
    approved_by: str
    approved_at: datetime
    notes: str = ""

    @property
    def complete(self) -> bool:
        return bool(
            self.historical_validation
            and self.walk_forward_validation
            and self.robustness_analysis
            and self.forward_demo_evidence
            and self.approved_by
        )


class StrategyRegistry:
    def __init__(self) -> None:
        self._versions: dict[str, StrategyVersion] = {}
        self._champion: str | None = None
        self._evidence: dict[str, PromotionEvidence] = {}

    @property
    def champion(self) -> StrategyVersion | None:
        return self._versions.get(self._champion) if self._champion else None

    @property
    def challengers(self) -> tuple[StrategyVersion, ...]:
        return tuple(version for key, version in self._versions.items() if key != self._champion)

    def register(self, version: StrategyVersion) -> None:
        if version.version_id in self._versions:
            raise ValueError("strategy versions are immutable and cannot be replaced")
        self._versions[version.version_id] = version

    def promote(self, version_id: str, evidence: PromotionEvidence) -> StrategyVersion:
        if version_id not in self._versions:
            raise KeyError(version_id)
        if not evidence.complete:
            raise ValueError("promotion requires all validation and manual approval evidence")
        self._champion = version_id
        self._evidence[version_id] = evidence
        return self._versions[version_id]
