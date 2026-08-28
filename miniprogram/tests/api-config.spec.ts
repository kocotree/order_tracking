import { describe, expect, it } from "vitest";

import { apiBaseUrlFor, SUBSCRIPTION_TEMPLATE_IDS } from "../api/config";

describe("mini program API environment", () => {
  it("selects an explicit API base URL for each WeChat environment", () => {
    expect(apiBaseUrlFor("develop")).toBe("http://127.0.0.1:8000/api/v1");
    expect(apiBaseUrlFor("trial")).toBe("https://api.example.invalid/api/v1");
    expect(apiBaseUrlFor("release")).toBe("https://api.example.invalid/api/v1");
  });

  it("uses the four templates selected in the WeChat admin console", () => {
    expect(SUBSCRIPTION_TEMPLATE_IDS).toEqual({
      admin_shipment: "qsM0bwEFQkMATPv-dPgwgtKw8XWdC8vJgfx5J8yqCNo",
      admin_repair: "gpFZ93n6vLFKUU5aCISc2CizJiCymGfKKTfl0e9HO6g",
      factory_status: "cSEC8Q5PUVz6NdcESpp-J4CGMLS8dScIK0CqsPRLzzY",
      factory_due: "GHS9jvL74feBeckR1W-J-xD-udAgXbGpoHIjgSsnKLw",
      factory_repair: "gpFZ93n6vLFKUU5aCISc2CizJiCymGfKKTfl0e9HO6g",
    });
  });
});
