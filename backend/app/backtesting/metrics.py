from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtesting.models import EquityPoint, Trade
from app.core.decimal import ONE, ZERO, money, safe_ratio


@dataclass(frozen=True, slots=True)
class MilestoneStatus:
    amount: Decimal
    first_exceeded: datetime | None
    fell_below_after: bool


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    starting_equity: Decimal
    final_equity_before_operational_costs: Decimal
    final_equity: Decimal
    total_return: Decimal
    trading_return_before_operational_costs: Decimal
    trading_return_after_operational_costs: Decimal
    annualised_return: Decimal | None
    cagr: Decimal | None
    maximum_drawdown: Decimal
    drawdown_duration_seconds: int
    number_of_trades: int
    win_rate: Decimal
    average_winner: Decimal
    average_loser: Decimal
    payoff_ratio: Decimal
    expectancy: Decimal
    profit_factor: Decimal | None
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    calmar_ratio: Decimal | None
    longest_winning_streak: int
    longest_losing_streak: int
    gross_profit: Decimal
    gross_loss: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    financing_cost: Decimal
    commission: Decimal
    guaranteed_stop_premium: Decimal
    currency_conversion_cost: Decimal
    operational_costs: Decimal
    exposure_percentage: Decimal
    average_effective_leverage: Decimal
    maximum_effective_leverage: Decimal
    average_holding_seconds: Decimal
    performance_by_instrument: dict[str, Decimal]
    performance_by_strategy: dict[str, Decimal]
    performance_by_regime: dict[str, Decimal]
    monthly_returns: dict[str, Decimal]
    annual_returns: dict[str, Decimal]
    milestones: dict[str, MilestoneStatus]
    ruin_reached: bool
    ruin_timestamp: datetime | None
    lowest_equity: Decimal


def _ratio(value: float) -> Decimal | None:
    return None if not math.isfinite(value) else Decimal(str(value))


def _streaks(trades: Sequence[Trade]) -> tuple[int, int]:
    win_max = loss_max = win = loss = 0
    for trade in trades:
        if trade.net_pnl > ZERO:
            win += 1
            loss = 0
            win_max = max(win_max, win)
        elif trade.net_pnl < ZERO:
            loss += 1
            win = 0
            loss_max = max(loss_max, loss)
        else:
            win = loss = 0
    return win_max, loss_max


def _group_pnl(trades: Sequence[Trade], attribute: str) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for trade in trades:
        key = str(getattr(trade, attribute))
        result[key] = money(result.get(key, ZERO) + trade.net_pnl)
    return result


def _period_returns(points: Sequence[EquityPoint], annual: bool) -> dict[str, Decimal]:
    grouped: dict[str, list[EquityPoint]] = {}
    for point in points:
        key = point.timestamp.strftime("%Y" if annual else "%Y-%m")
        grouped.setdefault(key, []).append(point)
    result: dict[str, Decimal] = {}
    previous = points[0].equity if points else ZERO
    for key in sorted(grouped):
        end = grouped[key][-1].equity
        result[key] = ZERO if previous == ZERO else end / previous - ONE
        previous = end
    return result


def calculate_metrics(
    starting_equity: Decimal,
    trades: Sequence[Trade],
    equity_curve: Sequence[EquityPoint],
    *,
    operational_costs: Decimal = ZERO,
) -> BacktestMetrics:
    starting = money(starting_equity)
    operating_cost = money(operational_costs)
    if operating_cost < ZERO:
        raise ValueError("operational_costs cannot be negative")
    trading_final = money(equity_curve[-1].equity if equity_curve else starting)
    final = money(trading_final - operating_cost)
    return_before_operating_costs = safe_ratio(trading_final - starting, starting)
    return_after_operating_costs = safe_ratio(final - starting, starting)
    total_return = return_after_operating_costs

    # External operating costs are a separate final account deduction.  Add a
    # zero-duration terminal point for drawdown, period-return, milestone and
    # ruin calculations while preserving the pre-cost trading curve itself.
    analysis_curve = list(equity_curve)
    if operating_cost > ZERO and analysis_curve:
        last = analysis_curve[-1]
        peak = max(last.peak, last.equity)
        drawdown = ZERO if peak <= ZERO else (peak - final) / peak
        analysis_curve.append(EquityPoint(last.timestamp, final, peak, drawdown, last.exposure))
    winners = [trade.net_pnl for trade in trades if trade.net_pnl > ZERO]
    losers = [trade.net_pnl for trade in trades if trade.net_pnl < ZERO]
    gross_profit = money(sum(winners, ZERO))
    gross_loss = money(sum(losers, ZERO))
    average_winner = money(gross_profit / len(winners)) if winners else ZERO
    average_loser = money(gross_loss / len(losers)) if losers else ZERO
    win_rate = Decimal(len(winners)) / Decimal(len(trades)) if trades else ZERO
    expectancy = money(sum((t.net_pnl for t in trades), ZERO) / len(trades)) if trades else ZERO
    profit_factor = None if gross_loss == ZERO else gross_profit / abs(gross_loss)
    payoff = ZERO if average_loser == ZERO else average_winner / abs(average_loser)
    returns = [
        float(trade.net_pnl / trade.managed_equity_before)
        for trade in trades
        if trade.managed_equity_before > ZERO
    ]
    sharpe = sortino = None
    if len(returns) >= 2:
        average = sum(returns) / len(returns)
        variance = sum((value - average) ** 2 for value in returns) / (len(returns) - 1)
        deviation = math.sqrt(variance)
        sharpe = _ratio(average / deviation * math.sqrt(len(returns))) if deviation else None
        downside = [min(0.0, value) for value in returns]
        downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside))
        sortino = (
            _ratio(average / downside_deviation * math.sqrt(len(returns)))
            if downside_deviation
            else None
        )

    maximum_drawdown = max((point.drawdown for point in analysis_curve), default=ZERO)
    drawdown_start: datetime | None = None
    longest_drawdown = 0
    for point in analysis_curve:
        if point.drawdown > ZERO and drawdown_start is None:
            drawdown_start = point.timestamp
        elif point.drawdown == ZERO and drawdown_start is not None:
            longest_drawdown = max(
                longest_drawdown, int((point.timestamp - drawdown_start).total_seconds())
            )
            drawdown_start = None
    if drawdown_start and analysis_curve:
        longest_drawdown = max(
            longest_drawdown,
            int((analysis_curve[-1].timestamp - drawdown_start).total_seconds()),
        )
    elapsed_years = 0.0
    annualised = cagr = None
    if len(analysis_curve) >= 2:
        elapsed_years = (
            analysis_curve[-1].timestamp - analysis_curve[0].timestamp
        ).total_seconds() / 31557600
    if elapsed_years > 0 and final > ZERO and starting > ZERO:
        cagr_value = (float(final / starting) ** (1 / elapsed_years)) - 1
        cagr = _ratio(cagr_value)
        annualised = cagr
    calmar = None if cagr is None or maximum_drawdown == ZERO else cagr / maximum_drawdown
    win_streak, loss_streak = _streaks(trades)
    exposure = (
        Decimal(sum(point.exposure > ZERO for point in equity_curve)) / Decimal(len(equity_curve))
        if equity_curve
        else ZERO
    )
    leverage_values = [
        point.exposure / point.equity if point.equity > ZERO else ZERO for point in equity_curve
    ]
    average_leverage = (
        sum(leverage_values, ZERO) / Decimal(len(leverage_values)) if leverage_values else ZERO
    )
    milestones: dict[str, MilestoneStatus] = {}
    for amount in (Decimal("750"), Decimal("1000"), Decimal("2500"), Decimal("5000")):
        first_index = next(
            (index for index, point in enumerate(analysis_curve) if point.equity >= amount),
            None,
        )
        first_time = analysis_curve[first_index].timestamp if first_index is not None else None
        fell_below = bool(
            first_index is not None
            and any(point.equity < amount for point in analysis_curve[first_index + 1 :])
        )
        milestones[str(amount)] = MilestoneStatus(amount, first_time, fell_below)
    ruin_point = next((point for point in analysis_curve if point.equity <= ZERO), None)
    ruin_reached = ruin_point is not None or final <= ZERO
    return BacktestMetrics(
        starting_equity=starting,
        final_equity_before_operational_costs=trading_final,
        final_equity=final,
        total_return=total_return,
        trading_return_before_operational_costs=return_before_operating_costs,
        trading_return_after_operational_costs=return_after_operating_costs,
        annualised_return=annualised,
        cagr=cagr,
        maximum_drawdown=maximum_drawdown,
        drawdown_duration_seconds=longest_drawdown,
        number_of_trades=len(trades),
        win_rate=win_rate,
        average_winner=average_winner,
        average_loser=average_loser,
        payoff_ratio=payoff,
        expectancy=expectancy,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        longest_winning_streak=win_streak,
        longest_losing_streak=loss_streak,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        spread_cost=money(sum((trade.spread_cost for trade in trades), ZERO)),
        slippage_cost=money(sum((trade.slippage_cost for trade in trades), ZERO)),
        financing_cost=money(sum((trade.financing_cost for trade in trades), ZERO)),
        commission=money(sum((trade.commission for trade in trades), ZERO)),
        guaranteed_stop_premium=money(
            sum((trade.guaranteed_stop_premium for trade in trades), ZERO)
        ),
        currency_conversion_cost=money(
            sum((trade.currency_conversion_cost for trade in trades), ZERO)
        ),
        operational_costs=operating_cost,
        exposure_percentage=exposure,
        average_effective_leverage=average_leverage,
        maximum_effective_leverage=max(leverage_values, default=ZERO),
        average_holding_seconds=(
            Decimal(sum(trade.holding_seconds for trade in trades)) / Decimal(len(trades))
            if trades
            else ZERO
        ),
        performance_by_instrument=_group_pnl(trades, "instrument_id"),
        performance_by_strategy=_group_pnl(trades, "strategy_version_id"),
        performance_by_regime=_group_pnl(trades, "regime"),
        monthly_returns=_period_returns(analysis_curve, False),
        annual_returns=_period_returns(analysis_curve, True),
        milestones=milestones,
        ruin_reached=ruin_reached,
        ruin_timestamp=ruin_point.timestamp if ruin_point else None,
        lowest_equity=min((point.equity for point in analysis_curve), default=final),
    )
