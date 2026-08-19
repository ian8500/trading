import { useEffect } from "react";
import type { Opportunity, Trade } from "../types/domain";
import { formatDateTime, formatMoney, formatNumber, formatPercent, formatPrice, humanize, pnlTone } from "../utils/format";
import { Icon } from "./Icon";
import { StatusPill } from "./Primitives";

function Drawer({ open, onClose, title, eyebrow, children }: { open: boolean; onClose: () => void; title: string; eyebrow: string; children: React.ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="drawer-layer" role="presentation">
      <button className="drawer-scrim" type="button" aria-label="Close details" onClick={onClose} />
      <aside className="detail-drawer" aria-modal="true" role="dialog" aria-label={title}>
        <div className="drawer-header"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div><button type="button" className="icon-button" aria-label="Close" onClick={onClose}><Icon name="close" /></button></div>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

function DetailGrid({ rows }: { rows: Array<[string, React.ReactNode]> }) {
  return <dl className="detail-grid">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}

export function TradeDetail({ trade, onClose }: { trade: Trade | null; onClose: () => void }) {
  return (
    <Drawer open={Boolean(trade)} onClose={onClose} title={trade ? `${trade.instrument} ${trade.direction}` : "Trade"} eyebrow="Auditable trade detail">
      {trade && <>
        <div className="drawer-hero">
          <div><span>Net P&amp;L</span><strong className={`text-${pnlTone(trade.netPnl)}`}>{formatMoney(trade.netPnl)}</strong></div>
          <StatusPill tone={trade.netPnl >= 0 ? "positive" : "negative"}>{trade.exitReason}</StatusPill>
        </div>
        <DetailGrid rows={[
          ["Strategy", `${trade.strategy} v${trade.strategyVersion}`],
          ["Regime", humanize(trade.regime)],
          ["Opened", formatDateTime(trade.openedAt)],
          ["Closed", formatDateTime(trade.closedAt)],
          ["Entry / exit", `${formatPrice(trade.entryPrice)} → ${formatPrice(trade.exitPrice)}`],
          ["Stop / target", `${formatPrice(trade.stopPrice)} / ${formatPrice(trade.targetPrice)}`],
          ["Size", formatNumber(trade.size, 3)],
          ["Gross P&L", formatMoney(trade.grossPnl)],
        ]} />
        <section className="drawer-section"><h3>Managed capital</h3><div className="capital-transition"><span>{formatMoney(trade.managedEquityBefore)}</span><Icon name="arrow" /><strong>{formatMoney(trade.managedEquityAfter)}</strong></div><p>The next position size uses the after-trade managed equity, never the broker account balance.</p></section>
        <section className="drawer-section"><h3>Trading costs</h3><DetailGrid rows={[
          ["Spread", formatMoney(trade.costs.spread)],
          ["Slippage", formatMoney(trade.costs.slippage)],
          ["Financing", formatMoney(trade.costs.financing)],
          ["Commission", formatMoney(trade.costs.commission)],
        ]} /></section>
        <section className="drawer-section"><h3>Decision trail</h3><div className="decision-step success"><span>1</span><div><strong>Opportunity · {trade.opportunityScore.toFixed(1)}</strong><p>{trade.explanation}</p></div></div><div className="decision-step success"><span>2</span><div><strong>Deterministic challenge</strong><p>{trade.challengeResult}</p></div></div><div className="decision-step success"><span>3</span><div><strong>RiskEngine</strong><p>{trade.riskDecision}</p></div></div></section>
        <section className="drawer-section"><h3>Excursion</h3><DetailGrid rows={[["Maximum adverse", formatMoney(trade.mae)], ["Maximum favourable", formatMoney(trade.mfe)]]} /></section>
      </>}
    </Drawer>
  );
}

export function OpportunityDetail({ opportunity, onClose }: { opportunity: Opportunity | null; onClose: () => void }) {
  return (
    <Drawer open={Boolean(opportunity)} onClose={onClose} title={opportunity ? `${opportunity.instrument} ${opportunity.direction}` : "Opportunity"} eyebrow="Expected growth score">
      {opportunity && <>
        <div className="score-hero">
          <div className="score-orbit"><strong>{opportunity.score.toFixed(1)}</strong><span>revised score</span></div>
          <div><StatusPill tone={opportunity.status === "ELIGIBLE" ? "positive" : opportunity.status === "REJECTED" ? "negative" : "warning"}>{humanize(opportunity.status)}</StatusPill><p>{opportunity.strategy} v{opportunity.strategyVersion}</p><small>{formatDateTime(opportunity.timestamp)}</small></div>
        </div>
        <p className="drawer-lead">{opportunity.explanation}</p>
        <DetailGrid rows={[
          ["Original score", opportunity.originalScore.toFixed(1)],
          ["Challenge revision", `${(opportunity.score - opportunity.originalScore).toFixed(1)} pts`],
          ["Signal price", formatPrice(opportunity.signalPrice)],
          ["Horizon", opportunity.expectedHorizon],
          ["Probability", opportunity.calibratedProbability == null ? <StatusPill tone="warning">Uncalibrated</StatusPill> : formatPercent(opportunity.calibratedProbability * 100, 1)],
          ["Reward / risk", `${opportunity.rewardRiskRatio.toFixed(2)}×`],
          ["Estimated costs", formatPercent(opportunity.estimatedTotalCost, 2)],
          ["Proposed equity risk", formatPercent(opportunity.proposedRisk, 2)],
          ["Regime", humanize(opportunity.regime)],
          ["Risk decision", opportunity.riskDecision],
        ]} />
        <section className="drawer-section"><h3>Inspect score composition</h3><div className="factor-list">{opportunity.factors.map((factor) => <div key={factor.label} className={`factor factor-${factor.tone}`}><div><strong>{factor.label}</strong><span>{factor.contribution > 0 ? "+" : ""}{factor.contribution.toFixed(1)}</span></div><p>{factor.detail}</p><div className="factor-track"><span style={{ width: `${Math.min(100, Math.abs(factor.contribution) * 4)}%` }} /></div></div>)}</div></section>
        <section className="drawer-section"><h3>Deterministic challenger</h3><div className={`challenge-box ${opportunity.approvedByChallenger ? "approved" : "rejected"}`}><Icon name={opportunity.approvedByChallenger ? "check" : "alert"} /><div><strong>{opportunity.approvedByChallenger ? "Approved" : "Rejected"}</strong>{opportunity.rejectionReasons.length ? <ul>{opportunity.rejectionReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>No hard rejection conditions were triggered.</p>}</div></div></section>
      </>}
    </Drawer>
  );
}
