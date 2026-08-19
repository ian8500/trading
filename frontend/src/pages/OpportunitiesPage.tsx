import { useMemo, useState } from "react";
import { OpportunityTable } from "../components/DataTables";
import { OpportunityDetail } from "../components/Details";
import { Icon } from "../components/Icon";
import { MetricCard, PageHeader, Panel, SourceBadge, StatusPill } from "../components/Primitives";
import { demoOpportunities } from "../data/demo";
import { useApiResource } from "../hooks/useApiResource";
import type { Opportunity, OpportunityStatus } from "../types/domain";
import { formatPercent } from "../utils/format";

export function OpportunitiesPage() {
  const resource = useApiResource("/opportunities?limit=100&include_rejected=true", demoOpportunities);
  const [selected, setSelected] = useState<Opportunity | null>(null);
  const [search, setSearch] = useState("");
  const [family, setFamily] = useState("ALL");
  const [status, setStatus] = useState<"ALL" | OpportunityStatus>("ALL");
  const filtered = useMemo(() => resource.data.filter((opportunity) => {
    const searchMatch = `${opportunity.instrument} ${opportunity.strategy}`.toLowerCase().includes(search.toLowerCase());
    return searchMatch && (family === "ALL" || opportunity.marketFamily === family) && (status === "ALL" || opportunity.status === status);
  }).sort((a, b) => b.score - a.score), [resource.data, search, family, status]);
  const eligible = resource.data.filter((item) => item.status === "ELIGIBLE");
  const calibrated = resource.data.filter((item) => item.calibratedProbability != null);

  return (
    <>
      <PageHeader title="Opportunity leaderboard" eyebrow="Cross-market ranking" description="Every candidate is scored on expected geometric growth, challenged deterministically, and gated by the RiskEngine." actions={<SourceBadge source={resource.source} loading={resource.loading} onRefresh={() => void resource.refresh()} />} />
      <div className="metric-grid metric-grid-4">
        <MetricCard label="Evaluated" value={resource.data.length} detail="Latest completed cycle" />
        <MetricCard label="Eligible" value={eligible.length} detail="Still requires fresh risk validation" tone="positive" />
        <MetricCard label="Top score" value={Math.max(...resource.data.map((item) => item.score)).toFixed(1)} detail={resource.data[0]?.instrument ?? "—"} tone="info" />
        <MetricCard label="Calibrated" value={`${calibrated.length}/${resource.data.length}`} detail="Uncalibrated scores are penalised" tone={calibrated.length === resource.data.length ? "positive" : "warning"} />
      </div>
      <Panel className="filter-panel">
        <div className="filters">
          <label className="search-field"><Icon name="search" /><input aria-label="Search opportunities" placeholder="Search instrument or strategy" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <label><span>Market family</span><select value={family} onChange={(event) => setFamily(event.target.value)}><option>ALL</option><option>FX</option><option>INDEX</option><option>COMMODITY</option><option>CRYPTO</option></select></label>
          <label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value as typeof status)}><option>ALL</option><option>ELIGIBLE</option><option>REJECTED</option><option>BELOW_THRESHOLD</option><option>OBSERVATION_ONLY</option></select></label>
          <button type="button" className="button button-ghost" onClick={() => { setSearch(""); setFamily("ALL"); setStatus("ALL"); }}>Clear filters</button>
        </div>
      </Panel>
      <div className="score-method-strip">
        <div><span>Estimated net edge</span><Icon name="arrow" /><span>Calibration</span><Icon name="arrow" /><span>Regime &amp; data</span><Icon name="arrow" /><span>Costs &amp; penalties</span><Icon name="arrow" /><strong>ExpectedGrowthScore</strong></div>
        <StatusPill tone="info">Inspect every component</StatusPill>
      </div>
      <Panel title={`Ranked candidates · ${filtered.length}`} eyebrow="Higher is stronger after penalties" flush>
        <OpportunityTable opportunities={filtered} onSelect={setSelected} />
      </Panel>
      <div className="layout-1-1">
        <Panel title="Calibration coverage" eyebrow="Observed evidence only">
          <div className="calibration-bars">
            {[{ bucket: "45–50%", predicted: 47, observed: 46, n: 184 }, { bucket: "50–55%", predicted: 53, observed: 52, n: 142 }, { bucket: "55–60%", predicted: 57, observed: 55, n: 89 }, { bucket: "60–65%", predicted: 62, observed: 58, n: 31 }].map((item) => <div key={item.bucket}><div><strong>{item.bucket}</strong><span>n={item.n}</span><small>Pred. {item.predicted}% · Obs. {item.observed}%</small></div><div className="dual-bar"><span style={{ width: `${item.predicted}%` }} /><i style={{ width: `${item.observed}%` }} /></div></div>)}
          </div>
          <p className="panel-caption">Small samples and calibration error add uncertainty penalties; they can never justify increased leverage.</p>
        </Panel>
        <Panel title="Latest challenger impact" eyebrow="Original → revised">
          <div className="challenger-impact">{resource.data.slice(0, 5).map((item) => <div key={item.id}><div><strong>{item.instrument}</strong><span>{item.originalScore.toFixed(1)} → {item.score.toFixed(1)}</span></div><div className="impact-track"><span style={{ width: `${item.originalScore}%` }} /><i style={{ width: `${item.score}%` }} /></div><small>{formatPercent(item.score - item.originalScore, 1)} score revision</small></div>)}</div>
        </Panel>
      </div>
      <OpportunityDetail opportunity={selected} onClose={() => setSelected(null)} />
    </>
  );
}
