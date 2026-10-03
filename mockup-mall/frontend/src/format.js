/** Money / label helpers used by the mockup UI. */

export function formatHkd(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "HK$—";
  return `HK$${n.toFixed(2)}`;
}

export function truncate(text, max = 72) {
  const s = String(text ?? "");
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}

export function cartItemsPayload(cartMap) {
  return Object.entries(cartMap)
    .filter(([, qty]) => qty > 0)
    .map(([sku, qty]) => ({ sku, qty: Number(qty) }));
}
