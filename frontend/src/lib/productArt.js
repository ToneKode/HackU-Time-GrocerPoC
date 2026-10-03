// Product pictures until the mall sends image_url: one picture + tint per category.
// Covers the agent's mall categories ("Personal Care") and the shop's ids ("personal").
const CATEGORY_ART = {
  household: ['🧻', 'var(--tint-household)'],
  food: ['🍚', 'var(--tint-pantry)'],
  pantry: ['🍚', 'var(--tint-pantry)'],
  beverages: ['💧', 'var(--tint-drinks)'],
  drinks: ['💧', 'var(--tint-drinks)'],
  snacks: ['🥔', 'var(--tint-snacks)'],
  health: ['😷', 'var(--tint-health)'],
  'personal care': ['🧴', 'var(--tint-personal)'],
  personal: ['🧴', 'var(--tint-personal)'],
  baby: ['👶', 'var(--tint-baby)'],
  pets: ['🐕', 'var(--tint-fruit-veg)'],
  electronics: ['🎧', 'var(--tint-dairy)'],
  kitchen: ['🥡', 'var(--tint-pantry)'],
  dairy: ['🥛', 'var(--tint-dairy)'],
  'fruit-veg': ['🥦', 'var(--tint-fruit-veg)'],
}

export function categoryArt(category) {
  const [emoji, tint] = CATEGORY_ART[String(category || '').toLowerCase()] ?? ['🛒', 'var(--surface-2)']
  return { emoji, tint }
}

// i18n key for a category name: "Personal Care" -> "personal_care".
export const categoryKey = (category) => String(category || '').toLowerCase().replace(/[\s-]+/g, '_')
