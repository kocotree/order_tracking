import { expect, it } from "vitest";
import { formatQuantity } from "../modules/orders/format";

it("keeps unknown quantities distinct from zero", () => {
  expect(formatQuantity(null)).toBe("—");
  expect(formatQuantity(0)).toBe("0");
  expect(formatQuantity(1150)).toBe("1,150");
});
