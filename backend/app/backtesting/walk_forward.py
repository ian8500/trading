from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from app.backtesting.models import Bar

P = TypeVar("P")
R = TypeVar("R")


class TrainingWindowMode(StrEnum):
    ROLLING = "ROLLING"
    EXPANDING = "EXPANDING"


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    training_bars: int
    test_bars: int
    step_bars: int
    mode: TrainingWindowMode = TrainingWindowMode.ROLLING

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", TrainingWindowMode(self.mode))
        if min(self.training_bars, self.test_bars, self.step_bars) <= 0:
            raise ValueError("walk-forward window sizes must be positive")


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    number: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int


@dataclass(frozen=True, slots=True)
class WalkForwardFold[P, R]:
    window: WalkForwardWindow
    parameters: P
    in_sample: R
    out_of_sample: R
    degradation: float | None


@dataclass(frozen=True, slots=True)
class WalkForwardResult[P, R]:
    folds: tuple[WalkForwardFold[P, R], ...]
    parameter_stability: float
    mean_degradation: float | None


class WalkForwardSplitter:
    def __init__(self, config: WalkForwardConfig) -> None:
        self.config = config

    def split(self, bars: Sequence[Bar]) -> tuple[WalkForwardWindow, ...]:
        cfg = self.config
        windows: list[WalkForwardWindow] = []
        train_end = cfg.training_bars
        number = 0
        while train_end + cfg.test_bars <= len(bars):
            train_start = (
                0 if cfg.mode is TrainingWindowMode.EXPANDING else train_end - cfg.training_bars
            )
            test_start = train_end
            test_end = test_start + cfg.test_bars
            windows.append(WalkForwardWindow(number, train_start, train_end, test_start, test_end))
            number += 1
            train_end += cfg.step_bars
        return tuple(windows)


class WalkForwardAnalyzer[P, R]:
    """Select on training data and evaluate once on the following test slice."""

    def __init__(self, config: WalkForwardConfig) -> None:
        self.config = config

    def run(
        self,
        bars: Sequence[Bar],
        select_parameters: Callable[[Sequence[Bar]], P],
        evaluate: Callable[[Sequence[Bar], P], R],
        objective: Callable[[R], float],
    ) -> WalkForwardResult[P, R]:
        folds: list[WalkForwardFold[P, R]] = []
        for window in WalkForwardSplitter(self.config).split(bars):
            training = bars[window.train_start : window.train_end]
            testing = bars[window.test_start : window.test_end]
            if training[-1].timestamp >= testing[0].timestamp:
                raise RuntimeError("walk-forward leakage: test data is not strictly after training")
            parameters = select_parameters(training)
            in_sample = evaluate(training, parameters)
            out_of_sample = evaluate(testing, parameters)
            in_score = objective(in_sample)
            out_score = objective(out_of_sample)
            degradation = None if in_score == 0 else (in_score - out_score) / abs(in_score)
            folds.append(
                WalkForwardFold(
                    window,
                    parameters,
                    in_sample,
                    out_of_sample,
                    degradation,
                )
            )
        parameter_stability = self._stability([fold.parameters for fold in folds])
        degradation_values = [fold.degradation for fold in folds if fold.degradation is not None]
        mean_degradation = (
            sum(degradation_values) / len(degradation_values) if degradation_values else None
        )
        return WalkForwardResult(tuple(folds), parameter_stability, mean_degradation)

    @staticmethod
    def _stability(parameters: list[P]) -> float:
        if not parameters:
            return 0.0
        representations = [repr(value) for value in parameters]
        most_common = max(representations.count(value) for value in set(representations))
        return most_common / len(representations)
