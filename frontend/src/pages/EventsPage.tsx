import { useEffect, useMemo, useState } from "react";
import { Icon } from "../components/Icon";
import { InlineNotice, MetricCard, PageHeader, Panel, SourceBadge, StatusPill } from "../components/Primitives";
import { demoEvents } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import type { MarketEvent } from "../types/domain";
import { formatDateTime, humanize } from "../utils/format";

export function EventsPage() {
  const resource = useApiResource("/events?include_news=true&limit=100", demoEvents);
  const [type, setType] = useState("ALL");
  const [importance, setImportance] = useState("ALL");
  const [selected, setSelected] = useState<MarketEvent | null>(resource.data[0] ?? null);
  useEffect(() => {
    setSelected((current) => resource.data.find((event) => event.id === current?.id) ?? resource.data[0] ?? null);
  }, [resource.data]);
  const filtered = useMemo(() => resource.data.filter((event) => (type === "ALL" || event.type === type) && (importance === "ALL" || event.importance === importance)), [resource.data, type, importance]);
  const highImpact = resource.data.filter((event) => event.importance === "HIGH").length;
  const restricted = resource.data.filter((event) => event.state === "PRE_EVENT" || event.state === "RELEASE_WINDOW").length;

  return (
    <>
      <PageHeader title="Events & market context" eyebrow="Macro + international news" description="Point-in-time event state and structured interpretations that may validate or contradict quantitative candidates." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <InlineNotice tone="warning" title="News is untrusted input">Headlines and payloads are schema-validated, length-limited, and prohibited from calling tools, altering risk, or placing orders.</InlineNotice>
      <div className="metric-grid metric-grid-4">
        <MetricCard label="Upcoming events" value={resource.data.length} detail="Current configured horizon" />
        <MetricCard label="High impact" value={highImpact} detail="Policy windows enforced" tone="warning" />
        <MetricCard label="Active restrictions" value={restricted} detail="New position limitations" tone={restricted ? "warning" : "positive"} />
        <MetricCard label="News latency" value="6.2 sec" detail="Median received − published" />
      </div>
      <Panel className="filter-panel"><div className="filters"><label><span>Event type</span><select value={type} onChange={(event) => setType(event.target.value)}><option>ALL</option><option>MACRO</option><option>CENTRAL_BANK</option><option>NEWS</option><option>MARKET</option></select></label><label><span>Importance</span><select value={importance} onChange={(event) => setImportance(event.target.value)}><option>ALL</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></label><div className="filter-summary"><Icon name="filter" /><span>{filtered.length} events</span></div></div></Panel>
      <div className="events-layout">
        <div className="event-calendar">
          <div className="calendar-heading"><span>Time</span><span>Impact</span><span>Event</span><span>State</span></div>
          {filtered.length ? filtered.map((event) => <button key={event.id} className={selected?.id === event.id ? "active" : ""} type="button" onClick={() => setSelected(event)}><time><strong>{formatDateTime(event.scheduledAt, false).split(" ").slice(0, 2).join(" ")}</strong><span>{formatDateTime(event.scheduledAt).split(",")[0]}</span></time><span className={`impact-dots impact-${event.importance.toLowerCase()}`}><i /><i /><i /></span><div><strong>{event.currency} · {event.name}</strong><span>{event.country} · {humanize(event.type)}</span></div><StatusPill tone={event.state === "RELEASE_WINDOW" ? "negative" : event.state === "PRE_EVENT" ? "warning" : "neutral"}>{humanize(event.state)}</StatusPill></button>) : <div className="empty-state"><Icon name="events" size={30} /><strong>No configured events</strong><p>The quantitative baseline continues without a macro or news provider.</p></div>}
        </div>
        <Panel className="event-detail-panel">
          {selected ? <><div className="event-detail-title"><div><span className={`importance importance-${selected.importance.toLowerCase()}`}>{selected.importance}</span><p className="eyebrow">{humanize(selected.type)} · {selected.currency}</p><h2>{selected.name}</h2><p>{formatDateTime(selected.scheduledAt)}</p></div><StatusPill tone={selected.state === "PRE_EVENT" ? "warning" : selected.state === "RELEASE_WINDOW" ? "negative" : "info"}>{humanize(selected.state)}</StatusPill></div><p className="event-summary">{selected.summary}</p><dl className="release-grid"><div><dt>Forecast</dt><dd>{selected.forecast ?? "—"}</dd></div><div><dt>Actual</dt><dd>{selected.actual ?? "Pending"}</dd></div><div><dt>Previous</dt><dd>{selected.previous ?? "—"}</dd></div><div><dt>Normalised surprise</dt><dd>{selected.surprise?.toFixed(2) ?? "Pending"}</dd></div></dl><section className="drawer-section"><h3>Affected markets</h3><div className="tag-list">{selected.affectedMarkets.map((market) => <span key={market}>{market}</span>)}</div></section><section className="drawer-section"><h3>Point-in-time provenance</h3><dl className="detail-grid"><div><dt>Source</dt><dd>{selected.source}</dd></div><div><dt>Received</dt><dd>{formatDateTime(selected.receivedAt)}</dd></div><div><dt>Version</dt><dd>Original observation</dd></div><div><dt>Revision policy</dt><dd>Later revisions never leak backward</dd></div></dl></section>{selected.sourceUrl && <a className="button button-secondary" href={selected.sourceUrl} target="_blank" rel="noreferrer">Open primary source <Icon name="arrow" /></a>}</> : <p>Select an event.</p>}
        </Panel>
      </div>
      <div className="layout-1-1">
        <Panel title="Event risk policy" eyebrow="Deterministic restrictions"><div className="policy-timeline"><div><span>−30m</span><strong>PRE_EVENT</strong><p>Reduce or prohibit new sensitive positions.</p></div><div><span>−2m → +5m</span><strong>RELEASE_WINDOW</strong><p>Fail closed unless a dedicated strategy is eligible.</p></div><div><span>+5m → +60m</span><strong>POST_EVENT</strong><p>Evaluate continuation and reversal on completed bars.</p></div></div></Panel>
        <Panel title="Interpretation boundary" eyebrow="AI optional · disabled by default"><ul className="policy-list"><li><StatusPill tone="positive">ALLOWED</StatusPill> Extract affected markets, surprise, duration, and policy implication.</li><li><StatusPill tone="positive">ALLOWED</StatusPill> Validate or contradict a quantitative candidate.</li><li><StatusPill tone="negative">BLOCKED</StatusPill> Place orders or bypass the deterministic challenger.</li><li><StatusPill tone="negative">BLOCKED</StatusPill> Modify risk, broker mode, stops, or leverage.</li></ul></Panel>
      </div>
    </>
  );
}
