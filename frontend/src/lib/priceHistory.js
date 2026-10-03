// DEMO price history. There is no real price feed yet, so each store's history
// is generated from a fixed seed (same product + store = same chart every time)
// and always ends at today's price from catalog.js. Swap this module for an API
// call when a backend provides real history.
import { merchants } from '../data/catalog.js'

const DAY = 24 * 60 * 60 * 1000
export const PERIODS = [30, 90, 180]
const MAX_DAYS = Math.max(...PERIODS)

const round1 = (n) => Math.round(n * 10) / 10
const round2 = (n) => Math.round(n * 100) / 100

function hash(text) {
  let h = 2166136261
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619)
  return h >>> 0
}

// Small seeded random number generator (mulberry32).
function seeded(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function startOfToday() {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

const cache = new Map()

// One price per day for MAX_DAYS days, oldest first: { t, v }[]
function offerHistory(productId, offer) {
  const key = productId + '|' + offer.merchant
  if (cache.has(key)) return cache.get(key)

  const rand = seeded(hash(key))
  const regular = offer.oldPrice ?? offer.price
  const currentFor = 3 + Math.floor(rand() * 20) // days today's price has held
  const end = startOfToday()
  const points = []
  let price = regular
  let promoLeft = 0

  for (let daysAgo = MAX_DAYS - 1; daysAgo >= 0; daysAgo--) {
    if (daysAgo < currentFor) {
      price = offer.price
    } else if (promoLeft > 0) {
      promoLeft--
      if (promoLeft === 0) price = regular
    } else if (rand() < 0.03) {
      price = round1(regular * (0.75 + rand() * 0.15)) // a short promo
      promoLeft = 4 + Math.floor(rand() * 10)
    } else if (rand() < 0.01) {
      price = round1(regular * (1 + (rand() - 0.5) * 0.06)) // small shelf-price change
    }
    points.push({ t: end - daysAgo * DAY, v: price })
  }

  cache.set(key, points)
  return points
}

function summarize(points) {
  const values = points.map((p) => p.v)
  const first = values[0]
  const current = values.at(-1)
  return {
    first,
    current,
    low: Math.min(...values),
    high: Math.max(...values),
    avg: round2(values.reduce((a, b) => a + b, 0) / values.length),
    changePct: first ? Math.round(((current - first) / first) * 100) : 0,
  }
}

// Everything the product page needs for one period.
export function productHistory(product, days) {
  const storeOrder = merchants.map((m) => m.name)
  const offers = [...product.offers].sort((a, b) => storeOrder.indexOf(a.merchant) - storeOrder.indexOf(b.merchant))

  const stores = offers.map((offer) => {
    const points = offerHistory(product.id, offer).slice(-days)
    return { merchant: offer.merchant, inStock: offer.inStock !== false, points, ...summarize(points) }
  })

  // Cheapest price available on each day, across all stores.
  const minPoints = stores[0].points.map((p, i) => ({
    t: p.t,
    v: Math.min(...stores.map((s) => s.points[i].v)),
  }))
  const min = summarize(minPoints)

  const inStockNow = offers.filter((o) => o.inStock !== false).map((o) => o.price)
  const spread = inStockNow.length > 1 ? round2(Math.max(...inStockNow) - Math.min(...inStockNow)) : 0

  return {
    start: minPoints[0].t,
    end: minPoints.at(-1).t,
    stores,
    minPoints,
    stats: {
      ...min,
      vsAvgPct: Math.round(((min.current - min.avg) / min.avg) * 100),
      spread,
      storeCount: inStockNow.length,
    },
  }
}

// Days since the price at this store last changed.
export function daysSinceChange(product, offer) {
  const points = offerHistory(product.id, offer)
  let i = points.length - 1
  while (i > 0 && points[i - 1].v === points[i].v) i--
  return points.length - 1 - i
}
