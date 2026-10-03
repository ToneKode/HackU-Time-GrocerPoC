// When persistance has catalog rows, replace the demo shelf. A failed fetch
// leaves the demo products in place.
import {
  BabyBottleIcon, BroccoliIcon, CookieIcon, MedicineBottle01Icon, RiceBowl01Icon,
  ShampooIcon, ShoppingBag01Icon, SoftDrink01Icon, TissuePaperIcon,
} from '@hugeicons/core-free-icons'
import { PERSISTANCE_URL } from '../lib/api.js'
import { reactive } from 'vue'
import { categories, categoryById, productById, products } from './catalog.js'

export const shelfState = reactive({ source: 'demo', count: products.length })

const TINTS = [
  'var(--tint-fruit-veg)',
  'var(--tint-dairy)',
  'var(--tint-pantry)',
  'var(--tint-snacks)',
  'var(--tint-drinks)',
  'var(--tint-household)',
  'var(--tint-personal)',
  'var(--tint-baby)',
  'var(--tint-health)',
]

const ICONS = {
  baby: BabyBottleIcon,
  snacks: CookieIcon,
  beverages: SoftDrink01Icon,
  drinks: SoftDrink01Icon,
  'health-supplements': MedicineBottle01Icon,
  health: MedicineBottle01Icon,
  pantry: RiceBowl01Icon,
  'rice-and-noodles': RiceBowl01Icon,
  'frozen-food': RiceBowl01Icon,
  kitchen: RiceBowl01Icon,
  'household-cleaning': TissuePaperIcon,
  household: TissuePaperIcon,
  'paper-and-tissue': TissuePaperIcon,
  laundry: TissuePaperIcon,
  bathroom: TissuePaperIcon,
  storage: TissuePaperIcon,
  'home-appliances': TissuePaperIcon,
  stationery: RiceBowl01Icon,
  'personal-care': ShampooIcon,
  personal: ShampooIcon,
  skincare: ShampooIcon,
  'hair-care': ShampooIcon,
  'oral-care': ShampooIcon,
  'bath-and-body': ShampooIcon,
  makeup: ShampooIcon,
  pet: BroccoliIcon,
}

export function categorySlug(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'other'
}

function shopProduct(row) {
  return {
    id: row.id,
    name: row.name,
    category: categorySlug(row.category),
    size: '',
    emoji: '🛒',
    imageUrl: row.image_url || '',
    offers: [
      {
        merchant: row.merchant,
        price: Number(row.price),
        inStock: row.in_stock !== false,
      },
    ],
  }
}

function replaceKeys(target, next) {
  for (const key of Object.keys(target)) delete target[key]
  Object.assign(target, next)
}

async function fetchRows() {
  const res = await fetch(`${PERSISTANCE_URL}/catalog/products?limit=6000`)
  if (!res.ok) return null
  const rows = await res.json()
  return Array.isArray(rows) ? rows : null
}

export async function loadDatabaseCatalog() {
  let rows = null
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      rows = await fetchRows()
    } catch {
      rows = null
    }
    if (rows && rows.length) break
    await new Promise((resolve) => setTimeout(resolve, 400))
  }
  if (!rows || !rows.length) return false
  const names = []
  for (const row of rows) {
    if (row?.category && !names.includes(row.category)) names.push(row.category)
  }
  const nextCategories = names.map((name, index) => {
    const id = categorySlug(name)
    return {
      id,
      label: name,
      icon: ICONS[id] || ShoppingBag01Icon,
      tint: TINTS[index % TINTS.length],
    }
  })
  const nextProducts = rows.filter((row) => row?.id && row?.name).map(shopProduct)
  if (!nextProducts.length) return false
  categories.splice(0, categories.length, ...nextCategories)
  replaceKeys(categoryById, Object.fromEntries(nextCategories.map((c) => [c.id, c])))
  products.splice(0, products.length, ...nextProducts)
  replaceKeys(productById, Object.fromEntries(nextProducts.map((p) => [p.id, p])))
  shelfState.source = 'database'
  shelfState.count = nextProducts.length
  return true
}
