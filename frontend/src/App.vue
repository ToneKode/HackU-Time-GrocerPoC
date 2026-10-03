<script setup>
import { useRoute } from 'vue-router'
import AppHeader from './components/shop/AppHeader.vue'
import SiteFooter from './components/shop/SiteFooter.vue'

const route = useRoute()
</script>

<template>
  <div class="app" :class="{ 'app-full': route.meta.fullHeight }">
    <AppHeader v-if="!route.meta.hideHeader" />
    <RouterView />
    <SiteFooter v-if="!route.meta.fullHeight" />
  </div>
</template>
