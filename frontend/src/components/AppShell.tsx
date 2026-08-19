import { useEffect, useState, type ReactNode } from "react";
import { useApi } from "../context/ApiContext";
import { Icon, type IconName } from "./Icon";
import { StatusPill } from "./Primitives";

export interface RouteItem {
  path: string;
  label: string;
  icon: IconName;
}

export const routes: RouteItem[] = [
  { path: "/", label: "Overview", icon: "overview" },
  { path: "/opportunities", label: "Opportunities", icon: "opportunities" },
  { path: "/positions", label: "Positions", icon: "positions" },
  { path: "/backtests", label: "Backtests", icon: "backtests" },
  { path: "/replay", label: "Replay", icon: "replay" },
  { path: "/strategies", label: "Strategies", icon: "strategies" },
  { path: "/events", label: "Events", icon: "events" },
  { path: "/ig-demo", label: "IG Demo", icon: "broker" },
  { path: "/risk", label: "Risk", icon: "risk" },
  { path: "/live-readiness", label: "Live Readiness", icon: "readiness" },
  { path: "/system", label: "System", icon: "system" },
];

export function AppShell({ children, path, navigate }: { children: ReactNode; path: string; navigate: (path: string) => void }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { availability, lastError, checkConnection } = useApi();

  useEffect(() => setMobileOpen(false), [path]);

  const go = (event: React.MouseEvent<HTMLAnchorElement>, target: string) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(target);
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? "mobile-open" : ""}`}>
        <div className="brand-block">
          <div className="brand-mark"><span /><span /><span /></div>
          <div><strong>Northstar</strong><span>Trading intelligence</span></div>
          <button type="button" className="sidebar-close" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><Icon name="close" /></button>
        </div>
        <nav aria-label="Primary navigation">
          {routes.map((route) => {
            const active = path === route.path;
            return (
              <a key={route.path} href={route.path} className={active ? "active" : ""} aria-current={active ? "page" : undefined} onClick={(event) => go(event, route.path)}>
                <Icon name={route.icon} />
                <span>{route.label}</span>
                {route.path === "/risk" && <i className="nav-health" />}
              </a>
            );
          })}
        </nav>
        <div className="sidebar-safety">
          <div className="safety-lock"><Icon name="lock" /><span>Live trading</span><strong>Disabled</strong></div>
          <p>V1 is restricted to research, replay, simulation, and IG Demo.</p>
        </div>
        <div className="sidebar-footer"><span>Managed allocation</span><strong>£500.00</strong><small>Broker balance is never the sizing base</small></div>
      </aside>
      {mobileOpen && <button className="nav-scrim" type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <div className="main-column">
        <div className="global-bar">
          <button type="button" className="mobile-menu" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Icon name="menu" /></button>
          <div className="global-status">
            <StatusPill tone="info">Historical research</StatusPill>
            <span className="bar-divider" />
            <span className="desktop-only">Europe/London</span>
          </div>
          <div className="global-actions">
            <StatusPill tone={availability === "online" ? "positive" : availability === "checking" ? "neutral" : "warning"}>
              {availability === "online" ? "Backend online" : availability === "checking" ? "Checking backend" : "Backend offline"}
            </StatusPill>
            <StatusPill tone="neutral">Demo off</StatusPill>
            <StatusPill tone="negative">Live disabled</StatusPill>
          </div>
        </div>
        {availability === "offline" && (
          <div className="offline-banner" role="status">
            <div><Icon name="alert" /><span><strong>Backend unavailable.</strong> Displaying clearly labelled local demo data. Broker and risk controls remain fail-closed.{lastError ? ` ${lastError}` : ""}</span></div>
            <button type="button" onClick={() => void checkConnection()}><Icon name="refresh" size={15} /> Retry</button>
          </div>
        )}
        <main className="page-content">{children}</main>
      </div>
    </div>
  );
}
