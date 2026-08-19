import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { formatDateTime } from "../utils/format";

export type Tone = "positive" | "negative" | "warning" | "neutral" | "info" | "purple";

export function StatusPill({ children, tone = "neutral", dot = true }: { children: ReactNode; tone?: Tone; dot?: boolean }) {
  return <span className={`status-pill tone-${tone}`}>{dot && <span className="status-dot" />}{children}</span>;
}

export function Panel({
  children,
  title,
  eyebrow,
  actions,
  className = "",
  flush = false,
}: {
  children: ReactNode;
  title?: ReactNode;
  eyebrow?: string;
  actions?: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`panel ${flush ? "panel-flush" : ""} ${className}`}>
      {(title || actions) && (
        <div className="panel-heading">
          <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}{title && <h2>{title}</h2>}</div>
          {actions && <div className="panel-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  tone = "neutral",
  icon,
  progress,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  progress?: number;
}) {
  return (
    <article className={`metric-card tone-border-${tone}`}>
      <div className="metric-topline"><span>{label}</span>{icon}</div>
      <div className={`metric-value text-${tone}`}>{value}</div>
      {detail && <div className="metric-detail">{detail}</div>}
      {progress != null && <div className="progress-track"><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></div>}
    </article>
  );
}

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
}: {
  title: string;
  description: string;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1><p>{description}</p></div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function SourceBadge({ source, loading, onRefresh }: { source: "api" | "demo"; loading: boolean; onRefresh: () => void }) {
  return (
    <div className="source-control">
      <StatusPill tone={source === "api" ? "positive" : "warning"}>
        {source === "api" ? "Live backend data" : "Offline demo data"}
      </StatusPill>
      <button className="icon-button" type="button" aria-label="Refresh data" disabled={loading} onClick={onRefresh}>
        <Icon name="refresh" className={loading ? "spin" : undefined} />
      </button>
    </div>
  );
}

export function InlineNotice({ tone = "info", title, children }: { tone?: Tone; title: string; children: ReactNode }) {
  return (
    <div className={`inline-notice notice-${tone}`}>
      <Icon name={tone === "positive" ? "check" : "alert"} />
      <div><strong>{title}</strong><p>{children}</p></div>
    </div>
  );
}

export function DataTimestamp({ value, prefix = "Updated" }: { value: string; prefix?: string }) {
  return <span className="data-timestamp"><Icon name="clock" size={14} /> {prefix} {formatDateTime(value)}</span>;
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  return (
    <div className="progress-block">
      {label && <div className="progress-label"><span>{label}</span><strong>{Math.round(value)}%</strong></div>}
      <div className="progress-track"><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><Icon name="system" size={30} /><strong>{title}</strong><p>{detail}</p></div>;
}

export function Toggle({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (checked: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <label className={`toggle ${disabled ? "is-disabled" : ""}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span className="toggle-track"><span /></span>
      <span>{label}</span>
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: readonly T[]; onChange: (value: T) => void; label: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button key={option} type="button" className={value === option ? "active" : ""} onClick={() => onChange(option)}>{option}</button>
      ))}
    </div>
  );
}
