import { Icon } from "../components/Icon";
import { InlineNotice, MetricCard, PageHeader, Panel, SourceBadge, StatusPill } from "../components/Primitives";
import { demoReadiness } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import { formatDateTime, humanize } from "../utils/format";

export function LiveReadinessPage() {
  const resource = useApiResource("/live-readiness", demoReadiness);
  const data = resource.data;
  const counts = {
    pass: data.checks.filter((item) => item.status === "PASS").length,
    warn: data.checks.filter((item) => item.status === "WARN").length,
    fail: data.checks.filter((item) => item.status === "FAIL").length,
    pending: data.checks.filter((item) => item.status === "PENDING").length,
  };
  const passedPercent = data.checks.length ? counts.pass / data.checks.length * 100 : 0;

  return (
    <>
      <PageHeader title="Live readiness" eyebrow="Evidence assessment only" description="A transparent gate for future manual review. Passing it can never activate Live execution." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <div className="live-disabled-hero"><div className="live-lock"><Icon name="lock" size={34} /></div><div><p className="eyebrow">V1 permanent state</p><h2>Live execution is disabled</h2><p>No endpoint, host, broker implementation, or frontend action can promote this application from Demo to Live.</p></div><StatusPill tone="negative">HARD LOCK</StatusPill></div>
      <InlineNotice tone="warning" title="Readiness is not permission">Even “Eligible for manual review” would mean only that evidence can be reviewed by an administrator in a future Live-capable release.</InlineNotice>
      <div className="readiness-summary">
        <div className="readiness-gauge" style={{ background: `conic-gradient(#47e6a4 ${passedPercent * 3.6}deg, #1a2926 0)` }}><div><strong>{Math.round(passedPercent)}%</strong><span>checks passed</span></div></div>
        <div className="readiness-status"><p>Assessment status</p><strong>{humanize(data.status)}</strong><span>Evaluated {formatDateTime(data.evaluatedAt)}</span></div>
        <div className="readiness-counts"><div className="pass"><strong>{counts.pass}</strong><span>Pass</span></div><div className="warn"><strong>{counts.warn}</strong><span>Warn</span></div><div className="fail"><strong>{counts.fail}</strong><span>Fail</span></div><div className="pending"><strong>{counts.pending}</strong><span>Pending</span></div></div>
      </div>
      <div className="metric-grid metric-grid-4">
        <MetricCard label="Live capability" value="ABSENT" detail="No implementation in V1" tone="negative" />
        <MetricCard label="Manual review" value={data.status === "ELIGIBLE_FOR_MANUAL_REVIEW" ? "Eligible" : "Not eligible"} detail="Evidence gate only" tone={data.status === "ELIGIBLE_FOR_MANUAL_REVIEW" ? "warning" : "negative"} />
        <MetricCard label="Failed gates" value={counts.fail} detail="Must be zero for review" tone={counts.fail ? "negative" : "positive"} />
        <MetricCard label="Pending evidence" value={counts.pending} detail="Cannot be inferred" tone={counts.pending ? "warning" : "positive"} />
      </div>
      <Panel title="Readiness evidence" eyebrow="Latest persisted assessment" flush>
        <div className="table-scroll"><table className="data-table readiness-table"><thead><tr><th>Control</th><th>Status</th><th>Current evidence</th><th>Requirement</th><th>Evidence trail</th><th>Checked</th></tr></thead><tbody>{data.checks.map((check) => <tr key={check.id}><td><strong>{check.label}</strong></td><td><StatusPill tone={check.status === "PASS" ? "positive" : check.status === "WARN" || check.status === "PENDING" ? "warning" : "negative"}>{check.status}</StatusPill></td><td>{check.value}</td><td>{check.requirement}</td><td>{check.evidence}</td><td>{formatDateTime(check.checkedAt)}</td></tr>)}</tbody></table></div>
      </Panel>
      <Panel title="Future manual activation boundary" eyebrow="Architecture only · unavailable in V1">
        <div className="activation-flow"><div><Icon name="check" /><span>Readiness evidence</span></div><Icon name="arrow" /><div><Icon name="lock" /><span>Server Live capability</span></div><Icon name="arrow" /><div><Icon name="lock" /><span>Admin + typed phrase</span></div><Icon name="arrow" /><div><Icon name="lock" /><span>Capital &amp; risk allocation</span></div><Icon name="arrow" /><div><Icon name="lock" /><span>Broker reconciliation</span></div><Icon name="arrow" /><div className="blocked"><Icon name="close" /><span>Unavailable</span></div></div>
      </Panel>
    </>
  );
}
