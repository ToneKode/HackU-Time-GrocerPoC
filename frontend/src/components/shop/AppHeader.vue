<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cartCount, favouriteCount } from '../../stores/shop.js'
import {
  Home01Icon, GridViewIcon, ShoppingCart01Icon, AiMagicIcon, Search01Icon, ShoppingBasket01Icon,
  Menu01Icon, FavouriteIcon,
} from '@hugeicons/core-free-icons'
import Icon from './Icon.vue'
import SideMenu from './SideMenu.vue'

const route = useRoute()
const router = useRouter()
const query = ref('')
const menuOpen = ref(false)
const menuButton = ref(null)

function closeMenu() {
  menuOpen.value = false
  menuButton.value?.focus()
}

// Close the menu whenever the page changes.
watch(() => route.fullPath, () => { menuOpen.value = false })

// Keep the box in sync when the catalog URL changes (?q=...)
watch(() => route.query.q, (q) => { query.value = q ?? '' }, { immediate: true })

function search() {
  const q = query.value.trim()
  router.push({ name: 'catalog', query: q ? { q } : {} })
}

const nav = [
  { to: '/', label: 'nav.home', icon: Home01Icon },
  { to: '/catalog', label: 'nav.catalog', icon: GridViewIcon },
  { to: '/favourites', label: 'nav.favourites', icon: FavouriteIcon, badge: favouriteCount },
  { to: '/cart', label: 'nav.cart', icon: ShoppingCart01Icon, badge: cartCount },
  { to: '/agent', label: 'nav.agent', icon: AiMagicIcon },
]
</script>

<template>
  <header class="site-header">
    <div class="site-header-inner">
      <RouterLink to="/" class="logo">
        <span class="logo-mark"><Icon :icon="ShoppingBasket01Icon" :size="24" :stroke-width="2" /></span>
        <span>grocer</span>
      </RouterLink>

      <form class="search" role="search" @submit.prevent="search">
        <span class="search-icon"><Icon :icon="Search01Icon" :size="18" /></span>
        <input v-model="query" type="search" :placeholder="$t('nav.searchPlaceholder')" :aria-label="$t('nav.searchLabel')" />
      </form>

      <nav class="nav">
        <RouterLink v-for="item in nav" :key="item.to" :to="item.to" class="nav-link">
          <span class="nav-icon">
            <Icon :icon="item.icon" />
            <span v-if="item.badge?.value" class="nav-badge">{{ item.badge.value }}</span>
          </span>
          <span class="nav-label">{{ $t(item.label) }}</span>
        </RouterLink>
      </nav>


      <button
        ref="menuButton"
        type="button"
        class="menu-btn"
        :class="{ on: menuOpen }"
        :aria-label="$t('nav.openMenu')"
        aria-controls="side-menu"
        :aria-expanded="menuOpen"
        @click="menuOpen ? closeMenu() : (menuOpen = true)"
      >
        <Icon :icon="Menu01Icon" :size="22" />
      </button>
    </div>
  </header>

  <SideMenu :open="menuOpen" @close="closeMenu" />
</template>
