import { useMemo, useState } from "react";
import { Icon } from "../components/Icon";
import { DataTimestamp, MetricCard, PageHeader, Panel, SourceBadge, StatusPill } from "../components/Primitives";
import { demoSystem } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import { formatDateTime, humanize } from "../utils/format";

export function SystemPage() {
  const resource = useApiResource("/system/health?include_audit=true", demoSystem);
  const data = resource.data;
  const [filter, setFilter] = useState("ALL");
  const counts = {
    healthy: data.services.filter((service) => service.status === "healthy").length,
    warning: data.services.filter((service) => service.status === "warning").length,
    critical: data.services.filter((service) => service.status === "critical").length,
    inactive: data.services.filter((service) => service.status === "neutral").length,
  };
  const audit = useMemo(() => data.auditEvents.filter((event) => filter === "ALL" || event.category === filter), [data.auditEvents, filter]);

  return (
    <>
      <PageHeader title="System health" eyebrow="Local operations" description="Service state, safe error summaries, runtime configuration, and an auditable control timeline." actions={<><DataTimestamp value={data.asOf} /><SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} /></>} />
      <div className="metric-grid metric-grid-4">
        <MetricCard label="Healthy" value={counts.healthy} detail={`${data.services.length} services observed`} tone="positive" />
        <MetricCard label="Warnings" value={counts.warning} detail="Degraded or action required" tone={counts.warning ? "warning" : "positive"} />
        <MetricCard label="Critical" value={counts.critical} detail="New orders fail closed" tone={counts.critical ? "negative" : "positive"} />
        <MetricCard label="Inactive" value={counts.inactive} detail="Disabled by configuration" />
      </div>
      <Panel title="Service matrix" eyebrow="Green · amber · red">
        <div className="service-grid">{data.services.map((service) => <article key={service.id} className={`service-card service-${service.status}`}><div><span className="service-indicator"><i /></span><StatusPill tone={service.status === "healthy" ? "positive" : service.status === "warning" ? "warning" : service.status === "critical" ? "negative" : "neutral"}>{service.status === "neutral" ? "INACTIVE" : service.status.toUpperCase()}</StatusPill></div><h3>{service.name}</h3><p>{service.message}</p><footer><span>{formatDateTime(service.checkedAt, false)}</span>{service.latencyMs != null && <strong>{service.latencyMs} ms</strong>}</footer></article>)}</div>
      </Panel>
      <div className="layout-1-1">
        <Panel title="Runtime environment" eyebrow="Non-secret configuration">
          <dl className="environment-list">{Object.entries(data.environment).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value}</dd></div>)}</dl>
          <div className="redaction-note"><Icon name="lock" /><div><strong>Sensitive values are never returned</strong><p>Credentials, API keys, passwords, tokens, session headers, and unmasked account identifiers cannot appear in this response.</p></div></div>
        </Panel>
        <Panel title="Failure policy" eyebrow="Fail closed">
          <div className="failure-flow"><div><span>1</span><p><strong>Detect</strong>Stale, impossible, disconnected, ambiguous, or inconsistent state.</p></div><div><span>2</span><p><strong>Persist</strong>Record the risk event and breaker transition.</p></div><div><span>3</span><p><strong>Block</strong>Prevent every new order path.</p></div><div><span>4</span><p><strong>Reconcile</strong>Require explicit health restoration before resume.</p></div></div>
        </Panel>
      </div>
      <Panel title="Audit timeline" eyebrow="Concise structured reasons" actions={<select aria-label="Filter audit events" value={filter} onChange={(event) => setFilter(event.target.value)}><option>ALL</option><option>CONTROL</option><option>RISK</option><option>BROKER</option><option>DATA</option><option>STRATEGY</option><option>SYSTEM</option></select>}>
        <div className="audit-timeline">{audit.map((event) => <div key={event.id}><time>{formatDateTime(event.timestamp)}</time><i className={event.severity} /><div><span>{event.category}</span><strong>{event.summary}</strong><p>{event.detail}</p><small>Actor: {event.actor}</small></div></div>)}</div>
      </Panel>
      <Panel title="Local notifications" eyebrow="Material events only"><div className="notification-policy">{["Demo trade opened or closed", "Circuit breaker activated", "Strategy suspended", "Stale data or IG disconnect", "Reconciliation failure", "Failed protective stop", "Demo automation started or stopped", "Emergency close requested"].map((notification) => <div key={notification}><Icon name="check" /><span>{notification}</span></div>)}</div><p className="panel-caption">Low-quality opportunities do not create notifications; they remain available in the opportunity audit trail.</p></Panel>
    </>
  );
}
