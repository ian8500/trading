import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TimeSeriesChart } from "../src/charts/TimeSeriesChart";

describe("TimeSeriesChart", () => {
  it("exposes interactive trade markers to keyboard and pointer users", async () => {
    const user = userEvent.setup();
    const selected = vi.fn();
    render(<TimeSeriesChart
      data={[{ timestamp: "2026-01-01T00:00:00Z", value: 500 }, { timestamp: "2026-01-02T00:00:00Z", value: 512 }]}
      markers={[{ id: "trade-1", timestamp: "2026-01-02T00:00:00Z", value: 512, direction: "LONG", label: "GBP/USD winner", positive: true }]}
      onMarkerClick={selected}
      ariaLabel="Test equity curve"
    />);
    expect(screen.getByRole("img", { name: "Test equity curve" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /GBP\/USD winner/ }));
    expect(selected).toHaveBeenCalledWith(expect.objectContaining({ id: "trade-1" }));
  });
});
