<script setup>
// Terms / Return policy / Privacy policy. Which document comes from the route's meta.doc.
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { content, fill, LEGAL_UPDATED } from '../content/index.js'
import { dateLocale } from '../i18n/index.js'
import Icon from '../components/shop/Icon.vue'
import { ArrowLeft01Icon } from '@hugeicons/core-free-icons'

const route = useRoute()
const doc = computed(() => content.value[route.meta.doc])
const updated = computed(() =>
  fill(content.value.updated, {
    date: new Date(LEGAL_UPDATED).toLocaleDateString(dateLocale(), { year: 'numeric', month: 'long', day: 'numeric' }),
  }),
)
</script>

<template>
  <main class="page legal">
    <RouterLink to="/" class="back-link"><Icon :icon="ArrowLeft01Icon" :size="16" /> {{ content.backHome }}</RouterLink>

    <header class="legal-head">
      <h1>{{ doc.title }}</h1>
      <p class="muted small">{{ updated }}</p>
      <p class="legal-intro">{{ doc.intro }}</p>
    </header>

    <nav class="legal-toc" :aria-label="content.contents">
      <p class="legal-toc-title">{{ content.contents }}</p>
      <ol>
        <li v-for="(section, i) in doc.sections" :key="i">
          <RouterLink :to="{ hash: `#s-${i + 1}` }">{{ section.title }}</RouterLink>
        </li>
      </ol>
    </nav>

    <section v-for="(section, i) in doc.sections" :id="`s-${i + 1}`" :key="i" class="legal-section">
      <h2>{{ i + 1 }}. {{ section.title }}</h2>
      <template v-for="(block, j) in section.body" :key="j">
        <ul v-if="block.list">
          <li v-for="(item, k) in block.list" :key="k">{{ item }}</li>
        </ul>
        <p v-else>{{ block }}</p>
      </template>
    </section>
  </main>
</template>
