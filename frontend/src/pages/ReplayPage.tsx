import { useEffect, useMemo, useState } from "react";
import { TimeSeriesChart } from "../charts/TimeSeriesChart";
import { OpportunityDetail } from "../components/Details";
import { Icon } from "../components/Icon";
import { InlineNotice, MetricCard, PageHeader, Panel, Segmented, SourceBadge, StatusPill } from "../components/Primitives";
import { SecureAction } from "../components/SecureAction";
import { demoReplay } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import type { Opportunity, ReplaySession, SeriesPoint } from "../types/domain";
import { formatDateTime, formatMoney, formatPrice, humanize, pnlTone } from "../utils/format";
import { londonLocalDateTimeToUtcIso } from "../utils/time";

type ReplaySpeed = "STEP" | "1x" | "10x" | "100x" | "MAX";

export function ReplayPage() {
  const resource = useApiResource("/replay/sessions/latest", demoReplay);
  const [session, setSession] = useState<ReplaySession>(resource.data);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<ReplaySpeed>("10x");
  const [instrument, setInstrument] = useState("GBP/USD");
  const [selectedOpportunity, setSelectedOpportunity] = useState<Opportunity | null>(null);
  const [form, setForm] = useState({ dateFrom: "2026-05-11T07:00", dateTo: "2026-05-17T02:00", capital: 500, strategy: "Regime Ensemble", risk: "Standard", cost: "REALISTIC" });
  const [message, setMessage] = useState<string | null>(null);

  const replayWindow = useMemo<{ start: string; end: string; error: string | null }>(() => {
    try {
      const start = londonLocalDateTimeToUtcIso(form.dateFrom);
      const end = londonLocalDateTimeToUtcIso(form.dateTo);
      if (Date.parse(end) <= Date.parse(start)) return { start, end, error: "Replay end must be after its start." };
      return { start, end, error: null };
    } catch (error) {
      return {
        start: "",
        end: "",
        error: error instanceof Error ? error.message : "Choose a valid London replay window.",
      };
    }
  }, [form.dateFrom, form.dateTo]);

  const acceptCreatedReplay = (created: ReplaySession) => {
    resource.acceptApiData(created);
    setSession(created);
    setIndex(0);
    setPlaying(false);
    setInstrument(Object.keys(created.ticks[0]?.prices ?? {})[0] ?? "GBP/USD");
    setMessage("Replay created; displaying the exact session returned by the backend with pinned provenance.");
  };

  useEffect(() => { setSession(resource.data); setIndex(0); setPlaying(false); }, [resource.data]);
  useEffect(() => {
    if (!playing || speed === "STEP") return;
    const interval = speed === "1x" ? 900 : speed === "10x" ? 320 : speed === "100x" ? 90 : 24;
    const increment = speed === "MAX" ? 4 : 1;
    const timer = window.setInterval(() => setIndex((current) => {
      const next = Math.min(session.ticks.length - 1, current + increment);
      if (next >= session.ticks.length - 1) setPlaying(false);
      return next;
    }), interval);
    return () => window.clearInterval(timer);
  }, [playing, session.ticks.length, speed]);

  const tick = session.ticks[index] ?? session.ticks[0];
  const visible = session.ticks.slice(0, index + 1);
  const priceSeries = useMemo<SeriesPoint[]>(() => visible.map((item) => ({ timestamp: item.timestamp, value: item.prices[instrument] ?? 0 })), [visible, instrument]);
  const eventsSoFar = visible.filter((item) => item.event || item.opportunity || item.circuitBreaker).slice(-8).reverse();
  const progress = session.ticks.length > 1 ? index / (session.ticks.length - 1) * 100 : 0;

  return (
    <>
      <PageHeader title="Historical replay" eyebrow="Point-in-time simulation" description="Step through the same chronological event path used by research and Demo trading—without broker credentials." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <InlineNotice tone="info" title="No future information">At each simulation time, strategies can access only completed market and event data received at or before that time.</InlineNotice>
      <Panel title="Replay configuration" eyebrow="Create session">
        <div className="form-grid form-grid-6 replay-config">
          <label><span>Start · Europe/London</span><input type="datetime-local" value={form.dateFrom} onChange={(event) => setForm({ ...form, dateFrom: event.target.value })} /></label>
          <label><span>End · Europe/London</span><input type="datetime-local" value={form.dateTo} onChange={(event) => setForm({ ...form, dateTo: event.target.value })} /></label>
          <label><span>Managed capital</span><div className="input-prefix"><span>£</span><input type="number" value={form.capital} onChange={(event) => setForm({ ...form, capital: Number(event.target.value) })} /></div></label>
          <label><span>Strategy</span><select value={form.strategy} onChange={(event) => setForm({ ...form, strategy: event.target.value })}><option>Regime Ensemble</option><option>Quant Baseline</option><option>Quant Aggressive</option></select></label>
          <label><span>Risk profile</span><select value={form.risk} onChange={(event) => setForm({ ...form, risk: event.target.value })}><option>Conservative</option><option>Standard</option><option>Aggressive</option></select></label>
          <label><span>Cost model</span><select value={form.cost} onChange={(event) => setForm({ ...form, cost: event.target.value })}><option>REALISTIC</option><option>STRESSED</option><option>OPTIMISTIC</option></select></label>
        </div>
        <div className="form-actions"><span>Completed-bar signals · conservative fills · simulation clock</span><SecureAction<ReplaySession> label="Load replay" title="Create historical replay" description="Authenticate to create a point-in-time replay pinned to the selected dataset revision." endpoint="/replay/sessions" body={{ start: replayWindow.start, end: replayWindow.end, startingCapital: form.capital, strategy: form.strategy, riskProfile: form.risk, costModel: form.cost }} disabled={Boolean(replayWindow.error)} onCompleted={acceptCreatedReplay} /></div>
        {replayWindow.error && <div className="job-message negative" role="alert">{replayWindow.error}</div>}
        {message && <div className="job-message positive" role="status" aria-live="polite">{message}</div>}
      </Panel>

      <div className="replay-console">
        <div className="replay-clock-block"><p className="eyebrow">Simulation clock · Europe/London</p><strong>{formatDateTime(tick.timestamp)}</strong><span>Tick {index + 1} / {session.ticks.length}</span></div>
        <div className="replay-transport">
          <button type="button" className="transport-button" aria-label={playing ? "Pause replay" : "Play replay"} onClick={() => setPlaying((value) => !value)} disabled={index >= session.ticks.length - 1}>{playing ? <Icon name="pause" size={22} /> : <Icon name="play" size={22} />}</button>
          <button type="button" className="transport-button secondary" aria-label="Step forward" onClick={() => { setPlaying(false); setIndex((value) => Math.min(session.ticks.length - 1, value + 1)); }} disabled={index >= session.ticks.length - 1}><Icon name="step" /></button>
          <button type="button" className="text-button" onClick={() => { setPlaying(false); setIndex(0); }}>Reset</button>
          <Segmented value={speed} options={["STEP", "1x", "10x", "100x", "MAX"] as const} onChange={(value) => { setSpeed(value); if (value === "STEP") setPlaying(false); }} label="Replay speed" />
        </div>
        <div className="replay-progress"><span style={{ width: `${progress}%` }} /><i style={{ left: `${progress}%` }} /></div>
      </div>

      <div className="metric-grid metric-grid-6">
        <MetricCard label="Managed equity" value={formatMoney(tick.managedEquity)} detail={`${formatMoney(tick.managedEquity - session.startingCapital)} since start`} tone={pnlTone(tick.managedEquity - session.startingCapital)} />
        <MetricCard label="Unrealised P&L" value={formatMoney(tick.unrealisedPnl)} detail={tick.position ? tick.position.instrument : "No open position"} tone={pnlTone(tick.unrealisedPnl)} />
        <MetricCard label="Market regime" value={humanize(tick.regime)} detail="Stored with every decision" tone={tick.regime === "HIGH_VOLATILITY" ? "warning" : "info"} />
        <MetricCard label="Open positions" value={tick.position ? 1 : 0} detail={tick.position ? `${tick.position.direction} ${tick.position.instrument}` : "Cash is valid"} />
        <MetricCard label="Circuit breaker" value={tick.circuitBreaker ? "RESTRICTED" : "HEALTHY"} detail={tick.circuitBreaker ?? "All replay checks healthy"} tone={tick.circuitBreaker ? "warning" : "positive"} />
        <MetricCard label="Cost model" value={session.costModel} detail="Applied at simulated fills" />
      </div>

      <div className="layout-2-1">
        <Panel title={`${instrument} price`} eyebrow="Information available by replay time" actions={<select aria-label="Replay instrument" value={instrument} onChange={(event) => setInstrument(event.target.value)}>{Object.keys(tick.prices).map((name) => <option key={name}>{name}</option>)}</select>}>
          <TimeSeriesChart data={priceSeries} lines={[{ key: "value", label: instrument, color: "#45baf5" }]} valueFormatter={formatPrice} ariaLabel={`${instrument} replay price chart`} height={310} />
        </Panel>
        <Panel title="Market state" eyebrow="Current completed observation">
          <div className="market-price-list">{Object.entries(tick.prices).map(([name, price]) => <div key={name}><span>{name}</span><strong>{formatPrice(price)}</strong><small>completed bar</small></div>)}</div>
          <div className="state-card"><span>Regime</span><strong>{humanize(tick.regime)}</strong><StatusPill tone={tick.regime === "HIGH_VOLATILITY" ? "warning" : "info"}>Deterministic</StatusPill></div>
          {tick.position && <div className="position-mini"><div><StatusPill tone={tick.position.direction === "LONG" ? "positive" : "purple"}>{tick.position.direction}</StatusPill><strong>{tick.position.instrument}</strong></div><dl><div><dt>Entry</dt><dd>{formatPrice(tick.position.entryPrice)}</dd></div><div><dt>Stop</dt><dd className="text-negative">{formatPrice(tick.position.stopPrice)}</dd></div><div><dt>Target</dt><dd className="text-positive">{formatPrice(tick.position.targetPrice)}</dd></div></dl></div>}
        </Panel>
      </div>

      <div className="layout-1-1">
        <Panel title="Decision timeline" eyebrow="Newest first">
          {eventsSoFar.length ? <div className="timeline">{eventsSoFar.map((item) => <button key={`${item.timestamp}-${item.event?.id ?? item.opportunity?.id ?? item.circuitBreaker}`} type="button" onClick={() => item.opportunity && setSelectedOpportunity(item.opportunity)} disabled={!item.opportunity}><time>{formatDateTime(item.timestamp, false)}</time><i className={item.circuitBreaker ? "warning" : item.opportunity ? "positive" : "info"} /><div><strong>{item.opportunity ? `${item.opportunity.instrument} candidate · ${item.opportunity.score.toFixed(1)}` : item.event ? item.event.name : "Circuit restriction"}</strong><p>{item.opportunity?.explanation ?? item.event?.summary ?? item.circuitBreaker}</p></div>{item.opportunity && <Icon name="chevron" />}</button>)}</div> : <div className="waiting-state"><span className="pulse-ring" /><strong>Waiting for decision events</strong><p>Advance the replay to see opportunities, events, and circuit-breaker transitions.</p></div>}
        </Panel>
        <Panel title="Equity ledger" eyebrow="Chronological and compounded">
          <TimeSeriesChart data={visible.map((item) => ({ timestamp: item.timestamp, value: item.managedEquity }))} lines={[{ key: "value", label: "Managed equity", color: "#47e6a4" }]} valueFormatter={(value) => formatMoney(value, "GBP", 0)} ariaLabel="Replay managed equity" height={250} />
          <p className="panel-caption">The replay clock—not the wall clock—drives state and data visibility.</p>
        </Panel>
      </div>
      <OpportunityDetail opportunity={selectedOpportunity} onClose={() => setSelectedOpportunity(null)} />
    </>
  );
}
