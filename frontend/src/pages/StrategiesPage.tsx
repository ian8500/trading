import { useEffect, useState } from "react";
import { ParameterSurface } from "../charts/VisualCharts";
import { Icon } from "../components/Icon";
import { InlineNotice, MetricCard, PageHeader, Panel, SourceBadge, StatusPill } from "../components/Primitives";
import { SecureAction } from "../components/SecureAction";
import { demoStrategies } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import { formatDateTime, formatPercent, humanize, pnlTone } from "../utils/format";

export function StrategiesPage() {
  const resource = useApiResource("/strategies/versions?include_metrics=true", demoStrategies);
  const [selectedId, setSelectedId] = useState(demoStrategies[0].id);
  useEffect(() => {
    if (!resource.data.some((strategy) => strategy.id === selectedId) && resource.data[0]) setSelectedId(resource.data[0].id);
  }, [resource.data, selectedId]);
  const selected = resource.data.find((item) => item.id === selectedId) ?? resource.data[0] ?? demoStrategies[0];
  const champion = resource.data.find((item) => item.role === "CHAMPION");

  return (
    <>
      <PageHeader title="Strategy registry" eyebrow="Champion & challengers" description="Immutable versions compete on the same evidence. Promotion is always an authenticated manual decision." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <InlineNotice tone="info" title="No automatic promotion">Historical, walk-forward, robustness, and forward Demo evidence inform a review; no strategy can replace the Champion itself.</InlineNotice>
      {champion && <div className="champion-banner"><div className="champion-icon"><Icon name="target" size={28} /></div><div><p className="eyebrow">Current champion</p><h2>{champion.name} <span>v{champion.version}</span></h2><p>{champion.family} · approved {formatDateTime(champion.createdAt)}</p></div><div className="champion-stats"><span><small>OOS Sharpe</small><strong>{champion.outOfSample.sharpe.toFixed(2)}</strong></span><span><small>Max drawdown</small><strong>{formatPercent(champion.historical.drawdown, 1)}</strong></span><span><small>Demo trades</small><strong>{champion.demo.trades}</strong></span></div><StatusPill tone="positive">{champion.state}</StatusPill></div>}
      <div className="strategy-layout">
        <aside className="strategy-list">
          <p className="eyebrow">Immutable versions</p>
          {resource.data.map((strategy) => <button key={strategy.id} type="button" className={strategy.id === selected.id ? "active" : ""} onClick={() => setSelectedId(strategy.id)}><div><strong>{strategy.name}</strong><span>v{strategy.version} · {strategy.family}</span></div><StatusPill tone={strategy.role === "CHAMPION" ? "positive" : "purple"}>{strategy.role}</StatusPill><div className="strategy-mini-metrics"><span>Return <b className={`text-${pnlTone(strategy.outOfSample.returnPercent)}`}>{formatPercent(strategy.outOfSample.returnPercent, 1, true)}</b></span><span>OOS <b>{strategy.outOfSample.sharpe.toFixed(2)}</b></span><span>DD <b>{formatPercent(strategy.historical.drawdown, 1)}</b></span></div></button>)}
        </aside>
        <div className="strategy-detail">
          <div className="strategy-detail-heading"><div><div className="title-with-tags"><h2>{selected.name} <span>v{selected.version}</span></h2><StatusPill tone={selected.role === "CHAMPION" ? "positive" : "purple"}>{selected.role}</StatusPill><StatusPill tone={selected.state === "NORMAL" ? "positive" : "warning"}>{humanize(selected.state)}</StatusPill></div><p>{selected.family} · Immutable SHA-backed configuration</p></div>{selected.role === "CHALLENGER" && <SecureAction label="Promote strategy" title={`Promote ${selected.name}`} description="Promotion replaces the active Champion only after the backend revalidates all evidence and records the administrator decision." endpoint={`/strategies/${selected.id}/promote`} confirmationPhrase={`PROMOTE ${selected.name} ${selected.version}`} variant="primary" />}</div>
          <div className="metric-grid metric-grid-6">
            <MetricCard label="Historical return" value={formatPercent(selected.historical.returnPercent, 1, true)} detail={`${selected.historical.trades} trades`} tone={pnlTone(selected.historical.returnPercent)} />
            <MetricCard label="Historical Sharpe" value={selected.historical.sharpe.toFixed(2)} detail={`${formatPercent(selected.historical.drawdown, 1)} max DD`} />
            <MetricCard label="OOS return" value={formatPercent(selected.outOfSample.returnPercent, 1, true)} detail="Unseen windows" tone={pnlTone(selected.outOfSample.returnPercent)} />
            <MetricCard label="OOS Sharpe" value={selected.outOfSample.sharpe.toFixed(2)} detail={`${formatPercent(selected.outOfSample.degradation, 1)} degradation`} tone={selected.outOfSample.degradation > 30 ? "warning" : "neutral"} />
            <MetricCard label="Demo return" value={formatPercent(selected.demo.returnPercent, 1, true)} detail={`${selected.demo.trades} trades · ${selected.demo.durationDays}d`} tone={pnlTone(selected.demo.returnPercent)} />
            <MetricCard label="Promotion" value={humanize(selected.promotionState)} detail="Manual review gate" tone={selected.promotionState === "APPROVED" ? "positive" : selected.promotionState === "IN_REVIEW" ? "warning" : "negative"} />
          </div>
          <div className="layout-1-1">
            <Panel title="Version parameters" eyebrow="Frozen at creation">
              <dl className="parameter-list">{Object.entries(selected.parameters).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{String(value)}</dd></div>)}</dl>
              <div className="immutable-note"><Icon name="lock" /><div><strong>Immutable version</strong><p>Changes create a new Challenger rather than mutating this evidence record.</p></div></div>
            </Panel>
            <Panel title="Parameter stability" eyebrow="Neighbourhood objective surface"><ParameterSurface values={selected.parameterSurface} /><p className="panel-caption">Broad, stable regions are preferred. Isolated peaks are flagged as likely overfit.</p></Panel>
          </div>
          <Panel title="Validation evidence" eyebrow={selected.dataRange}>
            <div className="evidence-flow"><div className="complete"><Icon name="check" /><strong>Historical</strong><span>{selected.historical.trades} costed trades</span></div><Icon name="arrow" /><div className="complete"><Icon name="check" /><strong>Walk-forward</strong><span>Out-of-sample distinct</span></div><Icon name="arrow" /><div className={selected.outOfSample.degradation < 30 ? "complete" : "warning"}><Icon name={selected.outOfSample.degradation < 30 ? "check" : "alert"} /><strong>Robustness</strong><span>{formatPercent(selected.outOfSample.degradation, 1)} degradation</span></div><Icon name="arrow" /><div className={selected.demo.trades >= 100 ? "complete" : "pending"}><Icon name="clock" /><strong>IG Demo</strong><span>{selected.demo.trades}/100 trades</span></div><Icon name="arrow" /><div className={selected.promotionState === "APPROVED" ? "complete" : "pending"}><Icon name="lock" /><strong>Manual review</strong><span>{humanize(selected.promotionState)}</span></div></div>
          </Panel>
        </div>
      </div>
    </>
  );
}
