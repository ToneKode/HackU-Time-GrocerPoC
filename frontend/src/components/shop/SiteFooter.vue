<script setup>
import { content, fill } from '../../content/index.js'

const year = new Date().getFullYear()
const links = [
  { to: '/about', key: 'about' },
  { to: '/terms', key: 'terms' },
  { to: '/returns', key: 'returns' },
  { to: '/privacy', key: 'privacy' },
]
</script>

<template>
  <footer class="site-footer">
    <nav class="site-footer-links">
      <RouterLink v-for="link in links" :key="link.to" :to="link.to">
        {{ link.key === 'about' ? content.about.kicker : content[link.key].title }}
      </RouterLink>
    </nav>
    <p class="muted small">{{ fill(content.footer.rights, { year }) }}</p>
  </footer>
</template>
