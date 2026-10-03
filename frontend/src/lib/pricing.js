// Price comparison. `allowed` is an optional list of merchant names; empty/null = all.
import { merchants } from '../data/catalog.js'

const round2 = (n) => Math.round(n * 100) / 100
const isAllowed = (allowed, merchant) => !allowed?.length || allowed.includes(merchant)
const inStock = (offer) => offer.inStock !== false

// All offers for a product: in-stock first, then cheapest first.
export function sortedOffers(product, allowed) {
  return product.offers
    .filter((o) => isAllowed(allowed, o.merchant))
    .sort((a, b) => inStock(b) - inStock(a) || a.price - b.price)
}

// Cheapest in-stock offer, or null if nobody allowed has it.
export function bestOffer(product, allowed) {
  const first = sortedOffers(product, allowed)[0]
  return first && inStock(first) ? first : null
}

export function discountPct(offer) {
  if (!offer?.oldPrice || offer.oldPrice <= offer.price) return 0
  return Math.round(((offer.oldPrice - offer.price) / offer.oldPrice) * 100)
}

// lines: [{ product, qty }]
// Buy every item at its cheapest allowed store. Returns groups per store.
export function optimalMix(lines, allowed) {
  const groups = new Map()
  const unavailable = []
  for (const line of lines) {
    const offer = bestOffer(line.product, allowed)
    if (!offer) {
      unavailable.push(line)
      continue
    }
    if (!groups.has(offer.merchant)) groups.set(offer.merchant, { merchant: offer.merchant, items: [], subtotal: 0 })
    const group = groups.get(offer.merchant)
    const lineTotal = round2(offer.price * line.qty)
    group.items.push({ ...line, offer, lineTotal })
    group.subtotal = round2(group.subtotal + lineTotal)
  }
  const list = [...groups.values()].sort((a, b) => b.items.length - a.items.length)
  return { groups: list, total: round2(list.reduce((sum, g) => sum + g.subtotal, 0)), unavailable }
}

// Cost of the whole cart at each single store. Complete stores first, then cheapest.
export function singleStoreTotals(lines, allowed) {
  return merchants
    .filter((m) => isAllowed(allowed, m.name))
    .map((m) => {
      const items = lines.map((line) => {
        const offer = line.product.offers.find((o) => o.merchant === m.name && inStock(o)) ?? null
        return { ...line, offer, lineTotal: offer ? round2(offer.price * line.qty) : 0 }
      })
      const available = items.filter((i) => i.offer).length
      return {
        merchant: m.name,
        items,
        available,
        missing: lines.length - available,
        total: round2(items.reduce((sum, i) => sum + i.lineTotal, 0)),
      }
    })
    .filter((s) => s.available > 0)
    .sort((a, b) => a.missing - b.missing || a.total - b.total)
}

// Savings of the mix vs the most expensive store that has every item.
export function mixSavings(mix, stores) {
  const complete = stores.filter((s) => s.missing === 0)
  if (!complete.length || mix.unavailable.length) return null
  const priciest = complete.reduce((a, b) => (b.total > a.total ? b : a))
  return { amount: round2(priciest.total - mix.total), merchant: priciest.merchant }
}
