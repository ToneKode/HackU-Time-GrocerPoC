/**
 * HTTP client for Person 4 mock-api (localhost:8000).
 * Uses VITE_API_BASE when set; otherwise /api (Vite proxy) in browser,
 * or http://127.0.0.1:8000 in Node/integration tests.
 */

function defaultBaseUrl() {
  if (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE) {
    return String(import.meta.env.VITE_API_BASE).replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    return "/api";
  }
  return "http://127.0.0.1:8000";
}

export function createApi(baseUrl = defaultBaseUrl(), fetchImpl = fetch) {
  const root = String(baseUrl).replace(/\/$/, "");

  async function request(path, options = {}) {
    const response = await fetchImpl(`${root}${path}`, {
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
      ...options,
    });

    let data = null;
    const text = await response.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text };
      }
    }

    if (!response.ok) {
      const detail =
        (data && (data.detail || data.error || data.message)) ||
        `HTTP ${response.status}`;
      const error = new Error(
        typeof detail === "string" ? detail : JSON.stringify(detail),
      );
      error.status = response.status;
      error.data = data;
      throw error;
    }

    return data;
  }

  return {
    baseUrl: root,

    getHealth() {
      return request("/health");
    },

    getProducts({ q, merchant, category } = {}) {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (merchant) params.set("merchant", merchant);
      if (category) params.set("category", category);
      const qs = params.toString();
      return request(`/products${qs ? `?${qs}` : ""}`);
    },

    getProduct(sku) {
      return request(`/products/${encodeURIComponent(sku)}`);
    },

    getMerchants() {
      return request("/merchants");
    },

    postCart({ items, merchant } = {}) {
      const body = { items };
      if (merchant) body.merchant = merchant;
      return request("/cart", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },

    postPay({ cart_total, payment_route, idempotency_key } = {}) {
      const payload = { cart_total, payment_route };
      if (idempotency_key) payload.idempotency_key = idempotency_key;
      return request("/pay", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
  };
}

export const api = createApi();
