import { describe, expect, it } from "vitest";

import { formatShanghaiDateTime } from "../utils/date-time";

describe("Shanghai date-time formatting", () => {
  it("formats UTC, explicit offsets, and API timestamps without offsets consistently", () => {
    expect(formatShanghaiDateTime("2026-09-05T08:30:00Z")).toBe("2026-09-05 16:30");
    expect(formatShanghaiDateTime("2026-09-05T16:30:00+08:00")).toBe("2026-09-05 16:30");
    expect(formatShanghaiDateTime("2026-09-05T08:30:00.123456")).toBe("2026-09-05 16:30");
    expect(formatShanghaiDateTime("2026-08-21 10:30")).toBe("2026-08-21 10:30");
  });

  it("returns a safe placeholder for missing or invalid values", () => {
    expect(formatShanghaiDateTime(null)).toBe("—");
    expect(formatShanghaiDateTime("")).toBe("—");
    expect(formatShanghaiDateTime("not-a-date")).toBe("—");
    expect(formatShanghaiDateTime("2026-02-30T08:30:00Z")).toBe("—");
    expect(formatShanghaiDateTime("2026-09-05T08:30:00+14:30")).toBe("—");
  });
});
