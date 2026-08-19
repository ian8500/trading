import { useId, useMemo, useState } from "react";
import type { ChartMarker, SeriesPoint } from "../types/domain";
import { compactDate } from "../utils/format";

type PointKey = "value" | "secondary" | "tertiary";

export interface ChartLine {
  key: PointKey;
  label: string;
  color: string;
  dashed?: boolean;
}

interface TimeSeriesChartProps {
  data: SeriesPoint[];
  lines?: ChartLine[];
  height?: number;
  area?: boolean;
  valueFormatter?: (value: number) => string;
  markers?: ChartMarker[];
  activeMarkerId?: string;
  onMarkerClick?: (marker: ChartMarker) => void;
  ariaLabel: string;
  zeroLine?: boolean;
}

const WIDTH = 800;
const PAD = { top: 18, right: 18, bottom: 28, left: 52 };

export function TimeSeriesChart({
  data,
  lines = [{ key: "value", label: "Value", color: "#47e6a4" }],
  height = 270,
  area = true,
  valueFormatter = (value) => value.toFixed(2),
  markers = [],
  activeMarkerId,
  onMarkerClick,
  ariaLabel,
  zeroLine = false,
}: TimeSeriesChartProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const gradientId = useId().replaceAll(":", "");
  const innerWidth = WIDTH - PAD.left - PAD.right;
  const innerHeight = height - PAD.top - PAD.bottom;

  const geometry = useMemo(() => {
    const visibleValues = data.flatMap((point) => lines
      .map((line) => point[line.key])
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value)));
    if (zeroLine) visibleValues.push(0);
    const rawMin = visibleValues.length ? Math.min(...visibleValues) : 0;
    const rawMax = visibleValues.length ? Math.max(...visibleValues) : 1;
    const span = rawMax - rawMin || 1;
    const min = rawMin - span * 0.08;
    const max = rawMax + span * 0.08;
    const start = data.length ? new Date(data[0].timestamp).getTime() : 0;
    const end = data.length ? new Date(data[data.length - 1].timestamp).getTime() : 1;
    const timeSpan = end - start || 1;
    const xForTime = (timestamp: string) => PAD.left + ((new Date(timestamp).getTime() - start) / timeSpan) * innerWidth;
    const yForValue = (value: number) => PAD.top + ((max - value) / (max - min)) * innerHeight;
    const paths = lines.map((line) => ({
      ...line,
      path: data.map((point, index) => {
        const value = point[line.key];
        if (typeof value !== "number") return "";
        return `${index === 0 ? "M" : "L"}${xForTime(point.timestamp).toFixed(2)},${yForValue(value).toFixed(2)}`;
      }).filter(Boolean).join(" "),
    }));
    return { min, max, xForTime, yForValue, paths };
  }, [data, innerHeight, innerWidth, lines, zeroLine]);

  if (!data.length) return <div className="chart-empty">No chart observations available.</div>;

  const gridValues = Array.from({ length: 5 }, (_, index) => geometry.max - ((geometry.max - geometry.min) / 4) * index);
  const dateTicks = [0, Math.floor((data.length - 1) / 3), Math.floor(((data.length - 1) * 2) / 3), data.length - 1];
  const hover = hoverIndex == null ? null : data[hoverIndex];
  const hoverX = hover ? geometry.xForTime(hover.timestamp) : 0;

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const chartX = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const ratio = Math.max(0, Math.min(1, (chartX - PAD.left) / innerWidth));
    setHoverIndex(Math.round(ratio * (data.length - 1)));
  };

  return (
    <div className="timeseries-wrap">
      <div className="chart-legend">
        {lines.map((line) => <span key={line.key}><i style={{ backgroundColor: line.color }} />{line.label}</span>)}
        {markers.length > 0 && <span><i className="marker-legend" />Trades</span>}
      </div>
      <svg
        className="timeseries-chart"
        viewBox={`0 0 ${WIDTH} ${height}`}
        role="img"
        aria-label={ariaLabel}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setHoverIndex(null)}
      >
        <defs>
          <linearGradient id={`${gradientId}-area`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={lines[0].color} stopOpacity="0.24" />
            <stop offset="1" stopColor={lines[0].color} stopOpacity="0" />
          </linearGradient>
          <filter id={`${gradientId}-glow`}><feGaussianBlur stdDeviation="3" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        {gridValues.map((value) => {
          const y = geometry.yForValue(value);
          return <g key={value}><line className="chart-grid" x1={PAD.left} x2={WIDTH - PAD.right} y1={y} y2={y} /><text className="chart-axis" x={PAD.left - 9} y={y + 4} textAnchor="end">{valueFormatter(value)}</text></g>;
        })}
        {dateTicks.map((index) => <text key={index} className="chart-axis" x={geometry.xForTime(data[index].timestamp)} y={height - 6} textAnchor={index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"}>{compactDate(data[index].timestamp)}</text>)}
        {zeroLine && geometry.min <= 0 && geometry.max >= 0 && <line className="chart-zero" x1={PAD.left} x2={WIDTH - PAD.right} y1={geometry.yForValue(0)} y2={geometry.yForValue(0)} />}
        {area && geometry.paths[0]?.path && (
          <path d={`${geometry.paths[0].path} L${geometry.xForTime(data.at(-1)!.timestamp)},${PAD.top + innerHeight} L${geometry.xForTime(data[0].timestamp)},${PAD.top + innerHeight} Z`} fill={`url(#${gradientId}-area)`} />
        )}
        {geometry.paths.map((line) => <path key={line.key} d={line.path} fill="none" stroke={line.color} strokeWidth={line.key === "value" ? 2.5 : 1.5} strokeDasharray={line.dashed ? "6 5" : undefined} vectorEffect="non-scaling-stroke" />)}
        {markers.map((marker) => {
          const x = geometry.xForTime(marker.timestamp);
          const y = geometry.yForValue(marker.value);
          return (
            <g key={marker.id} className={`trade-marker ${activeMarkerId === marker.id ? "active" : ""}`} role="button" tabIndex={0} aria-label={`${marker.label}, ${valueFormatter(marker.value)}`} onClick={(event) => { event.stopPropagation(); onMarkerClick?.(marker); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onMarkerClick?.(marker); }}>
              <circle cx={x} cy={y} r={activeMarkerId === marker.id ? 7 : 5} fill={marker.positive ? "#47e6a4" : "#ff6b7a"} stroke="#07110f" strokeWidth="2" />
              <path d={marker.direction === "LONG" ? `M${x - 3},${y + 1} L${x},${y - 3} L${x + 3},${y + 1}` : `M${x - 3},${y - 1} L${x},${y + 3} L${x + 3},${y - 1}`} stroke="#07110f" strokeWidth="1.4" fill="none" />
            </g>
          );
        })}
        {hover && (
          <g className="chart-hover">
            <line x1={hoverX} x2={hoverX} y1={PAD.top} y2={PAD.top + innerHeight} />
            {lines.map((line) => {
              const value = hover[line.key];
              return typeof value === "number" ? <circle key={line.key} cx={hoverX} cy={geometry.yForValue(value)} r="4" fill={line.color} stroke="#07110f" strokeWidth="2" /> : null;
            })}
          </g>
        )}
      </svg>
      {hover && (
        <div className="chart-tooltip" style={{ left: `${Math.max(7, Math.min(79, (hoverX / WIDTH) * 100))}%` }}>
          <strong>{compactDate(hover.timestamp)}</strong>
          {lines.map((line) => typeof hover[line.key] === "number" && <span key={line.key}><i style={{ backgroundColor: line.color }} />{line.label}<b>{valueFormatter(hover[line.key] as number)}</b></span>)}
        </div>
      )}
    </div>
  );
}
