import { api } from "./api.js";
import { cartItemsPayload, formatHkd, truncate } from "./format.js";

const state = {
  products: [],
  cart: {}, // sku -> qty
  priced: null,
  merchants: null,
};

const els = {
  apiStatus: document.getElementById("api-status"),
  searchForm: document.getElementById("search-form"),
  q: document.getElementById("q"),
  merchant: document.getElementById("merchant"),
  category: document.getElementById("category"),
  resetFilters: document.getElementById("reset-filters"),
  productGrid: document.getElementById("product-grid"),
  productCount: document.getElementById("product-count"),
  productError: document.getElementById("product-error"),
  cartLines: document.getElementById("cart-lines"),
  cartEmpty: document.getElementById("cart-empty"),
  cartCount: document.getElementById("cart-count"),
  subtotal: document.getElementById("subtotal"),
  shipping: document.getElementById("shipping"),
  tax: document.getElementById("tax"),
  tlc: document.getElementById("tlc"),
  shippingNote: document.getElementById("shipping-note"),
  priceCart: document.getElementById("price-cart"),
  payNow: document.getElementById("pay-now"),
  paymentRoute: document.getElementById("payment-route"),
  idempotencyKey: document.getElementById("idempotency-key"),
  payResult: document.getElementById("pay-result"),
  whitelist: document.getElementById("whitelist"),
  blacklist: document.getElementById("blacklist"),
};

function showFlash(el, message, kind) {
  el.textContent = message;
  el.classList.remove("hidden", "ok", "error");
  el.classList.add(kind);
}

function hideFlash(el) {
  el.classList.add("hidden");
  el.textContent = "";
}

function renderProducts() {
  els.productCount.textContent = `${state.products.length} items`;
  els.productGrid.innerHTML = "";

  for (const product of state.products) {
    const card = document.createElement("article");
    card.className = "product";
    card.dataset.sku = product.id;

    const title = document.createElement("h3");
    title.textContent = truncate(product.name, 90);

    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = `${product.merchant} · ${product.category} · stock ${product.stock}`;

    const price = document.createElement("p");
    price.className = "price";
    price.textContent = formatHkd(product.price);

    const qtyRow = document.createElement("div");
    qtyRow.className = "qty-row";
    const qtyLabel = document.createElement("label");
    qtyLabel.textContent = "Qty";
    const qtyInput = document.createElement("input");
    qtyInput.type = "number";
    qtyInput.min = "1";
    qtyInput.value = "1";
    qtyInput.className = "qty-input";
    qtyRow.append(qtyLabel, qtyInput);

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn btn-blue";
    addBtn.textContent = "Add to Cart";
    addBtn.addEventListener("click", () => {
      const qty = Math.max(1, Number(qtyInput.value) || 1);
      state.cart[product.id] = (state.cart[product.id] || 0) + qty;
      state.priced = null;
      hideFlash(els.payResult);
      renderCart();
    });

    card.append(title, meta, price, qtyRow, addBtn);
    els.productGrid.append(card);
  }
}

function renderCart() {
  const items = cartItemsPayload(state.cart);
  els.cartCount.textContent = String(items.reduce((n, i) => n + i.qty, 0));
  els.cartLines.innerHTML = "";
  els.cartEmpty.classList.toggle("hidden", items.length > 0);
  els.priceCart.disabled = items.length === 0;
  els.payNow.disabled = !state.priced;

  for (const item of items) {
    const product = state.products.find((p) => p.id === item.sku);
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${item.sku} × ${item.qty}${
      product ? ` — ${truncate(product.name, 28)}` : ""
    }`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      delete state.cart[item.sku];
      state.priced = null;
      hideFlash(els.payResult);
      renderCart();
    });
    li.append(label, remove);
    els.cartLines.append(li);
  }

  if (state.priced) {
    els.subtotal.textContent = formatHkd(state.priced.subtotal);
    els.shipping.textContent = formatHkd(state.priced.shipping_fee);
    els.tax.textContent = formatHkd(state.priced.tax);
    els.tlc.textContent = formatHkd(state.priced.total_landed_cost);
    els.shippingNote.textContent = `Free shipping at ${formatHkd(
      state.priced.free_shipping_threshold,
    )}`;
  } else {
    els.subtotal.textContent = "HK$0.00";
    els.shipping.textContent = "HK$0.00";
    els.tax.textContent = "HK$0.00";
    els.tlc.textContent = "HK$0.00";
  }
}

function fillMerchantSelect() {
  if (!state.merchants) return;
  const current = els.merchant.value;
  els.merchant.innerHTML = '<option value="">All merchants</option>';
  for (const name of state.merchants.whitelist) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    els.merchant.append(opt);
  }
  els.merchant.value = current;
  els.whitelist.textContent = state.merchants.whitelist.join(", ");
  els.blacklist.textContent = state.merchants.blacklist.join(", ");
}

async function loadProducts() {
  hideFlash(els.productError);
  try {
    state.products = await api.getProducts({
      q: els.q.value.trim() || undefined,
      merchant: els.merchant.value || undefined,
      category: els.category.value || undefined,
    });
    renderProducts();
    renderCart();
  } catch (err) {
    state.products = [];
    renderProducts();
    showFlash(els.productError, `Product load failed: ${err.message}`, "error");
  }
}

async function bootstrap() {
  try {
    const health = await api.getHealth();
    els.apiStatus.textContent = health?.ok
      ? "API online ✓"
      : "API responded oddly";
    els.apiStatus.classList.toggle("ok", Boolean(health?.ok));
    els.apiStatus.classList.toggle("bad", !health?.ok);
  } catch (err) {
    els.apiStatus.textContent = "API offline";
    els.apiStatus.classList.add("bad");
    showFlash(
      els.productError,
      `Cannot reach mock-api (${api.baseUrl}). Start it on :8000. ${err.message}`,
      "error",
    );
  }

  try {
    state.merchants = await api.getMerchants();
    fillMerchantSelect();
  } catch (err) {
    els.whitelist.textContent = "(failed to load)";
    els.blacklist.textContent = err.message;
  }

  await loadProducts();
}

els.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadProducts();
});

els.resetFilters.addEventListener("click", () => {
  els.q.value = "";
  els.merchant.value = "";
  els.category.value = "";
  loadProducts();
});

els.priceCart.addEventListener("click", async () => {
  hideFlash(els.payResult);
  const items = cartItemsPayload(state.cart);
  if (!items.length) return;
  els.priceCart.disabled = true;
  els.priceCart.textContent = "Pricing…";
  try {
    state.priced = await api.postCart({ items });
    renderCart();
    showFlash(
      els.payResult,
      `Cart priced. TLC ${formatHkd(state.priced.total_landed_cost)}`,
      "ok",
    );
  } catch (err) {
    state.priced = null;
    renderCart();
    showFlash(els.payResult, `Cart pricing failed: ${err.message}`, "error");
  } finally {
    els.priceCart.textContent = "Price Cart via API";
    els.priceCart.disabled = cartItemsPayload(state.cart).length === 0;
  }
});

els.payNow.addEventListener("click", async () => {
  if (!state.priced) return;
  els.payNow.disabled = true;
  els.payNow.textContent = "Paying…";
  hideFlash(els.payResult);
  try {
    const result = await api.postPay({
      cart_total: state.priced.total_landed_cost,
      payment_route: els.paymentRoute.value,
      idempotency_key: els.idempotencyKey.value.trim() || undefined,
    });
    if (result.success) {
      showFlash(
        els.payResult,
        `SUCCESS\norder_id: ${result.order_id}\ncharged: ${formatHkd(
          result.charged,
        )}\nroute: ${result.payment_route}\npoints: ${
          result.reward_points_earned
        }\nts: ${result.ts}`,
        "ok",
      );
    } else {
      showFlash(
        els.payResult,
        `FAILED\nerror: ${result.error}\norder_id: ${result.order_id}`,
        "error",
      );
    }
  } catch (err) {
    showFlash(els.payResult, `Pay request failed: ${err.message}`, "error");
  } finally {
    els.payNow.textContent = "Pay Now";
    els.payNow.disabled = !state.priced;
  }
});

bootstrap();
