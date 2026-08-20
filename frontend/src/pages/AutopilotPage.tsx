import { useEffect } from "react";
import { Icon } from "../components/Icon";
import { DataTimestamp, InlineNotice, PageHeader, Panel, SourceBadge, StatusPill } from "../components/Primitives";
import { useApiResource } from "../hooks/useApiResource";
import type { AutopilotSnapshot } from "../types/domain";
import { formatPercent } from "../utils/format";

const safeFallback: AutopilotSnapshot = {
  mode: "SAFE_RESEARCH_AUTOPILOT",
  state: "STAY_IN_CASH",
  headline: "Stay in cash",
  summary: "The backend is unavailable, so the automatic decision is to take no action.",
  checkedAt: new Date().toISOString(),
  nextCheckAt: new Date().toISOString(),
  refreshSeconds: 60,
  automaticMonitoring: true,
  evidenceStatus: "MISSING",
  evidenceGeneratedAt: null,
  protocolVersion: "unknown",
  protocolFingerprint: "",
  reportFingerprint: null,
  implementationDigest: "",
  strategies: [],
  reasons: ["Verified evidence is unavailable.", "Fail-closed policy preserves capital."],
  safeguards: ["No broker orders can be created.", "IG Demo remains stopped.", "Live execution remains unavailable."],
  demoTradingEnabled: false,
  liveTradingEnabled: false,
  orderExecutionEnabled: false,
};

export function AutopilotPage() {
  const resource = useApiResource("/autopilot/status", safeFallback);
  const data = resource.data;
  const refresh = resource.refresh;

  useEffect(() => {
    const timer = window.setInterval(() => void refresh(), data.refreshSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [data.refreshSeconds, refresh]);

  const verified = data.evidenceStatus === "VERIFIED";
  return (
    <>
      <PageHeader
        eyebrow="Automatic research · fail closed"
        title="Research autopilot"
        description="One clear decision, continuously checked against frozen evidence and safety rules."
        actions={<><DataTimestamp value={data.checkedAt} prefix="Checked" /><SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} /></>}
      />

      <section className={`autopilot-decision ${verified ? "verified" : "unverified"}`}>
        <div className="autopilot-orb"><span /><Icon name={data.state === "STAY_IN_CASH" ? "lock" : "alert"} size={30} /></div>
        <div className="autopilot-decision-copy">
          <div className="autopilot-running"><i />Monitoring automatically every {data.refreshSeconds} seconds</div>
          <p className="eyebrow">Current automatic decision</p>
          <h2>{data.headline}</h2>
          <p>{data.summary}</p>
          <div className="autopilot-badges">
            <StatusPill tone={verified ? "positive" : "warning"}>Evidence {data.evidenceStatus}</StatusPill>
            <StatusPill tone="positive">Capital protected</StatusPill>
            <StatusPill tone="neutral">Orders disabled</StatusPill>
          </div>
        </div>
      </section>

      {!verified && (
        <InlineNotice tone="warning" title="Automatic safe fallback">
          Research evidence is missing or stale. Autopilot will remain in cash until a valid frozen report is available.
        </InlineNotice>
      )}

      <div className="autopilot-grid">
        <Panel title="Why this decision" eyebrow="Plain-language reasoning">
          <ol className="autopilot-reason-list">{data.reasons.map((reason, index) => <li key={reason}><span>{index + 1}</span><p>{reason}</p></li>)}</ol>
        </Panel>
        <Panel title="What autopilot can do" eyebrow="Strictly limited authority">
          <div className="autopilot-safeguards">{data.safeguards.map((item) => <div key={item}><Icon name="check" /><span>{item}</span></div>)}</div>
          <div className="autopilot-lock-row"><Icon name="lock" /><div><strong>No unattended execution</strong><span>A human remains required before any future Demo promotion.</span></div></div>
        </Panel>
      </div>

      <Panel title="Strategy evidence" eyebrow={`Frozen protocol ${data.protocolVersion}`} className="autopilot-evidence">
        {data.strategies.length ? (
          <div className="autopilot-strategies">{data.strategies.map((strategy) => (
            <article key={strategy.name}>
              <div><strong>{strategy.name}</strong><StatusPill tone={strategy.status === "NOT_ELIGIBLE" ? "negative" : "warning"}>{strategy.status === "NOT_ELIGIBLE" ? "Not eligible" : "Review required"}</StatusPill></div>
              <dl>
                <div><dt>After-cost return</dt><dd className={strategy.returnPercent >= 0 ? "text-positive" : "text-negative"}>{formatPercent(strategy.returnPercent, 2, true)}</dd></div>
                <div><dt>Profit factor</dt><dd>{strategy.profitFactor.toFixed(2)}</dd></div>
                <div><dt>Trades</dt><dd>{strategy.trades}</dd></div>
                <div><dt>Worst drawdown</dt><dd>{formatPercent(strategy.maximumDrawdownPercent, 2)}</dd></div>
              </dl>
              <p>{strategy.unmetGateCount} mandatory gate{strategy.unmetGateCount === 1 ? "" : "s"} missed</p>
            </article>
          ))}</div>
        ) : <div className="empty-state"><Icon name="lock" size={28} /><strong>No verified strategy evidence</strong><p>Autopilot is safely holding cash.</p></div>}
        <div className="autopilot-evidence-footer">
          <span>Protocol <code>{data.protocolFingerprint.slice(0, 12) || "unavailable"}</code></span>
          <span>Implementation <code>{data.implementationDigest.slice(0, 12) || "unavailable"}</code></span>
          <a className="button button-secondary" href="/results">View simple results <Icon name="arrow" size={14} /></a>
        </div>
      </Panel>
    </>
  );
}
