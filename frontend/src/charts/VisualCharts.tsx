import { useState } from "react";
import type { MonteCarloResult } from "../types/domain";
import { formatMoney, formatPercent } from "../utils/format";

export function ExposureBars({ data }: { data: Array<{ label: string; value: number; limit?: number; color?: string }> }) {
  if (!data.length) return <div className="chart-empty">No active correlation exposure.</div>;
  const max = Math.max(...data.map((item) => item.limit ?? item.value), 1);
  return (
    <div className="exposure-bars">
      {data.map((item) => (
        <div className="exposure-row" key={item.label}>
          <div><span>{item.label}</span><strong>{formatPercent(item.value, 1)}</strong></div>
          <div className="exposure-track">
            <span style={{ width: `${Math.min(100, (item.value / max) * 100)}%`, backgroundColor: item.color }} />
            {item.limit != null && <i style={{ left: `${Math.min(100, (item.limit / max) * 100)}%` }} title={`Limit ${item.limit}%`} />}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ReturnHeatmap({ returns }: { returns: Array<{ period: string; value: number }> }) {
  if (!returns.length) return <div className="chart-empty">No monthly return observations available.</div>;
  const years = Array.from(new Set(returns.map((item) => item.period.slice(0, 4))));
  const monthNames = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
  const lookup = new Map(returns.map((item) => [item.period, item.value]));
  return (
    <div className="return-heatmap">
      <div className="heatmap-row heatmap-head"><span />{monthNames.map((name, index) => <span key={`${name}-${index}`}>{name}</span>)}</div>
      {years.map((year) => (
        <div className="heatmap-row" key={year}>
          <strong>{year}</strong>
          {monthNames.map((_, index) => {
            const value = lookup.get(`${year}-${String(index + 1).padStart(2, "0")}`);
            const intensity = value == null ? 0 : Math.min(1, Math.abs(value) / 4);
            return <span key={index} title={value == null ? "No observation" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`} style={{ backgroundColor: value == null ? undefined : value >= 0 ? `rgb(71 230 164 / ${0.12 + intensity * 0.65})` : `rgb(255 107 122 / ${0.12 + intensity * 0.65})` }}>{value == null ? "" : value.toFixed(1)}</span>;
          })}
        </div>
      ))}
      <div className="heatmap-key"><span>Loss</span><i className="loss" /><i className="flat" /><i className="gain" /><span>Gain</span></div>
    </div>
  );
}

export function MonteCarloDistribution({ result }: { result: MonteCarloResult }) {
  const points = [result.percentile5, result.percentile25, result.median, result.percentile75, result.percentile95];
  const min = Math.min(...points) * 0.9;
  const max = Math.max(...points) * 1.08;
  const place = (value: number) => ((value - min) / (max - min)) * 100;
  return (
    <div className="monte-carlo-viz">
      <div className="mc-axis">
        <div className="mc-range outer" style={{ left: `${place(result.percentile5)}%`, width: `${place(result.percentile95) - place(result.percentile5)}%` }} />
        <div className="mc-range inner" style={{ left: `${place(result.percentile25)}%`, width: `${place(result.percentile75) - place(result.percentile25)}%` }} />
        <i className="mc-start" style={{ left: `${place(500)}%` }}><span>Start £500</span></i>
        <i className="mc-median" style={{ left: `${place(result.median)}%` }}><span>Median {formatMoney(result.median, "GBP", 0)}</span></i>
      </div>
      <div className="mc-labels"><span>5th<br /><strong>{formatMoney(result.percentile5, "GBP", 0)}</strong></span><span>25th<br /><strong>{formatMoney(result.percentile25, "GBP", 0)}</strong></span><span>75th<br /><strong>{formatMoney(result.percentile75, "GBP", 0)}</strong></span><span>95th<br /><strong>{formatMoney(result.percentile95, "GBP", 0)}</strong></span></div>
    </div>
  );
}

export function ParameterSurface({ values }: { values: number[][] }) {
  const [active, setActive] = useState<{ row: number; column: number } | null>(null);
  if (!values.length || !values.some((row) => row.length)) return <div className="chart-empty">No parameter surface has been persisted for this version.</div>;
  const all = values.flat();
  const min = Math.min(...all);
  const max = Math.max(...all);
  return (
    <div className="parameter-surface" role="grid" aria-label="Parameter stability surface">
      {values.map((row, rowIndex) => row.map((value, columnIndex) => {
        const ratio = (value - min) / (max - min || 1);
        const selected = active?.row === rowIndex && active.column === columnIndex;
        return (
          <button
            type="button"
            role="gridcell"
            key={`${rowIndex}-${columnIndex}`}
            className={selected ? "selected" : ""}
            style={{ backgroundColor: `color-mix(in srgb, #47e6a4 ${Math.round(ratio * 80)}%, #101b19)` }}
            onClick={() => setActive({ row: rowIndex, column: columnIndex })}
            title={`Parameter set ${rowIndex + 1}.${columnIndex + 1}: objective ${value.toFixed(2)}`}
          >
            {value.toFixed(2)}
          </button>
        );
      }))}
      {active && <p>Selected set {active.row + 1}.{active.column + 1} · objective {values[active.row][active.column].toFixed(2)}</p>}
    </div>
  );
}

export function CircularProgress({ value, label, detail }: { value: number; label: string; detail: string }) {
  const degrees = Math.max(0, Math.min(100, value)) * 3.6;
  return (
    <div className="circular-progress" style={{ background: `conic-gradient(#47e6a4 ${degrees}deg, #1b2926 ${degrees}deg)` }}>
      <div><strong>{label}</strong><span>{detail}</span></div>
    </div>
  );
}
