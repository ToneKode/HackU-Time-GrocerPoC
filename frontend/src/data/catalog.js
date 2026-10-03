// Demo catalog for the price-comparison UI. Merchants match the policy whitelist
// in contract.json; SKU001/002/004/005 match the mock HKTV API so the agent and
// the shop talk about the same products. Prices are HKD.
//
// offer: { merchant, price, oldPrice?, inStock? }   (inStock defaults to true)
import {
  BroccoliIcon, MilkBottleIcon, RiceBowl01Icon, CookieIcon, SoftDrink01Icon,
  TissuePaperIcon, ShampooIcon, BabyBottleIcon, MedicineBottle01Icon,
} from '@hugeicons/core-free-icons'

// Category tints and store colours are CSS vars (shop.css) so charts and logos share one validated palette.
export const merchants = [
  { name: 'Watsons', short: 'W', color: 'var(--m-1)' },
  { name: 'HKTVmall', short: 'HK', color: 'var(--m-2)' },
  { name: 'PARKnSHOP', short: 'P', color: 'var(--m-3)' },
  { name: 'Japan Home Centre', short: 'J', color: 'var(--m-4)' },
]

export const categories = [
  { id: 'fruit-veg', label: 'Fruit & veg', icon: BroccoliIcon, tint: 'var(--tint-fruit-veg)' },
  { id: 'dairy', label: 'Dairy & eggs', icon: MilkBottleIcon, tint: 'var(--tint-dairy)' },
  { id: 'pantry', label: 'Pantry', icon: RiceBowl01Icon, tint: 'var(--tint-pantry)' },
  { id: 'snacks', label: 'Snacks', icon: CookieIcon, tint: 'var(--tint-snacks)' },
  { id: 'drinks', label: 'Drinks', icon: SoftDrink01Icon, tint: 'var(--tint-drinks)' },
  { id: 'household', label: 'Household', icon: TissuePaperIcon, tint: 'var(--tint-household)' },
  { id: 'personal', label: 'Personal care', icon: ShampooIcon, tint: 'var(--tint-personal)' },
  { id: 'baby', label: 'Baby', icon: BabyBottleIcon, tint: 'var(--tint-baby)' },
  { id: 'health', label: 'Health', icon: MedicineBottle01Icon, tint: 'var(--tint-health)' },
]

export const products = [
  {
    id: 'SKU001', name: 'Tempo Ultra Soft Toilet Paper 27 Rolls', category: 'household', size: '27 rolls', emoji: '🧻',
    offers: [
      { merchant: 'Watsons', price: 89.9, oldPrice: 129.9 },
      { merchant: 'HKTVmall', price: 94.5 },
      { merchant: 'PARKnSHOP', price: 99.9 },
    ],
  },
  {
    id: 'SKU002', name: 'Virjoy Toilet Paper 10 Rolls', category: 'household', size: '10 rolls', emoji: '🧻',
    offers: [
      { merchant: 'HKTVmall', price: 39.9, oldPrice: 49.9 },
      { merchant: 'PARKnSHOP', price: 42.9 },
      { merchant: 'Watsons', price: 45.0 },
    ],
  },
  {
    id: 'SKU004', name: 'Dettol Surface Cleaner 1L', category: 'household', size: '1 L', emoji: '🧴',
    offers: [
      { merchant: 'Watsons', price: 45.0, oldPrice: 59.9 },
      { merchant: 'HKTVmall', price: 47.5 },
      { merchant: 'PARKnSHOP', price: 49.9 },
      { merchant: 'Japan Home Centre', price: 52.0, inStock: false },
    ],
  },
  {
    id: 'TG001', name: 'Microfiber Cleaning Cloths 10pcs', category: 'household', size: '10 pcs', emoji: '🧽',
    offers: [
      { merchant: 'Japan Home Centre', price: 25.0, oldPrice: 35.0 },
      { merchant: 'HKTVmall', price: 27.0 },
      { merchant: 'Watsons', price: 29.9 },
    ],
  },
  {
    id: 'TG002', name: 'Stackable Storage Box Set 3pcs', category: 'household', size: '3 pcs', emoji: '📦',
    offers: [
      { merchant: 'Japan Home Centre', price: 39.0, oldPrice: 59.0 },
      { merchant: 'HKTVmall', price: 45.0 },
    ],
  },
  {
    id: 'SKU005', name: 'Snack Gift Pack (Assorted)', category: 'snacks', size: '1 kg', emoji: '🎁',
    offers: [
      { merchant: 'HKTVmall', price: 120.0, oldPrice: 158.0 },
      { merchant: 'PARKnSHOP', price: 128.0 },
    ],
  },
  {
    id: 'TG003', name: 'Calbee Potato Chips Original 105g', category: 'snacks', size: '105 g', emoji: '🥔',
    offers: [
      { merchant: 'HKTVmall', price: 12.5, oldPrice: 15.9 },
      { merchant: 'PARKnSHOP', price: 13.9 },
      { merchant: 'Watsons', price: 14.9 },
    ],
  },
  {
    id: 'TG004', name: 'Meiji Almond Chocolate 79g', category: 'snacks', size: '79 g', emoji: '🍫',
    offers: [
      { merchant: 'Japan Home Centre', price: 19.9, oldPrice: 26.0 },
      { merchant: 'Watsons', price: 22.9 },
      { merchant: 'PARKnSHOP', price: 24.5 },
    ],
  },
  {
    id: 'TG005', name: 'Vita Lemon Tea 250ml x 6', category: 'drinks', size: '6 × 250 ml', emoji: '🧃',
    offers: [
      { merchant: 'PARKnSHOP', price: 21.9, oldPrice: 27.5 },
      { merchant: 'HKTVmall', price: 22.9 },
      { merchant: 'Watsons', price: 24.9 },
    ],
  },
  {
    id: 'TG006', name: 'Pocari Sweat 500ml x 6', category: 'drinks', size: '6 × 500 ml', emoji: '🥤',
    offers: [
      { merchant: 'Watsons', price: 49.9, oldPrice: 59.4 },
      { merchant: 'HKTVmall', price: 52.0 },
      { merchant: 'PARKnSHOP', price: 54.9 },
    ],
  },
  {
    id: 'TG007', name: 'Bonaqua Mineral Water 1.5L x 12', category: 'drinks', size: '12 × 1.5 L', emoji: '💧',
    offers: [
      { merchant: 'HKTVmall', price: 85.0 },
      { merchant: 'PARKnSHOP', price: 89.0, oldPrice: 110.0 },
    ],
  },
  {
    id: 'TG008', name: 'Meiji Fresh Milk 2L', category: 'dairy', size: '2 L', emoji: '🥛',
    offers: [
      { merchant: 'PARKnSHOP', price: 46.9, oldPrice: 52.9 },
      { merchant: 'HKTVmall', price: 48.5 },
    ],
  },
  {
    id: 'TG009', name: 'Free-range Eggs 10pcs', category: 'dairy', size: '10 pcs', emoji: '🥚',
    offers: [
      { merchant: 'HKTVmall', price: 29.9, oldPrice: 36.9 },
      { merchant: 'PARKnSHOP', price: 32.9 },
    ],
  },
  {
    id: 'TG010', name: 'Garden Life Plus Wholemeal Bread 450g', category: 'pantry', size: '450 g', emoji: '🍞',
    offers: [
      { merchant: 'PARKnSHOP', price: 16.5 },
      { merchant: 'HKTVmall', price: 17.9 },
    ],
  },
  {
    id: 'TG011', name: 'Nissin Cup Noodles Seafood 5 Pack', category: 'pantry', size: '5 pcs', emoji: '🍜',
    offers: [
      { merchant: 'HKTVmall', price: 31.9 },
      { merchant: 'PARKnSHOP', price: 32.5, oldPrice: 39.9 },
      { merchant: 'Watsons', price: 35.0 },
    ],
  },
  {
    id: 'TG012', name: 'Golden Phoenix Jasmine Rice 5kg', category: 'pantry', size: '5 kg', emoji: '🍚',
    offers: [
      { merchant: 'PARKnSHOP', price: 79.9, oldPrice: 98.0 },
      { merchant: 'HKTVmall', price: 82.0 },
    ],
  },
  {
    id: 'TG013', name: 'Lee Kum Kee Oyster Sauce 510g', category: 'pantry', size: '510 g', emoji: '🦪',
    offers: [
      { merchant: 'HKTVmall', price: 24.9, oldPrice: 29.9 },
      { merchant: 'PARKnSHOP', price: 26.9 },
    ],
  },
  {
    id: 'TG014', name: 'Bananas 1kg', category: 'fruit-veg', size: '1 kg', emoji: '🍌',
    offers: [
      { merchant: 'HKTVmall', price: 16.9, oldPrice: 21.9 },
      { merchant: 'PARKnSHOP', price: 18.9 },
    ],
  },
  {
    id: 'TG015', name: 'Fuji Apples 6pcs', category: 'fruit-veg', size: '6 pcs', emoji: '🍎',
    offers: [
      { merchant: 'PARKnSHOP', price: 39.9, oldPrice: 48.0 },
      { merchant: 'HKTVmall', price: 42.0 },
    ],
  },
  {
    id: 'TG016', name: 'Broccoli 500g', category: 'fruit-veg', size: '500 g', emoji: '🥦',
    offers: [
      { merchant: 'HKTVmall', price: 14.5 },
      { merchant: 'PARKnSHOP', price: 15.9, inStock: false },
    ],
  },
  {
    id: 'TG017', name: 'Colgate Total Toothpaste 150g x 2', category: 'personal', size: '2 × 150 g', emoji: '🪥',
    offers: [
      { merchant: 'Watsons', price: 39.9, oldPrice: 55.8 },
      { merchant: 'HKTVmall', price: 41.0 },
      { merchant: 'PARKnSHOP', price: 42.9 },
    ],
  },
  {
    id: 'TG018', name: 'Head & Shoulders Shampoo 750ml', category: 'personal', size: '750 ml', emoji: '🧴',
    offers: [
      { merchant: 'HKTVmall', price: 76.0 },
      { merchant: 'Watsons', price: 79.9, oldPrice: 109.9 },
      { merchant: 'PARKnSHOP', price: 85.9 },
    ],
  },
  {
    id: 'TG019', name: 'Dove Deeply Nourishing Body Wash 1L', category: 'personal', size: '1 L', emoji: '🫧',
    offers: [
      { merchant: 'HKTVmall', price: 55.0, oldPrice: 69.9 },
      { merchant: 'Watsons', price: 59.9 },
    ],
  },
  {
    id: 'TG020', name: 'Pampers Baby Dry Diapers M 64pcs', category: 'baby', size: '64 pcs', emoji: '👶',
    offers: [
      { merchant: 'HKTVmall', price: 149.0 },
      { merchant: 'Watsons', price: 159.0, oldPrice: 199.0 },
      { merchant: 'PARKnSHOP', price: 165.0 },
    ],
  },
  {
    id: 'TG021', name: 'Friso Gold Stage 3 Formula 900g', category: 'baby', size: '900 g', emoji: '🍼',
    offers: [
      { merchant: 'HKTVmall', price: 259.0 },
      { merchant: 'Watsons', price: 269.0, oldPrice: 315.0 },
    ],
  },
  {
    id: 'TG022', name: 'Panadol Extra 20 Tablets', category: 'health', size: '20 pcs', emoji: '💊',
    offers: [
      { merchant: 'HKTVmall', price: 39.9, oldPrice: 45.0 },
      { merchant: 'Watsons', price: 42.9 },
    ],
  },
  {
    id: 'TG023', name: 'Vitamin C 1000mg 100 Tablets', category: 'health', size: '100 pcs', emoji: '🍊',
    offers: [
      { merchant: 'HKTVmall', price: 89.0 },
      { merchant: 'Japan Home Centre', price: 95.0 },
      { merchant: 'Watsons', price: 98.0, oldPrice: 138.0 },
    ],
  },
]

export const productById = Object.fromEntries(products.map((p) => [p.id, p]))
export const merchantByName = Object.fromEntries(merchants.map((m) => [m.name, m]))
export const categoryById = Object.fromEntries(categories.map((c) => [c.id, c]))
