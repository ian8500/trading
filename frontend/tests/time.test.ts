import { describe, expect, it } from "vitest";
import { londonLocalDateTimeToUtcIso } from "../src/utils/time";

describe("londonLocalDateTimeToUtcIso", () => {
  it("applies GMT in winter and BST in summer", () => {
    expect(londonLocalDateTimeToUtcIso("2026-01-15T07:00")).toBe("2026-01-15T07:00:00.000Z");
    expect(londonLocalDateTimeToUtcIso("2026-05-11T07:00")).toBe("2026-05-11T06:00:00.000Z");
  });

  it("rejects a skipped spring clock-change time", () => {
    expect(() => londonLocalDateTimeToUtcIso("2026-03-29T01:30")).toThrow(/does not exist/);
  });

  it("uses the first occurrence of a repeated autumn time", () => {
    expect(londonLocalDateTimeToUtcIso("2026-10-25T01:30")).toBe("2026-10-25T00:30:00.000Z");
  });
});
