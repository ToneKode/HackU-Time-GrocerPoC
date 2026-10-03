<script setup>
defineProps({ comparison: { type: Object, required: true } })

// "4 min" / "10 sec" in the current language.
const duration = (s) => (s >= 60 ? { key: 'agentCards.minutes', n: Math.round(s / 60) } : { key: 'agentCards.seconds', n: s })
</script>

<template>
  <section class="card">
    <h2>{{ $t('agentCards.compareTitle') }}</h2>
    <div class="compare">
      <div v-for="(side, key) in { manual: comparison.manual, agent: comparison.agent }" :key="key" class="compare-col">
        <span class="muted">{{ $t(`agentCards.${key}`) }}</span>
        <strong>{{ $t(duration(side.duration_seconds).key, { n: duration(side.duration_seconds).n }) }}</strong>
        <span>{{ $t('agentCards.steps', side.steps) }}</span>
      </div>
    </div>
  </section>
</template>
