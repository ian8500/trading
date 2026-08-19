import { useEffect, useState } from "react";
import { ExposureBars } from "../charts/VisualCharts";
import { Icon } from "../components/Icon";
import { InlineNotice, MetricCard, PageHeader, Panel, SourceBadge, StatusPill, Toggle } from "../components/Primitives";
import { SecureAction } from "../components/SecureAction";
import { demoRisk } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import { formatMoney, formatPercent, pnlTone } from "../utils/format";

export function RiskPage() {
  const resource = useApiResource("/risk/status", demoRisk);
  const data = resource.data;
  const [profile, setProfile] = useState(data.profile);
  const [taper, setTaper] = useState(data.taperEnabled);
  useEffect(() => {
    setProfile(data.profile);
    setTaper(data.taperEnabled);
  }, [data.profile, data.taperEnabled]);
  const healthy = data.circuitBreakers.filter((breaker) => breaker.status === "healthy").length;
  const fractionalRates = data.riskPerTrade <= 0.1 && data.maxOpenRisk <= 0.5;
  const percent = (value: number) => fractionalRates ? value * 100 : value;
  const riskPerTrade = percent(data.riskPerTrade);
  const maxOpenRisk = percent(data.maxOpenRisk);
  const currentOpenRisk = percent(data.currentOpenRisk);
  const marginUsage = percent(data.marginUsage);
  const drawdown = percent(data.drawdown);

  return (
    <>
      <PageHeader title="Risk authority" eyebrow="Deterministic RiskEngine" description="The only component permitted to approve execution. Strategies and AI may propose; neither can bypass these limits." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <InlineNotice tone="positive" title="RiskEngine mandatory">Every simulated and Demo order must carry a persisted approval record, fresh market state, a sized stop, and a unique intent ID.</InlineNotice>
      <div className="risk-profile-banner"><div><p className="eyebrow">Active profile</p><h2>{data.profile}</h2><span>{formatPercent(riskPerTrade, 1)} planned equity risk per trade</span></div><div className="profile-selector"><label><span>Proposed profile</span><select value={profile} onChange={(event) => setProfile(event.target.value as typeof profile)}><option>Conservative</option><option>Standard</option><option>Aggressive</option><option>Experimental</option><option>Custom</option></select></label><Toggle checked={taper} onChange={setTaper} label="Risk taper" /><SecureAction label="Apply risk profile" description="The backend validates this profile against current open positions, persisted circuit breakers, and administrator permissions before applying it." endpoint="/risk/profile" body={{ profile, taperEnabled: taper }} variant="primary" confirmationPhrase={`APPLY ${profile.toUpperCase()}`} disabled={profile === data.profile && taper === data.taperEnabled} onCompleted={resource.refresh} /></div></div>
      <div className="metric-grid metric-grid-8">
        <MetricCard label="Managed equity" value={formatMoney(data.managedEquity)} detail="Current sizing base" tone="positive" />
        <MetricCard label="Risk per trade" value={formatPercent(riskPerTrade, 1)} detail={`${formatMoney(data.managedEquity * riskPerTrade / 100)} maximum`} />
        <MetricCard label="Maximum open risk" value={formatPercent(maxOpenRisk, 1)} detail={formatMoney(data.managedEquity * maxOpenRisk / 100)} />
        <MetricCard label="Current open risk" value={formatPercent(currentOpenRisk, 2)} detail={`${formatPercent(maxOpenRisk - currentOpenRisk, 2)} headroom`} tone="warning" progress={maxOpenRisk ? currentOpenRisk / maxOpenRisk * 100 : 0} />
        <MetricCard label="Margin usage" value={formatPercent(marginUsage, 2)} detail="Hard cap 35%" />
        <MetricCard label="Effective leverage" value={`${data.effectiveLeverage.toFixed(2)}×`} detail="Hard cap 2.00×" />
        <MetricCard label="Daily P&L" value={formatMoney(data.dailyPnl)} detail={formatPercent(data.dailyPnl / data.managedEquity * 100, 2, true)} tone={pnlTone(data.dailyPnl)} />
        <MetricCard label="Drawdown" value={formatPercent(drawdown, 2)} detail="Hard stop 18%" tone={drawdown > 10 ? "warning" : "neutral"} />
      </div>
      <div className="layout-2-1">
        <Panel title="Circuit breakers" eyebrow={`${healthy}/${data.circuitBreakers.length} healthy`}>
          <div className="breaker-list">{data.circuitBreakers.map((breaker) => <div key={breaker.name}><i className={`breaker-light ${breaker.status}`} /><div><strong>{breaker.name}</strong><span>{breaker.detail}</span></div><dl><div><dt>Current</dt><dd>{breaker.current}</dd></div><div><dt>Limit</dt><dd>{breaker.threshold}</dd></div></dl><StatusPill tone={breaker.status === "healthy" ? "positive" : breaker.status === "warning" ? "warning" : "negative"}>{breaker.status.toUpperCase()}</StatusPill></div>)}</div>
        </Panel>
        <Panel title="Correlation exposure" eyebrow="Post-netting clusters">
          <ExposureBars data={data.correlationExposure.map((item) => ({ label: item.cluster, value: item.exposure, limit: item.limit }))} />
          <div className="correlation-examples"><div><span>Long GBP/USD</span><Icon name="arrow" /><strong>GBP long + USD short</strong></div><div><span>Long NASDAQ</span><Icon name="arrow" /><strong>US equity beta</strong></div></div>
        </Panel>
      </div>
      <div className="layout-1-1">
        <Panel title="Blocked scope" eyebrow="Explicit rejection state">
          <div className="blocked-groups"><section><h3>Strategies</h3>{data.blockedStrategies.length ? data.blockedStrategies.map((item) => <div key={item}><Icon name="lock" /><span>{item}</span></div>) : <p>None</p>}</section><section><h3>Markets</h3>{data.blockedMarkets.length ? data.blockedMarkets.map((item) => <div key={item}><Icon name="lock" /><span>{item}</span></div>) : <p>None</p>}</section></div>
        </Panel>
        <Panel title="Risk taper schedule" eyebrow={data.taperEnabled ? "Enabled" : "Disabled"}>
          <div className="taper-steps"><div className="active"><span>£500–£1k</span><strong>Aggressive research</strong><small>Current tier · hard caps still apply</small></div><div><span>£1k–£2.5k</span><strong>Moderately aggressive</strong><small>Reduced percentage risk</small></div><div><span>£2.5k–£4k</span><strong>Capital growth</strong><small>Further risk reduction</small></div><div><span>£4k–£5k</span><strong>Capital protection</strong><small>Target preservation bias</small></div></div>
        </Panel>
      </div>
      <Panel title="Prohibited behaviour" eyebrow="Hard-coded invariants"><div className="prohibited-grid">{["Martingale or doubling after losses", "Revenge sizing or winning-streak risk increases", "Removing or widening stops to avoid loss", "Averaging down solely because price moved adversely", "Orders on stale data or failed reconciliation", "AI-directed leverage, mode, or risk changes", "Duplicate submission after ambiguous broker response", "Unbounded leverage or unmanaged margin"].map((rule) => <div key={rule}><Icon name="close" /><span>{rule}</span></div>)}</div></Panel>
    </>
  );
}
