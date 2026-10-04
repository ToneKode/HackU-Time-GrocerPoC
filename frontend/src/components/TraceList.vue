<script setup>
import { ref, computed, watch } from 'vue'
import { verifyChain } from '../lib/hash.js'
import { shortHash } from '../lib/format.js'

const props = defineProps({ entries: { type: Array, default: () => [] } })

function toolSummary(entry) {
  const evidence = entry.result
  if (!evidence?.action) return entry.reason
  const result = evidence.result
  if (result?.error) return `${evidence.action}: ${typeof result.error === 'string' ? result.error : result.error.message}`
  if (evidence.action === 'candidate_policy') return `${result.product || result.sku}: ${result.verdict?.reason || ''}`
  if (evidence.action === 'search_catalog') return `${evidence.action}: ${result.products.length} / ${result.total_count}`
  if (evidence.action === 'optimize_basket') return `${evidence.action}: ${result.lines?.length || 0} items · HK$${Number(result.settlement?.total || 0).toFixed(2)}`
  return evidence.action
}

const sorted = computed(() => [...props.entries].sort((a, b) => a.index - b.index))

function stageOf(entry) {
  return entry.stage || entry.result?.stage || entry.result?.result?.stage || 'policy'
}
function policyEntry(entry) {
  return entry.event === 'POLICY_CHECK' || entry.result?.action === 'candidate_policy'
}
function failed(entry) {
  return policyEntry(entry) && entry.status !== 'PASS'
}
function productOf(entry) {
  return entry.result?.name || entry.result?.sku || entry.result?.result?.product || entry.result?.result?.sku || entry.reason?.match(/^line \d+ (\S+)/)?.[1] || ''
}
const displayed = computed(() => {
  const rows = []
  const groups = new Map()
  for (const [i, entry] of sorted.value.entries()) {
    if (policyEntry(entry) && entry.status === 'PASS') {
      const stage = stageOf(entry)
      if (!groups.has(stage)) {
        const group = { grouped: true, stage, entries: [], indices: [], index: entry.index }
        groups.set(stage, group)
        rows.push(group)
      }
      const group = groups.get(stage)
      group.entries.push(entry)
      group.indices.push(i)
    } else {
      rows.push({ ...entry, rawIndex: i })
    }
  }
  return rows
})

const checks = ref([])
const verification = ref('checking')
let revision = 0
watch(
  sorted,
  async (entries) => {
    const current = ++revision
    checks.value = []
    verification.value = 'checking'
    try {
      const results = await verifyChain(entries)
      if (current !== revision) return
      checks.value = results
      verification.value = results.every(Boolean) ? 'verified' : 'broken'
    } catch {
      if (current === revision) verification.value = 'unavailable'
    }
  },
  { immediate: true },
)
</script>

<template>
  <section class="card">
    <div class="approval-head">
      <h2>{{ $t('agentCards.traceTitle') }}</h2>
      <span v-if="entries.length" class="pill" :class="{ 'pill-ok': verification === 'verified', 'pill-bad': verification === 'broken' }" aria-live="polite">
        {{ $t(`agentCards.${verification === 'checking' ? 'hashChecking' : verification === 'unavailable' ? 'hashUnavailable' : verification}`) }}
      </span>
    </div>

    <ol class="trace">
      <li v-for="entry in displayed" :key="entry.index" :data-testid="entry.grouped ? 'policy-check-group' : failed(entry) ? 'policy-check-failure' : 'audit-entry'" :data-sku="productOf(entry)" :class="{ broken: entry.grouped ? entry.indices.some((i) => checks[i] === false) : checks[entry.rawIndex] === false, 'policy-failure': failed(entry) }">
        <template v-if="entry.grouped">
          <div class="trace-top"><strong>Policy checks · {{ entry.stage }}</strong><span class="pill pill-ok">{{ entry.entries.length }} passed</span></div>
          <details class="trace-evidence" data-testid="policy-group-evidence">
            <summary>View every check and original hash</summary>
            <article v-for="raw in entry.entries" :key="raw.index">
              <p>{{ raw.reason }}</p><p class="thought">{{ raw.thought }}</p>
              <pre>{{ JSON.stringify(raw, null, 2) }}</pre>
            </article>
          </details>
        </template>
        <template v-else>
        <div class="trace-top">
          <span class="trace-event">{{ $te(`agentCards.events.${entry.event}`) ? $t(`agentCards.events.${entry.event}`) : entry.event }}</span>
          <span class="pill small">{{ entry.status }}</span>
          <span class="muted mono">{{ entry.ts }}</span>
        </div>
        <p v-if="failed(entry)" class="danger-text"><strong>{{ productOf(entry) }}</strong> {{ entry.result?.rule }}</p>
        <p class="thought">{{ entry.thought }}</p>
        <p class="muted">{{ toolSummary(entry) }}</p>
        <details v-if="entry.result" class="trace-evidence">
          <summary>{{ $t('agentCards.toolEvidence') }}</summary>
          <pre>{{ JSON.stringify(entry.result, null, 2) }}</pre>
        </details>
        <p class="hashes mono muted">
          <span :title="entry.prev_hash">prev {{ shortHash(entry.prev_hash) }}</span>
          <span :title="entry.hash">hash {{ shortHash(entry.hash) }}</span>
        </p>
        </template>
      </li>
    </ol>
    <details class="trace-evidence" data-testid="full-audit">
      <summary>Full audit · {{ sorted.length }} original entries</summary>
      <pre>{{ JSON.stringify(sorted, null, 2) }}</pre>
    </details>
  </section>
</template>

<style scoped>
.policy-failure { border-left: 3px solid var(--danger, #b74136); padding-left: 12px; }
</style>
