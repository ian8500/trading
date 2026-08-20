import { useCallback, useEffect, useState } from "react";
import { AppShell, routes } from "./components/AppShell";
import { AutopilotPage } from "./pages/AutopilotPage";
import { BacktestsPage } from "./pages/BacktestsPage";
import { EventsPage } from "./pages/EventsPage";
import { IgDemoPage } from "./pages/IgDemoPage";
import { LiveReadinessPage } from "./pages/LiveReadinessPage";
import { OpportunitiesPage } from "./pages/OpportunitiesPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PositionsPage } from "./pages/PositionsPage";
import { ReplayPage } from "./pages/ReplayPage";
import { ResultsPage } from "./pages/ResultsPage";
import { RiskPage } from "./pages/RiskPage";
import { StrategiesPage } from "./pages/StrategiesPage";
import { SystemPage } from "./pages/SystemPage";

const pageByPath: Record<string, React.ComponentType> = {
  "/": AutopilotPage,
  "/results": ResultsPage,
  "/advanced/overview": OverviewPage,
  "/opportunities": OpportunitiesPage,
  "/positions": PositionsPage,
  "/backtests": BacktestsPage,
  "/replay": ReplayPage,
  "/strategies": StrategiesPage,
  "/events": EventsPage,
  "/ig-demo": IgDemoPage,
  "/risk": RiskPage,
  "/live-readiness": LiveReadinessPage,
  "/system": SystemPage,
};

function normalisePath(path: string): string {
  const clean = path.replace(/\/+$/, "") || "/";
  return routes.some((route) => route.path === clean) ? clean : "/";
}

export default function App() {
  const [path, setPath] = useState(() => normalisePath(window.location.pathname));

  useEffect(() => {
    const onPopState = () => setPath(normalisePath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((nextPath: string) => {
    const normalised = normalisePath(nextPath);
    if (normalised !== window.location.pathname) window.history.pushState({}, "", normalised);
    setPath(normalised);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const Page = pageByPath[path] ?? AutopilotPage;
  return <AppShell path={path} navigate={navigate}><Page /></AppShell>;
}
