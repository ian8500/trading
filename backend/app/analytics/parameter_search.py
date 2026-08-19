from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Objective(StrEnum):
    SHARPE = "SHARPE"
    SORTINO = "SORTINO"
    CALMAR = "CALMAR"
    EXPECTED_LOG_GROWTH = "EXPECTED_LOG_GROWTH"
    RETURN_DRAWDOWN_PENALTY = "RETURN_DRAWDOWN_PENALTY"
    PROFIT_FACTOR_MIN_TRADES = "PROFIT_FACTOR_MIN_TRADES"


@dataclass(frozen=True, slots=True)
class ParameterEvaluation:
    parameters: dict[str, Any]
    metrics: dict[str, float]
    objective_value: float
    isolated_peak: bool = False


@dataclass(frozen=True, slots=True)
class ParameterSearchResult:
    objective: Objective
    evaluations: tuple[ParameterEvaluation, ...]
    best: ParameterEvaluation


class ParameterSearch:
    def __init__(
        self,
        objective: Objective = Objective.RETURN_DRAWDOWN_PENALTY,
        *,
        minimum_trades: int = 20,
        drawdown_penalty: float = 1.0,
    ) -> None:
        self.objective = Objective(objective)
        self.minimum_trades = minimum_trades
        self.drawdown_penalty = drawdown_penalty

    def run(
        self,
        parameter_grid: Mapping[str, Sequence[Any]],
        evaluate: Callable[[dict[str, Any]], Mapping[str, float]],
    ) -> ParameterSearchResult:
        if not parameter_grid:
            raise ValueError("parameter_grid cannot be empty")
        names = tuple(sorted(parameter_grid))
        combinations = itertools.product(*(parameter_grid[name] for name in names))
        records: list[ParameterEvaluation] = []
        for combination in combinations:
            parameters = dict(zip(names, combination, strict=False))
            metrics = dict(evaluate(parameters))
            objective_value = self._objective(metrics)
            records.append(ParameterEvaluation(parameters, metrics, objective_value))
        if not records:
            raise ValueError("parameter_grid contains no combinations")
        records = self._flag_isolated(records, parameter_grid)
        best = max(records, key=lambda record: (record.objective_value, repr(record.parameters)))
        return ParameterSearchResult(
            self.objective,
            tuple(sorted(records, key=lambda record: record.objective_value, reverse=True)),
            best,
        )

    def _objective(self, metrics: Mapping[str, float]) -> float:
        key = {
            Objective.SHARPE: "sharpe",
            Objective.SORTINO: "sortino",
            Objective.CALMAR: "calmar",
            Objective.EXPECTED_LOG_GROWTH: "expected_log_growth",
        }.get(self.objective)
        if key:
            return float(metrics.get(key, float("-inf")))
        if self.objective is Objective.RETURN_DRAWDOWN_PENALTY:
            return float(metrics.get("total_return", 0)) - self.drawdown_penalty * float(
                metrics.get("maximum_drawdown", 0)
            )
        if int(metrics.get("number_of_trades", 0)) < self.minimum_trades:
            return float("-inf")
        return float(metrics.get("profit_factor", float("-inf")))

    @staticmethod
    def _flag_isolated(
        records: list[ParameterEvaluation],
        grid: Mapping[str, Sequence[Any]],
    ) -> list[ParameterEvaluation]:
        lookup = {tuple(sorted(record.parameters.items())): record for record in records}
        flagged: list[ParameterEvaluation] = []
        for record in records:
            neighbours: list[ParameterEvaluation] = []
            for name, values in grid.items():
                values = list(values)
                try:
                    index = values.index(record.parameters[name])
                except ValueError:
                    continue
                for adjacent in (index - 1, index + 1):
                    if 0 <= adjacent < len(values):
                        params = dict(record.parameters)
                        params[name] = values[adjacent]
                        neighbour = lookup.get(tuple(sorted(params.items())))
                        if neighbour:
                            neighbours.append(neighbour)
            finite = [
                item.objective_value for item in neighbours if math.isfinite(item.objective_value)
            ]
            isolated = bool(
                finite and record.objective_value > 0 and record.objective_value > max(finite) * 1.5
            )
            flagged.append(
                ParameterEvaluation(
                    record.parameters, record.metrics, record.objective_value, isolated
                )
            )
        return flagged
