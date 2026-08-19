import type { ReactNode } from "react";

export type IconName =
  | "overview" | "opportunities" | "positions" | "backtests" | "replay" | "strategies"
  | "events" | "broker" | "risk" | "readiness" | "system" | "refresh" | "search"
  | "chevron" | "close" | "play" | "pause" | "step" | "download" | "lock"
  | "alert" | "check" | "clock" | "target" | "menu" | "arrow" | "filter";

const paths: Record<IconName, ReactNode> = {
  overview: <><path d="M4 13h6V4H4v9Zm0 7h6v-4H4v4Zm10 0h6v-9h-6v9Zm0-16v4h6V4h-6Z" /></>,
  opportunities: <><path d="M12 3v18M3 12h18" /><circle cx="12" cy="12" r="6" /></>,
  positions: <><path d="m4 18 5-6 4 3 7-9" /><path d="M16 6h4v4" /></>,
  backtests: <><path d="M4 19V9m5 10V5m5 14v-7m5 7V3" /></>,
  replay: <><path d="M4 12a8 8 0 1 0 2.34-5.66L4 8.68" /><path d="M4 4v4.68h4.68M10 8l6 4-6 4V8Z" /></>,
  strategies: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1V21H9.6v-.08A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.6-1H3v-4h.08A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V3h4v.08A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.12.4.35.75.67 1H21v4h-.08A1.7 1.7 0 0 0 19.4 15Z" /></>,
  events: <><path d="M5 4v16m14-16v16M3 8h18M3 20h18M8 3v3m8-3v3" /></>,
  broker: <><path d="M3 10h18L12 4 3 10Zm2 2v6m5-6v6m4-6v6m5-6v6M3 20h18" /></>,
  risk: <><path d="M12 3 4 6v5c0 5 3.4 8.5 8 10 4.6-1.5 8-5 8-10V6l-8-3Z" /><path d="M12 8v5m0 3h.01" /></>,
  readiness: <><path d="M4 12 9 17 20 6" /><path d="M21 12a9 9 0 1 1-5.3-8.2" /></>,
  system: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9h.01M11 9h6M7 13h.01M11 13h6M7 17h.01M11 17h6" /></>,
  refresh: <><path d="M20 11a8 8 0 1 0-2.34 5.66L20 14.32" /><path d="M20 20v-5.68h-5.68" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  chevron: <path d="m9 18 6-6-6-6" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  play: <path d="m8 5 11 7-11 7V5Z" />,
  pause: <path d="M8 5v14m8-14v14" />,
  step: <path d="m6 5 9 7-9 7V5Zm11 0v14" />,
  download: <><path d="M12 3v12m-5-5 5 5 5-5" /><path d="M4 19h16" /></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
  alert: <><path d="M12 3 2.7 20h18.6L12 3Z" /><path d="M12 9v5m0 3h.01" /></>,
  check: <path d="m4 12 5 5L20 6" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  target: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4" /><path d="M12 3v2m0 14v2M3 12h2m14 0h2" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  filter: <path d="M4 5h16l-6 7v6l-4 2v-8L4 5Z" />,
};

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  );
}
