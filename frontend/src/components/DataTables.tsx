import type { Opportunity, Position, Trade } from "../types/domain";
import { formatDateTime, formatMoney, formatPercent, formatPrice, humanize, pnlTone } from "../utils/format";
import { Icon } from "./Icon";
import { StatusPill } from "./Primitives";

export function OpportunityTable({ opportunities, onSelect, compact = false }: { opportunities: Opportunity[]; onSelect: (opportunity: Opportunity) => void; compact?: boolean }) {
  return (
    <div className="table-scroll">
      <table className="data-table opportunity-table">
        <thead><tr><th>#</th><th>Instrument</th><th>Direction</th><th>Strategy</th><th>Regime</th><th className="number">Score</th><th>Status</th><th aria-label="Open" /></tr></thead>
        <tbody>{opportunities.map((opportunity, index) => (
          <tr key={opportunity.id} tabIndex={0} onClick={() => onSelect(opportunity)} onKeyDown={(event) => { if (event.key === "Enter") onSelect(opportunity); }}>
            <td className="rank">{index + 1}</td>
            <td><strong>{opportunity.instrument}</strong>{!compact && <small>{opportunity.marketFamily} · {opportunity.expectedHorizon}</small>}</td>
            <td><StatusPill tone={opportunity.direction === "LONG" ? "positive" : "purple"} dot={false}>{opportunity.direction}</StatusPill></td>
            <td>{opportunity.strategy}{!compact && <small>v{opportunity.strategyVersion}</small>}</td>
            <td>{humanize(opportunity.regime)}</td>
            <td className="number"><span className={`score-number ${opportunity.score >= 68 ? "high" : ""}`}>{opportunity.score.toFixed(1)}</span></td>
            <td><StatusPill tone={opportunity.status === "ELIGIBLE" ? "positive" : opportunity.status === "REJECTED" ? "negative" : "warning"}>{humanize(opportunity.status)}</StatusPill></td>
            <td><button className="row-arrow" type="button" aria-label={`Open ${opportunity.instrument} opportunity`}><Icon name="chevron" /></button></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function PositionTable({ positions }: { positions: Position[] }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr><th>Instrument</th><th>Direction</th><th>Strategy</th><th>Entry</th><th>Current</th><th>Stop</th><th>Target</th><th className="number">Risk</th><th className="number">Unrealised</th><th>Source</th></tr></thead>
        <tbody>{positions.map((position) => <tr key={position.id}>
          <td><strong>{position.instrument}</strong><small>{formatDateTime(position.openedAt)}</small></td>
          <td><StatusPill tone={position.direction === "LONG" ? "positive" : "purple"} dot={false}>{position.direction}</StatusPill></td>
          <td>{position.strategy}<small>{humanize(position.regime)}</small></td>
          <td>{formatPrice(position.entryPrice)}</td><td>{formatPrice(position.currentPrice)}</td><td className="text-negative">{formatPrice(position.stopPrice)}</td><td className="text-positive">{formatPrice(position.targetPrice)}</td>
          <td className="number">{formatMoney(position.plannedRisk)}<small>{formatPercent(position.marginUsed / 551.1 * 100, 1)} margin</small></td>
          <td className={`number text-${pnlTone(position.unrealisedPnl)}`}><strong>{formatMoney(position.unrealisedPnl)}</strong><small>{formatPercent(position.unrealisedPercent, 2, true)}</small></td>
          <td><StatusPill tone="info">{humanize(position.source)}</StatusPill></td>
        </tr>)}</tbody>
      </table>
    </div>
  );
}

export function TradeTable({ trades, onSelect }: { trades: Trade[]; onSelect: (trade: Trade) => void }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr><th>Closed</th><th>Instrument</th><th>Direction</th><th>Strategy</th><th>Entry → exit</th><th>Exit reason</th><th className="number">Costs</th><th className="number">Net P&amp;L</th><th aria-label="Open" /></tr></thead>
        <tbody>{trades.map((trade) => {
          const costs = Object.values(trade.costs).reduce((sum, value) => sum + value, 0);
          return <tr key={trade.id} tabIndex={0} onClick={() => onSelect(trade)} onKeyDown={(event) => { if (event.key === "Enter") onSelect(trade); }}>
            <td>{formatDateTime(trade.closedAt)}</td><td><strong>{trade.instrument}</strong><small>{humanize(trade.regime)}</small></td>
            <td><StatusPill tone={trade.direction === "LONG" ? "positive" : "purple"} dot={false}>{trade.direction}</StatusPill></td>
            <td>{trade.strategy}<small>v{trade.strategyVersion}</small></td><td>{formatPrice(trade.entryPrice)} → {formatPrice(trade.exitPrice)}</td><td>{trade.exitReason}</td><td className="number">{formatMoney(costs)}</td>
            <td className={`number text-${pnlTone(trade.netPnl)}`}><strong>{formatMoney(trade.netPnl)}</strong></td><td><button type="button" className="row-arrow" aria-label={`Open ${trade.instrument} trade`}><Icon name="chevron" /></button></td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  );
}
