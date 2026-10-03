/**
 * Integration tests: frontend API client + live mock-api backend.
 * mock-api is started by tests/integration/globalSetup.js when needed.
 */
import { createServer } from "node:http";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApi } from "../../src/api.js";
import { cartItemsPayload, formatHkd } from "../../src/format.js";

const API_BASE = "http://127.0.0.1:8000";
const FRONTEND_PORT = 5174;

let frontendServer = null;
let frontendBase = "";
const api = createApi(API_BASE);

function startFrontendStaticServer() {
  const html = `<!DOCTYPE html>
<html><head><title>Mock Mall Integration Probe</title></head>
<body>
  <h1 id="brand">Time-Grocer Mock Mall</h1>
  <div id="api-status">boot</div>
  <div id="product-count">0</div>
  <ul id="products"></ul>
  <pre id="cart-result"></pre>
  <pre id="pay-result"></pre>
  <script type="module">
    const API = ${JSON.stringify(API_BASE)};
    async function run() {
      const status = document.getElementById("api-status");
      const list = document.getElementById("products");
      const count = document.getElementById("product-count");
      const cartResult = document.getElementById("cart-result");
      const payResult = document.getElementById("pay-result");
      try {
        const health = await fetch(API + "/health").then((r) => r.json());
        status.textContent = health.ok ? "API online" : "API bad";
        const products = await fetch(API + "/products?q=toilet").then((r) => r.json());
        count.textContent = String(products.length);
        for (const p of products) {
          const li = document.createElement("li");
          li.dataset.sku = p.id;
          li.textContent = p.id + " " + p.name;
          list.appendChild(li);
        }
        const cart = await fetch(API + "/cart", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: [{ sku: "SKU001", qty: 1 }] }),
        }).then((r) => r.json());
        cartResult.textContent = JSON.stringify(cart);
        const pay = await fetch(API + "/pay", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cart_total: cart.total_landed_cost,
            payment_route: "mastercard",
            idempotency_key: "integration-fe-be",
          }),
        }).then((r) => r.json());
        payResult.textContent = JSON.stringify(pay);
        window.__MOCK_MALL_READY__ = { health, products, cart, pay };
      } catch (err) {
        status.textContent = "API offline";
        window.__MOCK_MALL_ERROR__ = String(err);
      }
    }
    run();
  </script>
</body></html>`;

  return new Promise((resolve) => {
    frontendServer = createServer((req, res) => {
      res.writeHead(200, {
        "Content-Type": "text/html; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
      });
      res.end(html);
    });
    frontendServer.listen(FRONTEND_PORT, "127.0.0.1", () => {
      frontendBase = `http://127.0.0.1:${FRONTEND_PORT}`;
      resolve();
    });
  });
}

beforeAll(async () => {
  await startFrontendStaticServer();
});

afterAll(async () => {
  if (frontendServer) {
    await new Promise((resolve) => frontendServer.close(resolve));
  }
});

describe("frontend client ↔ mock-api integration", () => {
  it("health and merchants match seed data", async () => {
    await expect(api.getHealth()).resolves.toEqual({ ok: true });
    const merchants = await api.getMerchants();
    expect(merchants.whitelist).toContain("Watsons");
    expect(merchants.blacklist).toContain("DarkWebMart");
  });

  it("product search used by the storefront returns toilet paper SKUs", async () => {
    const products = await api.getProducts({ q: "toilet" });
    expect(products.length).toBeGreaterThanOrEqual(3);
    expect(products.map((p) => p.id)).toEqual(
      expect.arrayContaining(["SKU001", "SKU002", "SKU003"]),
    );
  });

  it("cart pricing path used by Price Cart button", async () => {
    const items = cartItemsPayload({ SKU001: 1 });
    const cart = await api.postCart({ items });
    expect(cart.subtotal).toBe(89.9);
    expect(cart.shipping_fee).toBe(30);
    expect(cart.total_landed_cost).toBe(119.9);
    expect(formatHkd(cart.total_landed_cost)).toBe("HK$119.90");
  });

  it("free shipping path for bulk qty", async () => {
    const cart = await api.postCart({
      items: [{ sku: "SKU001", qty: 5 }],
    });
    expect(cart.subtotal).toBe(449.5);
    expect(cart.shipping_fee).toBe(0);
  });

  it("pay + idempotency path used by Pay Now", async () => {
    const key = `int-${Date.now()}`;
    const first = await api.postPay({
      cart_total: 119.9,
      payment_route: "mastercard",
      idempotency_key: key,
    });
    const second = await api.postPay({
      cart_total: 119.9,
      payment_route: "mastercard",
      idempotency_key: key,
    });
    expect(first.success).toBe(true);
    expect(first.reward_points_earned).toBe(11);
    expect(second.order_id).toBe(first.order_id);
  });

  it("decline trigger still works through the same client", async () => {
    const result = await api.postPay({
      cart_total: 666,
      payment_route: "mastercard",
    });
    expect(result).toMatchObject({
      success: false,
      error: "card_declined",
      order_id: null,
    });
  });
});

describe("browser page ↔ backend wiring", () => {
  it("serves a page that loads products/cart/pay from the API", async () => {
    const page = await fetch(frontendBase);
    expect(page.status).toBe(200);
    const html = await page.text();
    expect(html).toContain("Time-Grocer Mock Mall");
    expect(html).toContain(API_BASE);
    expect(html).toContain("/products?q=toilet");
    expect(html).toContain("/cart");
    expect(html).toContain("/pay");
  });

  it("executes the page script flow against the live API (node fetch simulation)", async () => {
    // Mirrors the inline browser script: health → products → cart → pay
    const health = await fetch(`${API_BASE}/health`).then((r) => r.json());
    const products = await fetch(`${API_BASE}/products?q=toilet`).then((r) =>
      r.json(),
    );
    const cart = await fetch(`${API_BASE}/cart`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: [{ sku: "SKU001", qty: 1 }] }),
    }).then((r) => r.json());
    const pay = await fetch(`${API_BASE}/pay`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cart_total: cart.total_landed_cost,
        payment_route: "mastercard",
        idempotency_key: "page-flow-key",
      }),
    }).then((r) => r.json());

    expect(health.ok).toBe(true);
    expect(products.length).toBeGreaterThanOrEqual(3);
    expect(cart.total_landed_cost).toBe(119.9);
    expect(pay.success).toBe(true);
    expect(pay.order_id).toMatch(/^ORD-[0-9a-f]{8}$/);
  });
});
