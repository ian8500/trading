import { useEffect, useMemo, useState } from "react";
import { TimeSeriesChart } from "../charts/TimeSeriesChart";
import { MonteCarloDistribution, ReturnHeatmap } from "../charts/VisualCharts";
import { OpportunityTable, TradeTable } from "../components/DataTables";
import { OpportunityDetail, TradeDetail } from "../components/Details";
import { Icon } from "../components/Icon";
import { InlineNotice, MetricCard, PageHeader, Panel, ProgressBar, Segmented, SourceBadge, StatusPill, Toggle } from "../components/Primitives";
import { SecureAction } from "../components/SecureAction";
import { downloadCsv, downloadJson } from "../api/client";
import { demoBacktests } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import type { BacktestRequest, BacktestResult, BreakdownRow, ChartMarker, Opportunity, Trade } from "../types/domain";
import { formatDateTime, formatMoney, formatPercent, humanize, pnlTone } from "../utils/format";

const instruments = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/GBP", "FTSE 100", "S&P 500", "NASDAQ 100", "DAX", "Gold"];
const strategies = ["Quant Baseline", "Quant Aggressive", "Regime Ensemble"];

export function BacktestsPage() {
  const resource = useApiResource("/backtests?limit=20", demoBacktests);
  const [runs, setRuns] = useState<BacktestResult[]>(resource.data);
  const [activeId, setActiveId] = useState(demoBacktests[0].id);
  const [comparisonIds, setComparisonIds] = useState<string[]>(demoBacktests.map((item) => item.id));
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const [selectedOpportunity, setSelectedOpportunity] = useState<Opportunity | null>(null);
  const [chartMode, setChartMode] = useState<"Equity" | "Drawdown" | "Exposure">("Equity");
  const [breakdown, setBreakdown] = useState<"Instrument" | "Regime" | "Strategy">("Instrument");
  const [resultTab, setResultTab] = useState<"Trades" | "Rejected">("Trades");
  const [jobMessage, setJobMessage] = useState<{ tone: "positive" | "negative" | "warning"; text: string } | null>(null);
  const [form, setForm] = useState<BacktestRequest>({
    dateFrom: "2018-01-01",
    dateTo: "2026-07-31",
    startingCapital: 500,
    instruments: ["GBP/USD", "EUR/USD", "FTSE 100", "Gold"],
    strategies: ["Regime Ensemble"],
    riskProfile: "Standard",
    costModel: "REALISTIC",
    resolution: "1d",
    compounding: true,
    riskTaper: false,
  });

  useEffect(() => setRuns(resource.data), [resource.data]);
  const active = runs.find((item) => item.id === activeId) ?? runs[0] ?? demoBacktests[0];
  const compared = runs.filter((item) => comparisonIds.includes(item.id));

  const toggleList = (key: "instruments" | "strategies", value: string) => {
    setForm((current) => ({
      ...current,
      [key]: current[key].includes(value) ? current[key].filter((item) => item !== value) : [...current[key], value],
    }));
  };

  const acceptCompletedBacktest = (completed: BacktestResult) => {
    const nextRuns = [
      completed,
      ...(resource.source === "api" ? runs.filter((run) => run.id !== completed.id) : []),
    ];
    resource.acceptApiData(nextRuns);
    setRuns(nextRuns);
    setActiveId(completed.id);
    setComparisonIds((current) => [
      completed.id,
      ...current.filter((id) => id !== completed.id && nextRuns.some((run) => run.id === id)),
    ]);
    setSelectedTrade(null);
    setSelectedOpportunity(null);
    setJobMessage({ tone: "positive", text: "Backtest completed; displaying the exact result returned by the backend." });
  };

  const markers = useMemo<ChartMarker[]>(() => active.trades.map((trade) => {
    const closeTime = new Date(trade.closedAt).getTime();
    const nearest = active.equityCurve.reduce((best, point) => Math.abs(new Date(point.timestamp).getTime() - closeTime) < Math.abs(new Date(best.timestamp).getTime() - closeTime) ? point : best, active.equityCurve[0]);
    return { id: trade.id, timestamp: nearest?.timestamp ?? trade.closedAt, value: nearest?.value ?? active.metrics.finalEquity, direction: trade.direction, label: `${trade.instrument} ${trade.netPnl >= 0 ? "winner" : "loser"}`, positive: trade.netPnl >= 0 };
  }), [active]);
  const chart = chartMode === "Equity"
    ? { data: active.equityCurve, label: "Equity", color: "#47e6a4", formatter: (value: number) => formatMoney(value, "GBP", 0) }
    : chartMode === "Drawdown"
      ? { data: active.drawdownCurve, label: "Drawdown", color: "#ff6b7a", formatter: (value: number) => `${value.toFixed(1)}%` }
      : { data: active.exposureCurve, label: "Exposure", color: "#9a8cff", formatter: (value: number) => `${value.toFixed(0)}%` };
  const breakdownRows: BreakdownRow[] = breakdown === "Instrument" ? active.instrumentBreakdown : breakdown === "Regime" ? active.regimeBreakdown : active.strategyBreakdown;

  return (
    <>
      <PageHeader title="Backtest laboratory" eyebrow="Event-driven research" description="Run reproducible, costed simulations with completed-bar timing, compounding, and conservative intrabar fills." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <InlineNotice tone="warning" title="Official reports use conservative fills">When a bar touches both stop and target, the default policy takes the adverse outcome. Zero-cost results cannot approve a strategy.</InlineNotice>
      <Panel title="Research configuration" eyebrow="New backtest">
        <div className="backtest-form">
          <div className="form-grid form-grid-4">
            <label><span>Start date</span><input type="date" value={form.dateFrom} onChange={(event) => setForm({ ...form, dateFrom: event.target.value })} /></label>
            <label><span>End date</span><input type="date" value={form.dateTo} onChange={(event) => setForm({ ...form, dateTo: event.target.value })} /></label>
            <label><span>Starting managed capital</span><div className="input-prefix"><span>£</span><input type="number" min="100" step="50" value={form.startingCapital} onChange={(event) => setForm({ ...form, startingCapital: Number(event.target.value) })} /></div></label>
            <label><span>Bar resolution</span><select value={form.resolution} onChange={(event) => setForm({ ...form, resolution: event.target.value })}><option value="1h">1 hour</option><option value="1d">1 day</option></select></label>
            <label><span>Risk profile</span><select value={form.riskProfile} onChange={(event) => setForm({ ...form, riskProfile: event.target.value })}><option>Conservative</option><option>Standard</option><option>Aggressive</option><option>Experimental</option></select></label>
            <label><span>Cost model</span><select value={form.costModel} onChange={(event) => setForm({ ...form, costModel: event.target.value })}><option>OPTIMISTIC</option><option>REALISTIC</option><option>STRESSED</option></select></label>
            <div className="switch-stack"><Toggle checked disabled onChange={() => undefined} label="Compound realised P&L (required)" /><Toggle checked={form.riskTaper} onChange={(checked) => setForm({ ...form, riskTaper: checked })} label="Adaptive risk taper" /></div>
          </div>
          <div className="selection-groups">
            <fieldset><legend>Instrument universe</legend><div className="chip-grid">{instruments.map((instrument) => <label className={form.instruments.includes(instrument) ? "selected" : ""} key={instrument}><input type="checkbox" checked={form.instruments.includes(instrument)} onChange={() => toggleList("instruments", instrument)} />{instrument}</label>)}</div></fieldset>
            <fieldset><legend>Strategy set</legend><div className="chip-grid">{strategies.map((strategy) => <label className={form.strategies.includes(strategy) ? "selected" : ""} key={strategy}><input type="checkbox" checked={form.strategies.includes(strategy)} onChange={() => toggleList("strategies", strategy)} />{strategy}</label>)}</div></fieldset>
          </div>
          <div className="form-actions"><span>Seed 8500 · Simulation clock isolated · Look-ahead guard on</span><SecureAction<BacktestResult> label="Run backtest" title="Run historical backtest" description="Authenticate to run this costed simulation and persist its full decision audit trail." endpoint="/backtests" body={{ ...form, compounding: true }} variant="primary" disabled={!form.instruments.length || form.strategies.length !== 1} onCompleted={acceptCompletedBacktest} /></div>
        </div>
        {jobMessage && <div className={`job-message ${jobMessage.tone}`} role="status" aria-live="polite">{jobMessage.text}</div>}
      </Panel>

      <div className="run-selector">
        <div>{runs.map((run) => <button key={run.id} type="button" className={run.id === active.id ? "active" : ""} onClick={() => setActiveId(run.id)}><span>{run.name}</span><small>{run.status} · {run.dateFrom} → {run.dateTo}</small></button>)}</div>
      </div>

      <div className="result-heading">
        <div><p className="eyebrow">Selected result</p><h2>{active.name}</h2><p>{active.dataSource}</p></div>
        <div className="result-actions"><StatusPill tone={active.status === "COMPLETED" ? "positive" : active.status === "FAILED" ? "negative" : "warning"}>{active.status}</StatusPill>{active.status === "RUNNING" && <SecureAction label="Cancel" title="Cancel running backtest" description="Authenticate to request cancellation of this research job." endpoint={`/backtests/${active.id}/cancel`} variant="danger" onCompleted={async () => { await resource.refresh(); setJobMessage({ tone: "warning", text: `Cancellation requested for ${active.id}.` }); }} />}<button type="button" className="button button-secondary" onClick={() => downloadCsv(`${active.id}-trades.csv`, active.trades as unknown as Array<Record<string, unknown>>)}><Icon name="download" size={15} />CSV</button><button type="button" className="button button-secondary" onClick={() => downloadJson(`${active.id}.json`, active)}><Icon name="download" size={15} />JSON</button></div>
      </div>
      {active.status !== "COMPLETED" && <Panel><ProgressBar value={active.progress} label={`Backtest ${active.status.toLowerCase()}`} /></Panel>}
      <div className="result-provenance"><span><strong>Source</strong>{active.dataSource}</span><span><strong>Data quality</strong>{active.dataQuality}</span><span><strong>Resolution</strong>{active.resolution}</span><span><strong>Fill policy</strong>CONSERVATIVE</span><span><strong>Costs</strong>{active.costModel}</span><span><strong>Seed</strong>{active.seed}</span></div>
      <div className="metric-grid metric-grid-8">
        <MetricCard label="Final equity" value={formatMoney(active.metrics.finalEquity)} detail={`From ${formatMoney(active.metrics.startingEquity)}`} tone={pnlTone(active.metrics.finalEquity - active.metrics.startingEquity)} />
        <MetricCard label="Total return" value={formatPercent(active.metrics.totalReturn, 2, true)} detail={`CAGR ${formatPercent(active.metrics.cagr)}`} tone={pnlTone(active.metrics.totalReturn)} />
        <MetricCard label="Max drawdown" value={formatPercent(active.metrics.maximumDrawdown)} detail={active.metrics.drawdownDuration} tone="warning" />
        <MetricCard label="Trades" value={active.metrics.trades} detail={`${formatPercent(active.metrics.winRate, 1)} win rate`} />
        <MetricCard label="Profit factor" value={active.metrics.profitFactor.toFixed(2)} detail={`${formatMoney(active.metrics.expectancy)} expectancy`} />
        <MetricCard label="Sharpe" value={active.metrics.sharpe.toFixed(2)} detail={`Sortino ${active.metrics.sortino.toFixed(2)}`} />
        <MetricCard label="Trading costs" value={formatMoney(active.metrics.totalCosts)} detail="Spread + slippage + funding" tone="warning" />
        <MetricCard label="Max leverage" value={`${active.metrics.maxLeverage.toFixed(2)}×`} detail={`${formatPercent(active.metrics.exposure, 1)} exposure`} />
      </div>
      <Panel title="Performance path" eyebrow="Click a trade marker for full detail" actions={<Segmented value={chartMode} options={["Equity", "Drawdown", "Exposure"] as const} onChange={setChartMode} label="Backtest chart" />}>
        <TimeSeriesChart data={chart.data} lines={[{ key: "value", label: chart.label, color: chart.color }]} valueFormatter={chart.formatter} markers={chartMode === "Equity" ? markers : []} activeMarkerId={selectedTrade?.id} onMarkerClick={(marker) => setSelectedTrade(active.trades.find((trade) => trade.id === marker.id) ?? null)} ariaLabel={`${chartMode} curve for ${active.name}`} zeroLine={chartMode === "Drawdown"} />
      </Panel>

      <Panel title="Strategy comparison" eyebrow="Identical data, period, and cost assumptions">
        <div className="compare-controls">{runs.slice(0, 5).map((run) => <label key={run.id}><input type="checkbox" checked={comparisonIds.includes(run.id)} onChange={() => setComparisonIds((current) => current.includes(run.id) ? current.filter((id) => id !== run.id) : [...current, run.id])} />{run.strategy}</label>)}</div>
        <div className="table-scroll"><table className="data-table comparison-table"><thead><tr><th>Variant</th><th className="number">Final equity</th><th className="number">Return</th><th className="number">Max DD</th><th className="number">Sharpe</th><th className="number">Sortino</th><th className="number">Profit factor</th><th className="number">Costs</th><th>Risk context</th></tr></thead><tbody>{compared.map((run) => <tr key={run.id}><td><strong>{run.strategy}</strong><small>{run.riskProfile}</small></td><td className="number">{formatMoney(run.metrics.finalEquity)}</td><td className={`number text-${pnlTone(run.metrics.totalReturn)}`}>{formatPercent(run.metrics.totalReturn, 1, true)}</td><td className="number text-warning">{formatPercent(run.metrics.maximumDrawdown, 1)}</td><td className="number">{run.metrics.sharpe.toFixed(2)}</td><td className="number">{run.metrics.sortino.toFixed(2)}</td><td className="number">{run.metrics.profitFactor.toFixed(2)}</td><td className="number">{formatMoney(run.metrics.totalCosts)}</td><td><StatusPill tone={run.metrics.maximumDrawdown > 10 ? "warning" : "positive"}>{run.metrics.maximumDrawdown > 10 ? "Higher drawdown" : "Contained"}</StatusPill></td></tr>)}</tbody></table></div>
      </Panel>

      <div className="layout-1-1">
        <Panel title="Monthly returns" eyebrow="Negative periods remain visible"><ReturnHeatmap returns={active.monthlyReturns} /></Panel>
        <Panel title="Monte Carlo robustness" eyebrow="Trade-sequence bootstrap"><MonteCarloDistribution result={active.monteCarlo} /><div className="mc-stats"><span><strong>{formatPercent(active.monteCarlo.belowStartingProbability, 1)}</strong>below £500</span><span><strong>{formatPercent(active.monteCarlo.ruinProbability, 1)}</strong>risk of ruin</span><span><strong>{formatPercent(active.monteCarlo.target750Probability, 1)}</strong>reach £750</span><span><strong>{formatPercent(active.monteCarlo.target5000Probability, 1)}</strong>reach £5,000</span></div></Panel>
      </div>
      <Panel title="Performance breakdown" eyebrow="Costs included" actions={<Segmented value={breakdown} options={["Instrument", "Regime", "Strategy"] as const} onChange={setBreakdown} label="Breakdown dimension" />} flush>
        <div className="table-scroll"><table className="data-table"><thead><tr><th>{breakdown}</th><th className="number">Trades</th><th className="number">Win rate</th><th className="number">Net P&amp;L</th><th className="number">Return</th></tr></thead><tbody>{breakdownRows.map((row) => <tr key={row.label}><td><strong>{humanize(row.label)}</strong></td><td className="number">{row.trades}</td><td className="number">{formatPercent(row.winRate, 1)}</td><td className={`number text-${pnlTone(row.pnl)}`}>{formatMoney(row.pnl)}</td><td className={`number text-${pnlTone(row.returnPercent)}`}>{formatPercent(row.returnPercent, 1, true)}</td></tr>)}</tbody></table></div>
      </Panel>
      <Panel title="Decision records" eyebrow="Nothing hidden" actions={<Segmented value={resultTab} options={["Trades", "Rejected"] as const} onChange={setResultTab} label="Decision records" />} flush>
        {resultTab === "Trades" ? <TradeTable trades={active.trades} onSelect={setSelectedTrade} /> : <OpportunityTable opportunities={active.rejectedOpportunities} onSelect={setSelectedOpportunity} />}
      </Panel>
      <div className="milestone-strip">{Object.entries(active.milestones).map(([milestone, timestamp]) => <div key={milestone}><Icon name={timestamp ? "check" : "target"} /><span>{milestone}</span><strong>{timestamp ? formatDateTime(timestamp) : "Not reached"}</strong></div>)}</div>
      <TradeDetail trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
      <OpportunityDetail opportunity={selectedOpportunity} onClose={() => setSelectedOpportunity(null)} />
    </>
  );
}
