/**
 * JSDOM integration: real storefront HTML + live mock-api responses
 * through the same api.js client the UI uses.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { beforeAll, describe, expect, it } from "vitest";
import { createApi } from "../../src/api.js";
import { cartItemsPayload, formatHkd, truncate } from "../../src/format.js";

const API_BASE = "http://127.0.0.1:8000";
const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const api = createApi(API_BASE);

beforeAll(async () => {
  const start = Date.now();
  while (Date.now() - start < 15000) {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) return;
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("mock-api not reachable on :8000 for DOM integration tests");
});

describe("storefront DOM contract", () => {
  it("index.html exposes the controls wired in main.js", () => {
    const html = readFileSync(join(root, "index.html"), "utf8");
    const dom = new JSDOM(html);
    const { document } = dom.window;

    for (const id of [
      "api-status",
      "search-form",
      "q",
      "merchant",
      "category",
      "product-grid",
      "cart-lines",
      "price-cart",
      "pay-now",
      "payment-route",
      "idempotency-key",
      "pay-result",
      "whitelist",
      "blacklist",
    ]) {
      expect(document.getElementById(id), `missing #${id}`).toBeTruthy();
    }

    expect(html).toContain("/src/main.js");
    expect(document.querySelector(".brand")?.textContent).toContain(
      "Time-Grocer Mock Mall",
    );
  });
});

describe("UI helpers + live API (full front/back path)", () => {
  it("search → cart → pay mirrors the button flow", async () => {
    const products = await api.getProducts({ q: "toilet" });
    expect(products.length).toBeGreaterThanOrEqual(3);

    const labels = products.map((p) => truncate(p.name, 90));
    expect(labels[0].length).toBeGreaterThan(0);

    const cartMap = { [products[0].id]: 1 };
    const items = cartItemsPayload(cartMap);
    const cart = await api.postCart({ items });
    expect(formatHkd(cart.total_landed_cost)).toBe("HK$119.90");

    const pay = await api.postPay({
      cart_total: cart.total_landed_cost,
      payment_route: "mastercard",
      idempotency_key: "dom-wiring-key",
    });
    expect(pay.success).toBe(true);
    expect(pay.payment_route).toBe("mastercard");
    expect(pay.order_id).toMatch(/^ORD-/);
  });
});
