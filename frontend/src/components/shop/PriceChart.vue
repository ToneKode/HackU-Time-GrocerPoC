<script setup>
// Price history line chart (inline SVG, no library).
// series: [{ key, label, color, points: [{ t, v }] }]  — all series share the same dates.
// annotate: label the period low and the last value (used for the single "min price" line).
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { money } from '../../lib/format.js'
import { useI18n } from 'vue-i18n'
import { dateLocale } from '../../i18n/index.js'

const { t } = useI18n()

const props = defineProps({
  series: { type: Array, required: true },
  annotate: Boolean,
  height: { type: Number, default: 260 },
})

const wrap = ref(null)
const width = ref(640)
let observer
const measure = () => { if (wrap.value) width.value = Math.max(280, wrap.value.clientWidth) }
onMounted(() => {
  measure()
  window.addEventListener('resize', measure)
  observer = new ResizeObserver(measure)
  observer.observe(wrap.value)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', measure)
  observer?.disconnect()
})

const pad = { top: 18, right: 16, bottom: 28, left: 56 }
const innerW = computed(() => width.value - pad.left - pad.right)
const innerH = computed(() => props.height - pad.top - pad.bottom)
const dates = computed(() => props.series[0]?.points.map((p) => p.t) ?? [])
const n = computed(() => dates.value.length)

// ---- Y scale with "nice" ticks ----
function niceStep(range) {
  const raw = range / 4
  const pow = 10 ** Math.floor(Math.log10(raw))
  return [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw)
}
const yScale = computed(() => {
  const values = props.series.flatMap((s) => s.points.map((p) => p.v))
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  if (hi - lo < 1) { lo -= 1; hi += 1 }
  const step = niceStep(hi - lo)
  lo = Math.floor(lo / step) * step
  hi = Math.ceil(hi / step) * step
  const ticks = []
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 100) / 100)
  return { lo, hi, ticks }
})
const x = (i) => pad.left + (n.value > 1 ? (i / (n.value - 1)) * innerW.value : 0)
const y = (v) => pad.top + (1 - (v - yScale.value.lo) / (yScale.value.hi - yScale.value.lo)) * innerH.value

// ---- X ticks: ~5 dates ----
const fmtDate = (ts) => new Date(ts).toLocaleDateString(dateLocale(), { day: 'numeric', month: 'short' })
const xTicks = computed(() => {
  const count = Math.min(width.value < 480 ? 3 : 5, n.value)
  return Array.from({ length: count }, (_, k) => Math.round((k / (count - 1 || 1)) * (n.value - 1)))
})

// Step line: a price holds until the day it changes.
function stepPath(points) {
  let d = `M${x(0)},${y(points[0].v)}`
  for (let i = 1; i < points.length; i++) {
    if (points[i].v !== points[i - 1].v) d += `H${x(i)}V${y(points[i].v)}`
  }
  return d + `H${x(points.length - 1)}`
}
const paths = computed(() => props.series.map((s) => ({ ...s, d: stepPath(s.points) })))

// Today's price marker on each line (values are in the legend below the chart).
const endMarks = computed(() =>
  props.annotate ? [] : props.series.map((s) => ({ key: s.key, color: s.color, cy: y(s.points.at(-1).v) })),
)

const annotations = computed(() => {
  if (!props.annotate || !props.series.length) return []
  const pts = props.series[0].points
  let lowIndex = 0
  pts.forEach((p, i) => { if (p.v < pts[lowIndex].v) lowIndex = i })
  const last = pts.length - 1
  const list = [{ i: last, v: pts[last].v, text: money(pts[last].v), anchor: 'end' }]
  if (lowIndex !== last && pts[lowIndex].v !== pts[last].v) {
    list.push({ i: lowIndex, v: pts[lowIndex].v, text: t('chart.low', { price: money(pts[lowIndex].v) }), anchor: lowIndex < n.value / 2 ? 'start' : 'middle' })
  }
  return list
})

// ---- Hover / keyboard crosshair ----
const active = ref(null)
function onPointer(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const px = ((event.clientX - rect.left) / rect.width) * width.value
  const i = Math.round(((px - pad.left) / innerW.value) * (n.value - 1))
  active.value = Math.min(n.value - 1, Math.max(0, i))
}
function onKey(event) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const step = event.key === 'ArrowLeft' ? -1 : 1
  active.value = Math.min(n.value - 1, Math.max(0, (active.value ?? n.value - 1) + step))
}
const tooltip = computed(() => {
  if (active.value == null) return null
  const i = active.value
  const rows = props.series
    .map((s) => ({ key: s.key, label: s.label, color: s.color, v: s.points[i].v }))
    .sort((a, b) => a.v - b.v)
  const left = x(i)
  return { i, left, flip: left > width.value * 0.6, date: fmtDate(dates.value[i]), rows }
})
</script>

<template>
  <div ref="wrap" class="chart-wrap">
    <svg
      :width="width"
      :height="height"
      class="chart"
      role="img"
      tabindex="0"
      :aria-label="$t('chart.label')"
      @pointermove="onPointer"
      @pointerleave="active = null"
      @focus="active = n - 1"
      @blur="active = null"
      @keydown="onKey"
    >
      <!-- grid + y labels -->
      <g class="chart-grid">
        <template v-for="t in yScale.ticks" :key="t">
          <line :x1="pad.left" :x2="width - pad.right" :y1="y(t)" :y2="y(t)" />
          <text :x="pad.left - 8" :y="y(t)" dy="0.32em" text-anchor="end">{{ money(t).replace('.00', '') }}</text>
        </template>
      </g>
      <!-- x labels -->
      <g class="chart-axis">
        <text
          v-for="(i, k) in xTicks"
          :key="i"
          :x="x(i)"
          :y="height - 8"
          :text-anchor="k === 0 ? 'start' : k === xTicks.length - 1 ? 'end' : 'middle'"
        >{{ fmtDate(dates[i]) }}</text>
      </g>

      <!-- lines -->
      <path v-for="s in paths" :key="s.key" :d="s.d" class="chart-line" :style="{ stroke: s.color }" />

      <!-- end markers with a surface ring -->
      <circle
        v-for="m in endMarks"
        :key="m.key"
        :cx="x(n - 1)"
        :cy="m.cy"
        r="4"
        class="chart-dot"
        :style="{ fill: m.color }"
      />

      <!-- selective direct labels (single series) -->
      <g v-for="a in annotations" :key="a.text" class="chart-annotation">
        <circle :cx="x(a.i)" :cy="y(a.v)" r="4" class="chart-dot" :style="{ fill: series[0].color }" />
        <text :x="x(a.i)" :y="y(a.v) - 10" :text-anchor="a.anchor">{{ a.text }}</text>
      </g>

      <!-- crosshair -->
      <g v-if="tooltip" class="chart-cross">
        <line :x1="tooltip.left" :x2="tooltip.left" :y1="pad.top" :y2="height - pad.bottom" />
        <circle
          v-for="r in tooltip.rows"
          :key="r.key"
          :cx="tooltip.left"
          :cy="y(r.v)"
          r="4"
          class="chart-dot"
          :style="{ fill: r.color }"
        />
      </g>
    </svg>

    <div
      v-if="tooltip"
      class="chart-tooltip"
      :style="{ left: tooltip.left + 'px', transform: tooltip.flip ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)' }"
    >
      <div class="tt-date">{{ tooltip.date }}</div>
      <div v-for="r in tooltip.rows" :key="r.key" class="tt-row">
        <span class="tt-key" :style="{ background: r.color }" />
        <strong>{{ money(r.v) }}</strong>
        <span class="tt-label">{{ r.label }}</span>
      </div>
    </div>
  </div>
</template>
