<script setup>
import { computed } from 'vue'
import { content } from '../content/index.js'
import Icon from '../components/shop/Icon.vue'
import {
  ChartIncreaseIcon, SecurityCheckIcon, ShoppingCartCheck01Icon,
  RankingIcon, UserCheck01Icon, LinkSquare01Icon, Mail01Icon,
} from '@hugeicons/core-free-icons'

const about = computed(() => content.value.about)
const stepIcons = [ChartIncreaseIcon, SecurityCheckIcon, ShoppingCartCheck01Icon]
const principleIcons = [RankingIcon, UserCheck01Icon, LinkSquare01Icon]
</script>

<template>
  <main class="page about">
    <section class="about-hero">
      <p class="about-kicker">{{ about.kicker }}</p>
      <h1>{{ about.title }}</h1>
      <p class="about-lead">{{ about.lead }}</p>
      <RouterLink to="/catalog" class="btn-primary">{{ about.cta }}</RouterLink>
    </section>

    <section class="about-block">
      <p class="about-kicker">{{ about.whatTitle }}</p>
      <h2>{{ about.whatText }}</h2>
      <div class="about-grid three">
        <article v-for="(step, i) in about.steps" :key="i" class="about-card">
          <div class="about-card-top">
            <span class="about-num">{{ String(i + 1).padStart(2, '0') }}</span>
            <Icon :icon="stepIcons[i]" :size="22" class="about-icon" />
          </div>
          <h3>{{ step.title }}</h3>
          <p>{{ step.text }}</p>
        </article>
      </div>
    </section>

    <section class="about-block">
      <p class="about-kicker">{{ about.principlesTitle }}</p>
      <div class="about-grid three">
        <article v-for="(p, i) in about.principles" :key="i" class="about-card">
          <Icon :icon="principleIcons[i]" :size="24" class="about-icon" />
          <h3>{{ p.title }}</h3>
          <p>{{ p.text }}</p>
        </article>
      </div>
    </section>

    <a :href="`mailto:${about.contactEmail}`" class="about-contact">
      <Icon :icon="Mail01Icon" :size="22" />
      <span>{{ about.contactTitle }}</span>
      <strong>{{ about.contactEmail }}</strong>
    </a>
  </main>
</template>
