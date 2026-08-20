import { describe, expect, it } from "vitest";

import { apiBaseUrlFor } from "../api/config";

describe("mini program API environment", () => {
  it("selects an explicit API base URL for each WeChat environment", () => {
    expect(apiBaseUrlFor("develop")).toBe("http://127.0.0.1:8000/api/v1");
    expect(apiBaseUrlFor("trial")).toBe("https://api.example.invalid/api/v1");
    expect(apiBaseUrlFor("release")).toBe("https://api.example.invalid/api/v1");
  });
});
