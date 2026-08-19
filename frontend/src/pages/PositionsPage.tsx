import { TimeSeriesChart } from "../charts/TimeSeriesChart";
import { ExposureBars } from "../charts/VisualCharts";
import { PositionTable, TradeTable } from "../components/DataTables";
import { TradeDetail } from "../components/Details";
import { InlineNotice, MetricCard, PageHeader, Panel, SourceBadge, StatusPill } from "../components/Primitives";
import { demoDashboard } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import { useState } from "react";
import type { Trade } from "../types/domain";
import { formatMoney, formatPercent, pnlTone } from "../utils/format";

export function PositionsPage() {
  const resource = useApiResource("/positions?include_closed=true", demoDashboard);
  const data = resource.data;
  const [trade, setTrade] = useState<Trade | null>(null);
  const unrealised = data.positions.reduce((sum, item) => sum + item.unrealisedPnl, 0);
  const margin = data.positions.reduce((sum, item) => sum + item.marginUsed, 0);
  const plannedRisk = data.positions.reduce((sum, item) => sum + item.plannedRisk, 0);

  return (
    <>
      <PageHeader title="Positions & ledger" eyebrow="Managed-capital portfolio" description="Chronological position state, protection levels, costs, and compounding evidence." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <InlineNotice tone="info" title="Broker funds are informational">All planned risk and position sizing shown here are derived from the internal {formatMoney(data.managedEquity)} managed-equity ledger.</InlineNotice>
      <div className="metric-grid metric-grid-6">
        <MetricCard label="Open positions" value={data.positions.length} detail="No pyramiding" />
        <MetricCard label="Managed equity" value={formatMoney(data.managedEquity)} detail="Authoritative sizing base" tone="positive" />
        <MetricCard label="Unrealised P&L" value={formatMoney(unrealised)} detail={formatPercent((unrealised / data.managedEquity) * 100, 2, true)} tone={pnlTone(unrealised)} />
        <MetricCard label="Planned open risk" value={formatMoney(plannedRisk)} detail={formatPercent(plannedRisk / data.managedEquity * 100)} tone="warning" />
        <MetricCard label="Margin used" value={formatMoney(margin)} detail={formatPercent(margin / data.managedEquity * 100)} />
        <MetricCard label="Effective leverage" value="0.46×" detail="Hard cap 2.00×" />
      </div>
      <Panel title="Open positions" eyebrow="Stops are mandatory" flush><PositionTable positions={data.positions} /></Panel>
      <div className="layout-2-1">
        <Panel title="Portfolio exposure" eyebrow="Percentage of managed equity">
          <TimeSeriesChart data={data.exposureCurve.slice(-60)} lines={[{ key: "value", label: "Gross exposure", color: "#9a8cff" }]} valueFormatter={(value) => `${value.toFixed(0)}%`} ariaLabel="Portfolio exposure over time" />
        </Panel>
        <Panel title="Correlation clusters" eyebrow="Aggregate directional risk">
          <ExposureBars data={[{ label: "GBP long", value: 1.82, limit: 3.5 }, { label: "US equity beta", value: 2.41, limit: 4 }, { label: "USD short", value: 2.08, limit: 4 }, { label: "Gold / real rates", value: 0, limit: 3 }]} />
          <div className="risk-legend"><StatusPill tone="positive">Inside limits</StatusPill><span>Limits apply before every order and after correlation netting.</span></div>
        </Panel>
      </div>
      <Panel title="Closed trade ledger" eyebrow="Click any row for full audit detail" flush><TradeTable trades={data.recentTrades} onSelect={setTrade} /></Panel>
      <div className="layout-1-1">
        <Panel title="Compounding proof" eyebrow="Recent managed-equity transitions">
          <div className="ledger-transitions">{data.recentTrades.slice(0, 4).map((item) => <div key={item.id}><span>{formatMoney(item.managedEquityBefore)}</span><i className={item.netPnl >= 0 ? "gain" : "loss"}>{item.netPnl >= 0 ? "+" : ""}{formatMoney(item.netPnl)}</i><strong>{formatMoney(item.managedEquityAfter)}</strong></div>)}</div>
        </Panel>
        <Panel title="Protection policy" eyebrow="Non-negotiable controls">
          <ul className="policy-list"><li><StatusPill tone="positive">ENFORCED</StatusPill> Every trade receives a stop before broker submission.</li><li><StatusPill tone="positive">ENFORCED</StatusPill> Stops cannot be widened solely to avoid a loss.</li><li><StatusPill tone="positive">ENFORCED</StatusPill> Ambiguous stop/target bars use conservative fills.</li><li><StatusPill tone="positive">ENFORCED</StatusPill> Equity exhaustion halts the simulation.</li></ul>
        </Panel>
      </div>
      <TradeDetail trade={trade} onClose={() => setTrade(null)} />
    </>
  );
}
