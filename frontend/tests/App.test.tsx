import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { ApiProvider } from "../src/context/ApiContext";
import { demoBacktests, demoReplay } from "../src/data/demo";

function renderAt(path: string) {
  window.history.replaceState({}, "", path);
  return render(<ApiProvider><App /></ApiProvider>);
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
}

describe("trading dashboard", () => {
  beforeEach(() => {
    document.cookie = "csrf_token=; Max-Age=0; path=/";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("connection refused")));
  });

  it("shows the managed-capital overview and explicit offline safety state", async () => {
    renderAt("/");
    expect(screen.getByRole("heading", { name: "Portfolio overview" })).toBeInTheDocument();
    expect(screen.getByText("£500.00", { selector: ".metric-value" })).toBeInTheDocument();
    expect(screen.getByText("£551.10", { selector: ".metric-value" })).toBeInTheDocument();
    expect(await screen.findByText(/Backend unavailable\./)).toBeInTheDocument();
    expect(screen.getByText("Live disabled", { selector: ".status-pill" })).toBeInTheDocument();
  });

  it("navigates without reloading and filters the opportunity audit table", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await user.click(screen.getByRole("link", { name: "Opportunities" }));
    expect(screen.getByRole("heading", { name: "Opportunity leaderboard" })).toBeInTheDocument();
    const search = screen.getByRole("textbox", { name: "Search opportunities" });
    await user.type(search, "Bitcoin");
    expect(screen.getByText("Bitcoin", { selector: "td strong" })).toBeInTheDocument();
    expect(screen.queryByText("NASDAQ 100", { selector: "td strong" })).not.toBeInTheDocument();
  });

  it("advances the historical replay one chronological tick", async () => {
    const user = userEvent.setup();
    renderAt("/replay");
    expect(screen.getByText("Tick 1 / 140")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Step forward" }));
    expect(screen.getByText("Tick 2 / 140")).toBeInTheDocument();
  });

  it("does not pretend an offline backtest submission succeeded", async () => {
    const user = userEvent.setup();
    renderAt("/backtests");
    await user.click(screen.getByRole("button", { name: "Run backtest" }));
    const dialog = screen.getByRole("dialog", { name: "Run historical backtest" });
    await user.type(within(dialog).getByLabelText("Password"), "local-test-only");
    await user.click(within(dialog).getByRole("button", { name: "Run backtest" }));
    await waitFor(() => expect(within(dialog).getByText(/No control command was sent/)).toBeInTheDocument());
    expect(screen.getAllByText(/synthetic, not a research result/i)).toHaveLength(2);
  });

  it("keeps reachable authentication errors online and announces them", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.endsWith("/health")) return jsonResponse({ status: "ok" });
      if (url.includes("/backtests?")) return jsonResponse(demoBacktests);
      if (url.endsWith("/auth/login") && init?.method === "POST") {
        return jsonResponse({ detail: "invalid credentials" }, 401);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));

    const user = userEvent.setup();
    renderAt("/backtests");
    expect(await screen.findByText("Backend online", { selector: ".status-pill" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run backtest" }));
    const dialog = screen.getByRole("dialog", { name: "Run historical backtest" });
    await user.type(within(dialog).getByLabelText("Password"), "incorrect");
    await user.click(within(dialog).getByRole("button", { name: "Run backtest" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Authentication failed");
    expect(screen.getByText("Backend online", { selector: ".status-pill" })).toBeInTheDocument();
    expect(screen.queryByText(/Displaying clearly labelled local demo data/)).not.toBeInTheDocument();
  });

  it("adopts the exact successful backtest response without a refresh", async () => {
    const completed = {
      ...demoBacktests[0],
      id: "bt-api-return",
      name: "Exact API backtest result",
      dataSource: "Pinned Yahoo Finance manifest from API",
      metrics: { ...demoBacktests[0].metrics, finalEquity: 612.34 },
    };
    let backtestGetCount = 0;
    let actionRequest: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.endsWith("/health")) return jsonResponse({ status: "ok" });
      if (url.includes("/backtests?")) {
        backtestGetCount += 1;
        return jsonResponse([demoBacktests[0]]);
      }
      if (url.endsWith("/auth/login") && init?.method === "POST") {
        document.cookie = "csrf_token=csrf-test-token; path=/";
        return jsonResponse({ authenticated: true, username: "admin" });
      }
      if (url.endsWith("/backtests") && init?.method === "POST") {
        actionRequest = init;
        return jsonResponse(completed);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));

    const user = userEvent.setup();
    renderAt("/backtests");
    expect(await screen.findByText("Live backend data")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Compound realised P&L (required)" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Run backtest" }));
    const dialog = screen.getByRole("dialog", { name: "Run historical backtest" });
    await user.type(within(dialog).getByLabelText("Password"), "correct");
    await user.click(within(dialog).getByRole("button", { name: "Run backtest" }));

    expect(await within(dialog).findByRole("status")).toHaveTextContent("Command accepted");
    expect(screen.getByRole("heading", { name: "Exact API backtest result" })).toBeInTheDocument();
    expect(screen.getByText("£612.34", { selector: ".metric-value" })).toBeInTheDocument();
    expect(screen.getByText(/displaying the exact result returned by the backend/i)).toBeInTheDocument();
    expect(backtestGetCount).toBe(1);
    expect(new Headers(actionRequest?.headers).get("X-CSRF-Token")).toBe("csrf-test-token");
    expect(JSON.parse(String(actionRequest?.body))).toEqual(expect.objectContaining({ compounding: true, resolution: "1d" }));
  });

  it("submits London replay times as UTC and adopts the returned session", async () => {
    const returnedReplay = {
      ...demoReplay,
      id: "replay-api-return",
      startingCapital: 700,
      ticks: [
        { ...demoReplay.ticks[0], managedEquity: 777 },
        ...demoReplay.ticks.slice(1),
      ],
    };
    let replayGetCount = 0;
    let actionRequest: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.endsWith("/health")) return jsonResponse({ status: "ok" });
      if (url.endsWith("/replay/sessions/latest")) {
        replayGetCount += 1;
        return jsonResponse(demoReplay);
      }
      if (url.endsWith("/auth/login") && init?.method === "POST") {
        document.cookie = "csrf_token=replay-csrf-token; path=/";
        return jsonResponse({ authenticated: true, username: "admin" });
      }
      if (url.endsWith("/replay/sessions") && init?.method === "POST") {
        actionRequest = init;
        return jsonResponse(returnedReplay);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));

    const user = userEvent.setup();
    renderAt("/replay");
    expect(await screen.findByText("Live backend data")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load replay" }));
    const dialog = screen.getByRole("dialog", { name: "Create historical replay" });
    await user.type(within(dialog).getByLabelText("Password"), "correct");
    await user.click(within(dialog).getByRole("button", { name: "Load replay" }));

    expect(await within(dialog).findByRole("status")).toHaveTextContent("Command accepted");
    expect(screen.getByText("£777.00", { selector: ".metric-value" })).toBeInTheDocument();
    expect(screen.getByText(/displaying the exact session returned by the backend/i)).toBeInTheDocument();
    expect(replayGetCount).toBe(1);
    expect(JSON.parse(String(actionRequest?.body))).toEqual(expect.objectContaining({
      start: "2026-05-11T06:00:00.000Z",
      end: "2026-05-17T01:00:00.000Z",
    }));
  });

  it("opens a complete opportunity decision trail from the leaderboard", async () => {
    const user = userEvent.setup();
    renderAt("/opportunities");
    const row = screen.getByText("NASDAQ 100", { selector: "td strong" }).closest("tr");
    expect(row).not.toBeNull();
    await user.click(row!);
    expect(screen.getByRole("dialog", { name: "NASDAQ 100 LONG" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "NASDAQ 100 LONG" })).getByText("Inspect score composition")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "NASDAQ 100 LONG" })).getByText(/No hard rejection conditions/)).toBeInTheDocument();
  });

  it("keeps an authenticated Demo control fail-closed when the backend is absent", async () => {
    const user = userEvent.setup();
    renderAt("/ig-demo");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    const dialog = screen.getByRole("dialog", { name: "Connect" });
    await user.type(within(dialog).getByLabelText("Password"), "local-test-only");
    await user.click(within(dialog).getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(within(dialog).getByText(/No control command was sent/)).toBeInTheDocument());
  });
});
