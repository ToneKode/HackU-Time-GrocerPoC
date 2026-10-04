<script setup>
import { computed, ref } from 'vue'
import { categoryById } from '../../data/catalog.js'
import { sortedOffers, bestOffer, discountPct } from '../../lib/pricing.js'
import { money } from '../../lib/format.js'
import { qtyOf, setQty, addToCart, favourites, toggleFavourite } from '../../stores/shop.js'
import MerchantLogo from './MerchantLogo.vue'
import QtyStepper from './QtyStepper.vue'
import { FavouriteIcon, PlusSignIcon } from '@hugeicons/core-free-icons'
import Icon from './Icon.vue'
import { productName, productSize, storeName } from '../../i18n/index.js'

// merchant: optional store filter; the card then shows that store's price.
const props = defineProps({
  product: { type: Object, required: true },
  merchant: { type: String, default: null },
})

const allowed = computed(() => (props.merchant ? [props.merchant] : null))
const best = computed(() => bestOffer(props.product, allowed.value))
const offers = computed(() => sortedOffers(props.product).slice(0, 3))
const discount = computed(() => discountPct(best.value))
const tint = computed(() => categoryById[props.product.category]?.tint)
const photoBroken = ref(false)
const qty = computed({
  get: () => qtyOf(props.product.id),
  set: (value) => setQty(props.product.id, value),
})
</script>

<template>
  <article class="product">
    <div class="product-image" :style="{ background: tint }">
      <span v-if="discount" class="discount">-{{ discount }}%</span>
      <button
        type="button"
        class="fav"
        :class="{ on: favourites.ids[product.id] }"
        :aria-label="favourites.ids[product.id] ? $t('card.removeFavourite') : $t('card.addFavourite')"
        @click="toggleFavourite(product.id)"
      >
        <Icon :icon="FavouriteIcon" :size="18" />
      </button>
      <RouterLink :to="{ name: 'product', params: { id: product.id } }" class="product-image-link" :aria-label="productName(product)">
        <img v-if="product.imageUrl && !photoBroken" class="product-photo" :src="product.imageUrl" alt="" @error="photoBroken = true" />
        <span v-else class="product-emoji" aria-hidden="true">{{ product.emoji }}</span>
      </RouterLink>
      <span class="size">{{ productSize(product) }}</span>
    </div>

    <div class="price-row">
      <template v-if="best">
        <s v-if="best.oldPrice" class="old-price">{{ money(best.oldPrice) }}</s>
        <span class="price">{{ money(best.price) }}</span>
      </template>
      <span v-else class="muted">{{ $t('card.notAvailable') }}</span>
    </div>

    <!-- Product names are plain text: {{ }} only, never v-html. -->
    <h3 class="product-name">
      <RouterLink :to="{ name: 'product', params: { id: product.id } }">{{ productName(product) }}</RouterLink>
    </h3>

    <ul class="offers">
      <li v-for="offer in offers" :key="offer.merchant" :class="{ out: offer.inStock === false }">
        <MerchantLogo :name="offer.merchant" :size="16" />
        <span class="offer-name">{{ storeName(offer.merchant) }}</span>
        <span v-if="offer.inStock === false" class="out-tag">{{ $t('card.outOfStock') }}</span>
        <span class="offer-price">{{ money(offer.price) }}</span>
      </li>
    </ul>

    <QtyStepper v-if="qty" v-model="qty" class="product-action" />
    <button v-else type="button" class="add-btn product-action" :disabled="!bestOffer(product)" @click="addToCart(product.id)">
      <Icon :icon="PlusSignIcon" :size="16" :stroke-width="2.2" /> {{ $t('card.addToCart') }}
    </button>
  </article>
</template>
