from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.decimal import ONE, ZERO, as_decimal


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    raw_score: Decimal
    won: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_score", as_decimal(self.raw_score))


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    lower: Decimal
    upper: Decimal
    predicted_probability: Decimal
    observed_win_rate: Decimal
    sample_size: int
    calibration_error: Decimal


class EmpiricalScoreCalibrator:
    """Simple inspectable equal-width reliability calibration."""

    def __init__(self, bucket_count: int = 10, minimum_bucket_size: int = 30) -> None:
        if bucket_count < 2:
            raise ValueError("bucket_count must be at least two")
        self.bucket_count = bucket_count
        self.minimum_bucket_size = minimum_bucket_size
        self._buckets: tuple[CalibrationBucket, ...] = ()

    @property
    def buckets(self) -> tuple[CalibrationBucket, ...]:
        return self._buckets

    def fit(self, observations: Sequence[CalibrationObservation]) -> tuple[CalibrationBucket, ...]:
        width = ONE / Decimal(self.bucket_count)
        buckets: list[CalibrationBucket] = []
        for index in range(self.bucket_count):
            lower = width * Decimal(index)
            upper = ONE if index == self.bucket_count - 1 else width * Decimal(index + 1)
            selected = [
                obs
                for obs in observations
                if lower <= obs.raw_score <= upper
                and (index == self.bucket_count - 1 or obs.raw_score < upper)
            ]
            if not selected:
                continue
            predicted = sum((obs.raw_score for obs in selected), ZERO) / Decimal(len(selected))
            observed = Decimal(sum(obs.won for obs in selected)) / Decimal(len(selected))
            buckets.append(
                CalibrationBucket(
                    lower,
                    upper,
                    predicted,
                    observed,
                    len(selected),
                    abs(predicted - observed),
                )
            )
        self._buckets = tuple(buckets)
        return self._buckets

    def calibrate(self, raw_score: Decimal) -> Decimal | None:
        raw_score = min(ONE, max(ZERO, as_decimal(raw_score)))
        for bucket in self._buckets:
            if bucket.lower <= raw_score <= bucket.upper:
                return (
                    bucket.observed_win_rate
                    if bucket.sample_size >= self.minimum_bucket_size
                    else None
                )
        return None
