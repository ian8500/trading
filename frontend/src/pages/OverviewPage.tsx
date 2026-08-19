import { useMemo, useState } from "react";
import { TimeSeriesChart } from "../charts/TimeSeriesChart";
import { CircularProgress, ExposureBars } from "../charts/VisualCharts";
import { OpportunityTable, PositionTable, TradeTable } from "../components/DataTables";
import { OpportunityDetail, TradeDetail } from "../components/Details";
import { Icon } from "../components/Icon";
import { DataTimestamp, InlineNotice, MetricCard, PageHeader, Panel, Segmented, SourceBadge, StatusPill } from "../components/Primitives";
import { demoDashboard } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import type { Opportunity, Trade } from "../types/domain";
import { formatDateTime, formatMoney, formatPercent, humanize, pnlTone } from "../utils/format";

export function OverviewPage() {
  const resource = useApiResource("/dashboard/overview", demoDashboard);
  const data = resource.data;
  const [chart, setChart] = useState<"Equity" | "Drawdown" | "Exposure">("Equity");
  const [selectedOpportunity, setSelectedOpportunity] = useState<Opportunity | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const targetProgress = ((data.managedEquity - data.startingCapital) / (data.target - data.startingCapital)) * 100;
  const healthyServices = data.services.filter((service) => service.status === "healthy").length;
  const chartConfig = useMemo(() => {
    if (chart === "Drawdown") return { data: data.drawdownCurve, color: "#ff6b7a", label: "Drawdown", formatter: (value: number) => `${value.toFixed(1)}%`, zeroLine: true };
    if (chart === "Exposure") return { data: data.exposureCurve, color: "#9a8cff", label: "Portfolio exposure", formatter: (value: number) => `${value.toFixed(0)}%`, zeroLine: false };
    return { data: data.equityCurve, color: "#47e6a4", label: "Managed equity", formatter: (value: number) => formatMoney(value, "GBP", 0), zeroLine: false };
  }, [chart, data]);

  return (
    <>
      <PageHeader
        eyebrow="Command centre"
        title="Portfolio overview"
        description="Managed-capital performance, ranked opportunities, and system safety at a glance."
        actions={<><DataTimestamp value={data.asOf} /><SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} /></>}
      />
      {resource.source === "demo" && <InlineNotice tone="warning" title="Offline interface demonstration">Values on this screen are synthetic UI demonstration data, not a genuine backtest or broker account.</InlineNotice>}

      <div className="metric-grid metric-grid-8">
        <MetricCard label="Mode" value={humanize(data.mode)} detail="Completed-bar research" tone="info" icon={<Icon name="clock" />} />
        <MetricCard label="Starting capital" value={formatMoney(data.startingCapital)} detail="Internal managed ledger" />
        <MetricCard label="Managed equity" value={formatMoney(data.managedEquity)} detail={`${formatPercent(data.returnPercent, 2, true)} all-time`} tone="positive" />
        <MetricCard label="Broker Demo balance" value={formatMoney(data.brokerDemoBalance)} detail="Informational only" />
        <MetricCard label="Target" value={formatMoney(data.target, "GBP", 0)} detail={`${Math.max(0, targetProgress).toFixed(1)}% of growth path`} progress={targetProgress} />
        <MetricCard label="Maximum drawdown" value={formatPercent(data.maxDrawdown)} detail="Peak-to-trough" tone={data.maxDrawdown > 12 ? "negative" : "warning"} />
        <MetricCard label="Open risk" value={formatPercent(data.openRisk)} detail={`${data.positions.length} active positions`} tone="warning" />
        <MetricCard label="Circuit breakers" value={data.circuitBreakers} detail="New orders fail closed" tone={data.circuitBreakers === "HEALTHY" ? "positive" : "negative"} icon={<Icon name="risk" />} />
      </div>

      <div className="layout-2-1 overview-performance">
        <Panel title="Managed capital performance" eyebrow="£500 ledger · compounded" actions={<Segmented value={chart} options={["Equity", "Drawdown", "Exposure"] as const} onChange={setChart} label="Performance chart" />}>
          <TimeSeriesChart data={chartConfig.data} lines={[{ key: "value", label: chartConfig.label, color: chartConfig.color }]} valueFormatter={chartConfig.formatter} ariaLabel={`${chart} chart`} zeroLine={chartConfig.zeroLine} />
          <div className="chart-footnote"><span><i className="legend-dot green" />Current {formatMoney(data.managedEquity)}</span><span>Peak-to-trough {formatPercent(data.maxDrawdown)}</span><span>Compounding on</span><span>Costs realistic</span></div>
        </Panel>
        <Panel title="Target journey" eyebrow="Capital milestones">
          <div className="target-progress-block">
            <CircularProgress value={Math.max(2, targetProgress)} label={`${targetProgress.toFixed(1)}%`} detail="growth path" />
            <div className="milestone-list">
              {[750, 1000, 2500, 5000].map((milestone) => <div key={milestone} className={data.managedEquity >= milestone ? "reached" : ""}><span>{data.managedEquity >= milestone ? <Icon name="check" size={14} /> : <i />}{formatMoney(milestone, "GBP", 0)}</span><strong>{data.managedEquity >= milestone ? "Reached" : `${formatMoney(milestone - data.managedEquity, "GBP", 0)} to go`}</strong></div>)}
            </div>
          </div>
          <div className="capital-rule"><Icon name="lock" /><p><strong>Sizing base: {formatMoney(data.managedEquity)}</strong><span>Every next trade uses current managed equity. Broker Demo funds never affect size.</span></p></div>
        </Panel>
      </div>

      <Panel title="Opportunity leaderboard" eyebrow="Comparable expected geometric growth" actions={<a className="text-link" href="/opportunities">View all <Icon name="arrow" size={15} /></a>} flush>
        <OpportunityTable opportunities={data.opportunities.slice(0, 5)} compact onSelect={setSelectedOpportunity} />
      </Panel>

      <div className="layout-2-1">
        <Panel title={`Open positions · ${data.positions.length}`} eyebrow="Chronological portfolio state" flush>
          <PositionTable positions={data.positions} />
        </Panel>
        <Panel title="Exposure map" eyebrow="Correlation-aware risk">
          <ExposureBars data={[
            { label: "USD short", value: 2.1, limit: 4, color: "#47e6a4" },
            { label: "US equity beta", value: 2.4, limit: 4, color: "#9a8cff" },
            { label: "GBP long", value: 1.8, limit: 3.5, color: "#45baf5" },
            { label: "Precious metals", value: 0, limit: 3, color: "#f4be5b" },
          ]} />
          <p className="panel-caption">Vertical markers show configured cluster limits. New overlapping positions may be reduced or rejected.</p>
        </Panel>
      </div>

      <div className="layout-2-1">
        <Panel title="Recent trades" eyebrow="Net of trading costs" flush>
          <TradeTable trades={data.recentTrades.slice(0, 4)} onSelect={setSelectedTrade} />
        </Panel>
        <Panel title="Strategy health" eyebrow="Rolling evidence">
          <div className="health-list">{data.strategyHealth.map((strategy) => <div className="health-row" key={strategy.id}><div><strong>{strategy.name}</strong><span>{strategy.sampleSize} observations · PF {strategy.profitFactor.toFixed(2)}</span></div><div><span className={`text-${pnlTone(strategy.expectancy)}`}>{formatMoney(strategy.expectancy)} exp.</span><StatusPill tone={strategy.state === "NORMAL" ? "positive" : strategy.state === "REDUCED_RISK" ? "warning" : "negative"}>{humanize(strategy.state)}</StatusPill></div></div>)}</div>
        </Panel>
      </div>

      <div className="layout-1-1">
        <Panel title="Upcoming risk events" eyebrow="Europe/London">
          <div className="event-list compact">{data.events.slice(0, 3).map((event) => <div key={event.id}><time>{formatDateTime(event.scheduledAt, false)}</time><span className={`importance importance-${event.importance.toLowerCase()}`}>{event.importance}</span><div><strong>{event.currency} · {event.name}</strong><p>{event.summary}</p></div></div>)}</div>
        </Panel>
        <Panel title="System confidence" eyebrow="Fail-closed services">
          <div className="system-summary"><strong>{healthyServices}/{data.services.length}</strong><span>services healthy</span><StatusPill tone={data.circuitBreakers === "HEALTHY" ? "positive" : "negative"}>{data.circuitBreakers}</StatusPill></div>
          <div className="service-mini-grid">{data.services.slice(0, 8).map((service) => <div key={service.id}><i className={`service-dot ${service.status}`} /><span>{service.name}</span><small>{service.message}</small></div>)}</div>
        </Panel>
      </div>

      <OpportunityDetail opportunity={selectedOpportunity} onClose={() => setSelectedOpportunity(null)} />
      <TradeDetail trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
    </>
  );
}
