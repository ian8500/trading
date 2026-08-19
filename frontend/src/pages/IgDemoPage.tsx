import { PositionTable } from "../components/DataTables";
import { Icon } from "../components/Icon";
import { InlineNotice, MetricCard, PageHeader, Panel, SourceBadge, StatusPill } from "../components/Primitives";
import { SecureAction } from "../components/SecureAction";
import { demoIgStatus } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import { formatDateTime, formatMoney, formatPercent, humanize } from "../utils/format";

export function IgDemoPage() {
  const resource = useApiResource("/ig-demo/status", demoIgStatus);
  const data = resource.data;
  const refresh = () => resource.refresh();
  const canStart = data.configured && data.connected && data.reconciliation === "RECONCILED" && !data.autonomousMode;

  return (
    <>
      <PageHeader title="IG Demo operations" eyebrow="External execution · Demo only" description="Capability discovery, account reconciliation, and guarded autonomous Demo controls." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <div className="demo-only-banner"><div><Icon name="broker" size={25} /><div><strong>IG DEMO environment</strong><span>Only allowlisted Demo hosts are reachable. Live execution has no implementation in V1.</span></div></div><StatusPill tone="negative">LIVE HARD-LOCKED</StatusPill></div>
      {!data.configured && <InlineNotice tone="warning" title="IG credentials are not configured">Enter fresh IG Demo credentials only in the local backend <code>.env</code>. Never enter broker credentials in this browser, a prompt, source code, or Git.</InlineNotice>}
      <div className="metric-grid metric-grid-6">
        <MetricCard label="Connection" value={data.connected ? "CONNECTED" : "DISCONNECTED"} detail={data.configured ? data.accountIdMasked : "Backend credentials absent"} tone={data.connected ? "positive" : "warning"} />
        <MetricCard label="Broker Demo balance" value={formatMoney(data.brokerBalance)} detail="Informational only" />
        <MetricCard label="Managed equity" value={formatMoney(data.managedEquity)} detail="Authoritative sizing base" tone="positive" />
        <MetricCard label="Available broker funds" value={formatMoney(data.availableFunds)} detail="Never used as capital base" />
        <MetricCard label="Market stream" value={humanize(data.streamStatus)} detail="Snapshot freshness independently checked" tone={data.streamStatus === "CONNECTED" ? "positive" : "warning"} />
        <MetricCard label="Reconciliation" value={humanize(data.reconciliation)} detail={data.lastReconciledAt ? formatDateTime(data.lastReconciledAt) : "Required before new trades"} tone={data.reconciliation === "RECONCILED" ? "positive" : "warning"} />
      </div>
      <Panel title="Demo control centre" eyebrow="Authenticated · persistent · audited">
        <div className="control-state"><div><span className={`control-orb ${data.autonomousMode ? "on" : "off"}`}><i /></span><div><p>Autonomous Demo</p><strong>{data.autonomousMode ? "RUNNING" : "OFF"}</strong><span>{data.newTradesAllowed ? "New trades permitted by current state" : "No new Demo trades permitted"}</span></div></div><div className="control-actions"><SecureAction label="Connect" description="Open an IG Demo session from credentials held only by the backend. The response will never expose tokens or credentials." endpoint="/ig-demo/connect" variant="secondary" onCompleted={refresh} /><SecureAction label="Reconcile" description="Query Demo positions and pending orders, then compare them with internal records. New trades remain blocked if any difference is unresolved." endpoint="/ig-demo/reconcile" variant="secondary" onCompleted={refresh} /><SecureAction label="Start autonomous Demo" description="Enable autonomous IG Demo execution only after capability, stream, risk, and reconciliation checks pass. Restarting the server will not resume it automatically." endpoint="/ig-demo/autonomy/start" variant="primary" confirmationPhrase="START DEMO" disabled={!canStart} onCompleted={refresh} /><SecureAction label="Stop new Demo trades" description="Persist the kill switch immediately. Existing positions retain their protective controls and continue to be monitored." endpoint="/ig-demo/autonomy/stop" variant="danger" disabled={!data.autonomousMode} onCompleted={refresh} /><SecureAction label="Emergency close all" description="Request an orderly close of every managed IG Demo position, reconcile confirmations, and persist the kill switch." endpoint="/ig-demo/positions/emergency-close" variant="danger" confirmationPhrase="CLOSE ALL DEMO" disabled={!data.positions.length} onCompleted={refresh} /></div></div>
        {!canStart && !data.autonomousMode && <div className="control-blockers"><Icon name="lock" /><div><strong>Start is blocked</strong><span>{!data.configured ? "Configure backend-only IG Demo credentials." : !data.connected ? "Connect to IG Demo." : data.reconciliation !== "RECONCILED" ? "Complete reconciliation." : "Resolve current risk restrictions."}</span></div></div>}
      </Panel>
      <Panel title={`Discovered markets · ${data.markets.length}`} eyebrow="Capability matrix" flush>
        <div className="table-scroll"><table className="data-table"><thead><tr><th>Instrument</th><th>IG epic</th><th>Status</th><th>Snapshot</th><th>Stream</th><th>History</th><th className="number">Minimum size</th><th className="number">Margin</th><th>Controlled risk</th><th>£500 eligibility</th></tr></thead><tbody>{data.markets.map((market) => <tr key={market.epic}><td><strong>{market.instrument}</strong><small>{market.type}</small></td><td><code className="masked-code">{market.epic}</code></td><td><StatusPill tone={market.status === "TRADEABLE" ? "positive" : "warning"}>{market.status}</StatusPill></td><td><Capability value={market.snapshot} /></td><td><Capability value={market.streaming} /></td><td><Capability value={market.historical} /></td><td className="number">{market.minDealSize}</td><td className="number">{formatPercent(market.marginFactor, 2)}</td><td><Capability value={market.controlledRisk} /></td><td>{market.tradeableForManagedCapital ? <StatusPill tone="positive">Eligible</StatusPill> : <span title={market.rejectionReason}><StatusPill tone="negative">Rejected</StatusPill><small>{market.rejectionReason}</small></span>}</td></tr>)}</tbody></table></div>
      </Panel>
      <Panel title={`Open IG Demo positions · ${data.positions.length}`} eyebrow="Broker-reconciled state" flush>{data.positions.length ? <PositionTable positions={data.positions} /> : <div className="empty-state"><Icon name="positions" size={30} /><strong>No broker positions</strong><p>Open positions appear only after a successful authenticated Demo connection and reconciliation.</p></div>}</Panel>
      <div className="layout-1-1">
        <Panel title="Recent confirmations" eyebrow="Identifiers redacted">
          <div className="confirmation-list">{data.confirmations.map((confirmation) => <div key={confirmation.id}><i className={confirmation.status.toLowerCase()} /><div><strong>{confirmation.summary}</strong><span>{confirmation.dealReference} · {formatDateTime(confirmation.timestamp)}</span></div><StatusPill tone={confirmation.status === "ACCEPTED" ? "positive" : confirmation.status === "REJECTED" ? "negative" : "warning"}>{confirmation.status}</StatusPill></div>)}</div>
        </Panel>
        <Panel title="Managed capital separation" eyebrow="Safety invariant">
          <div className="capital-separation"><div><span>Broker Demo</span><strong>{formatMoney(data.brokerBalance)}</strong><small>informational</small></div><Icon name="lock" size={25} /><div className="managed"><span>Strategy ledger</span><strong>{formatMoney(data.managedEquity)}</strong><small>position-sizing base</small></div></div><p className="panel-caption">A large broker Demo balance can never increase planned risk. Every order intent stores the internal managed-equity basis used.</p>
        </Panel>
      </div>
    </>
  );
}

function Capability({ value }: { value: boolean }) {
  return <span className={`capability ${value ? "yes" : "no"}`}><Icon name={value ? "check" : "close"} size={14} />{value ? "Yes" : "No"}</span>;
}
