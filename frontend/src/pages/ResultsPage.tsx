import { TimeSeriesChart } from "../charts/TimeSeriesChart";
import { Icon } from "../components/Icon";
import { DataTimestamp, InlineNotice, MetricCard, PageHeader, Panel, SourceBadge } from "../components/Primitives";
import { demoDashboard } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import { formatDateTime, formatMoney, formatPercent, pnlTone } from "../utils/format";

export function ResultsPage() {
  const resource = useApiResource("/dashboard/overview", demoDashboard);
  const data = resource.data;
  return (
    <>
      <PageHeader
        eyebrow="Latest stored research"
        title="Results"
        description="A short view of the latest historical simulation. This is not a live account or current market feed."
        actions={<><DataTimestamp value={data.asOf} /><SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} /></>}
      />
      <InlineNotice tone="info" title="Historical evidence only">Autopilot uses the frozen research protocol for its decision. These latest-run figures are context, not permission to trade.</InlineNotice>
      <div className="metric-grid metric-grid-4 simple-results-metrics">
        <MetricCard label="Starting capital" value={formatMoney(data.startingCapital)} detail="Managed research ledger" />
        <MetricCard label="Final equity" value={formatMoney(data.managedEquity)} detail={formatPercent(data.returnPercent, 2, true)} tone={pnlTone(data.returnPercent)} />
        <MetricCard label="Maximum drawdown" value={formatPercent(data.maxDrawdown, 2)} detail="Peak to trough" tone="warning" />
        <MetricCard label="Recent records loaded" value={data.recentTrades.length} detail="Latest stored run" />
      </div>
      <Panel title="Equity path" eyebrow="After modeled costs">
        <TimeSeriesChart data={data.equityCurve} lines={[{ key: "value", label: "Managed equity", color: "#47e6a4" }]} valueFormatter={(value) => formatMoney(value, "GBP", 0)} ariaLabel="Latest historical equity path" />
      </Panel>
      <Panel title="Recent outcomes" eyebrow="Newest first">
        <div className="simple-activity-list">{data.recentTrades.slice(0, 5).map((trade) => (
          <div key={trade.id}>
            <span className={`activity-dot ${trade.netPnl >= 0 ? "positive" : "negative"}`} />
            <div><strong>{trade.instrument} · {trade.direction}</strong><span>{trade.exitReason} · {formatDateTime(trade.closedAt)}</span></div>
            <strong className={`text-${pnlTone(trade.netPnl)}`}>{formatMoney(trade.netPnl)}</strong>
          </div>
        ))}</div>
        {!data.recentTrades.length && <div className="empty-state"><Icon name="clock" /><strong>No completed trades</strong></div>}
      </Panel>
      {resource.source === "demo" && (
        <InlineNotice tone="warning" title="Demonstration fallback">
          These figures are synthetic placeholders because stored backend results are unavailable.
        </InlineNotice>
      )}
    </>
  );
}
