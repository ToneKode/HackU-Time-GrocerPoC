// Cart + favourites, kept in localStorage so a refresh doesn't empty the cart.
import { reactive, computed, watch } from 'vue'
import { productById } from '../data/catalog.js'

function load(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback
  } catch {
    return fallback
  }
}

function persist(key, getter) {
  watch(getter, (value) => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Private mode or storage blocked: the cart still works for this visit.
    }
  }, { deep: true })
}

// cart.items: { [productId]: qty }
export const cart = reactive({ items: load('tg-cart', {}) })
persist('tg-cart', () => cart.items)

export function qtyOf(id) {
  return cart.items[id] ?? 0
}

export function setQty(id, qty) {
  if (qty > 0) cart.items[id] = qty
  else delete cart.items[id]
}

export function addToCart(id) {
  setQty(id, qtyOf(id) + 1)
}

export function clearCart() {
  for (const id of Object.keys(cart.items)) delete cart.items[id]
}

export const cartLines = computed(() =>
  Object.entries(cart.items)
    .filter(([id]) => productById[id])
    .map(([id, qty]) => ({ product: productById[id], qty })),
)

export const cartCount = computed(() => cartLines.value.reduce((sum, line) => sum + line.qty, 0))

// favourites.ids: { [productId]: savedAt (ms) }  — older saves stored `true`, treated as 0.
export const favourites = reactive({ ids: load('tg-favourites', {}) })
persist('tg-favourites', () => favourites.ids)

export function toggleFavourite(id) {
  if (favourites.ids[id]) delete favourites.ids[id]
  else favourites.ids[id] = Date.now()
}

export function clearFavourites() {
  for (const id of Object.keys(favourites.ids)) delete favourites.ids[id]
}

export const favouriteCount = computed(() => Object.keys(favourites.ids).filter((id) => productById[id]).length)
