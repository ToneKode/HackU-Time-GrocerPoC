import { describe, expect, it } from "vitest";
import { cartItemsPayload, formatHkd, truncate } from "./format.js";

describe("formatHkd", () => {
  it("formats to two decimals with HK$ prefix", () => {
    expect(formatHkd(89.9)).toBe("HK$89.90");
    expect(formatHkd(0)).toBe("HK$0.00");
  });

  it("handles invalid numbers", () => {
    expect(formatHkd(NaN)).toBe("HK$—");
  });
});

describe("truncate", () => {
  it("leaves short strings alone", () => {
    expect(truncate("hello", 10)).toBe("hello");
  });

  it("truncates long strings with ellipsis", () => {
    expect(truncate("abcdefghij", 5)).toBe("abcd…");
  });
});

describe("cartItemsPayload", () => {
  it("converts cart map to API items and drops zero qty", () => {
    expect(
      cartItemsPayload({ SKU001: 2, SKU002: 0, SKU003: 1 }),
    ).toEqual([
      { sku: "SKU001", qty: 2 },
      { sku: "SKU003", qty: 1 },
    ]);
  });
});
