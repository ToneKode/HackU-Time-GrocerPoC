<script setup>
// Flat food illustration for the log-in / register pages (inline SVG, theme-aware).
// variant 'login': Grocer shopping bag. variant 'register': crate of vegetables.
defineProps({ variant: { type: String, default: 'login' } })
</script>

<template>
  <svg class="auth-art" viewBox="0 0 520 600" role="img" :aria-label="$t(`auth.art.${variant}Alt`)">
    <defs>
      <filter :id="`shadow-${variant}`" x="-20%" y="-20%" width="140%" height="160%">
        <feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#1e325a" flood-opacity="0.16" />
      </filter>
    </defs>

    <!-- ================= LOG IN: shopping bag ================= -->
    <g v-if="variant === 'login'">
      <ellipse cx="270" cy="532" rx="190" ry="20" class="art-ground" />

      <!-- back handle -->
      <path d="M205 262 C205 170 335 170 335 262" fill="none" stroke="#b9773d" stroke-width="12" stroke-linecap="round" />

      <!-- baguette -->
      <g transform="rotate(-24 220 205)">
        <rect x="140" y="182" width="190" height="44" rx="22" fill="#e6ac5c" />
        <rect x="140" y="182" width="190" height="16" rx="8" fill="#f2c27c" opacity="0.7" />
        <path d="M175 190 l16 26 M215 190 l16 26 M255 190 l16 26 M295 190 l14 22" stroke="#c4843a" stroke-width="5" stroke-linecap="round" />
      </g>

      <!-- leafy greens -->
      <g>
        <path d="M330 262 C326 230 330 200 342 178" stroke="#3f8f46" stroke-width="7" fill="none" stroke-linecap="round" />
        <ellipse cx="322" cy="196" rx="30" ry="50" transform="rotate(-18 322 196)" fill="#57b05e" />
        <ellipse cx="356" cy="204" rx="28" ry="48" transform="rotate(26 356 204)" fill="#6cc474" />
        <ellipse cx="338" cy="180" rx="22" ry="42" fill="#3f9c48" />
        <path d="M338 150 L338 230" stroke="#2f7d37" stroke-width="3" stroke-linecap="round" opacity="0.6" />
      </g>

      <!-- milk carton -->
      <g>
        <rect x="236" y="168" width="64" height="96" rx="4" fill="#ffffff" />
        <path d="M236 168 L268 140 L300 168 Z" fill="#eef2f8" />
        <rect x="258" y="128" width="20" height="14" rx="3" fill="#3d6ef0" />
        <rect x="244" y="196" width="48" height="40" rx="8" fill="#3d6ef0" />
        <path d="M250 222 q8 -8 16 0 t16 0" stroke="#ffffff" stroke-width="3" fill="none" stroke-linecap="round" />
      </g>

      <!-- bag body -->
      <path d="M170 258 H370 L392 506 Q393 522 377 522 H163 Q147 522 148 506 Z" fill="#e9b27a" />
      <path d="M330 258 H370 L392 506 Q393 522 377 522 H352 Z" fill="#d99a5e" opacity="0.65" />
      <rect x="170" y="258" width="200" height="20" fill="#d4914f" />
      <!-- front handle -->
      <path d="M220 286 C220 238 320 238 320 286" fill="none" stroke="#c4843a" stroke-width="10" stroke-linecap="round" />
      <circle cx="270" cy="392" r="46" fill="#fff8ee" opacity="0.9" />
      <text x="270" y="400" text-anchor="middle" class="art-logo">grocer</text>

      <!-- oranges -->
      <circle cx="150" cy="505" r="38" fill="#f59f00" />
      <circle cx="138" cy="492" r="10" fill="#ffd27a" opacity="0.6" />
      <path d="M150 469 l6 -10" stroke="#3f8f46" stroke-width="5" stroke-linecap="round" />
      <circle cx="98" cy="522" r="26" fill="#fab005" />
      <circle cx="90" cy="514" r="7" fill="#ffe08a" opacity="0.6" />

      <!-- apples -->
      <circle cx="398" cy="506" r="34" fill="#e03131" />
      <circle cx="386" cy="494" r="9" fill="#ff8787" opacity="0.55" />
      <path d="M398 472 q2 -12 10 -16" stroke="#6b3e1f" stroke-width="4" fill="none" stroke-linecap="round" />
      <path d="M404 462 q16 -10 24 2 q-14 8 -24 -2 Z" fill="#40a14a" />
      <circle cx="446" cy="524" r="24" fill="#c92a2a" />
      <circle cx="438" cy="516" r="6" fill="#ff8787" opacity="0.5" />

      <!-- floating: price tag -->
      <g transform="translate(26 74)" :filter="`url(#shadow-${variant})`">
        <rect width="176" height="92" rx="18" class="art-card" />
        <rect x="16" y="16" width="52" height="24" rx="8" fill="#ffd84a" />
        <text x="42" y="33" text-anchor="middle" class="art-badge">−20%</text>
        <text x="80" y="33" class="art-strike">HK$27.50</text>
        <text x="16" y="72" class="art-price">HK$21.90</text>
      </g>

      <!-- floating: 30-day low chart -->
      <g transform="translate(360 104)" :filter="`url(#shadow-${variant})`">
        <rect width="140" height="104" rx="18" class="art-card" />
        <text x="16" y="28" class="art-label">{{ $t('auth.art.low') }}</text>
        <path d="M16 54 H46 V44 H74 V70 H100 V78 H124" fill="none" class="art-line" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />
        <circle cx="124" cy="78" r="5" class="art-dot" />
      </g>

      <!-- floating: approved chip -->
      <g transform="translate(372 300)" :filter="`url(#shadow-${variant})`">
        <rect width="136" height="44" rx="22" class="art-card" />
        <circle cx="24" cy="22" r="12" fill="#1f9d6b" />
        <path d="M18 22 l4 4 l8 -9" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round" />
        <text x="44" y="27" class="art-chip">{{ $t('auth.art.approved') }}</text>
      </g>
    </g>

    <!-- ================= REGISTER: vegetable crate ================= -->
    <g v-else>
      <ellipse cx="260" cy="534" rx="200" ry="20" class="art-ground" />

      <!-- carrots (behind) -->
      <g transform="rotate(-28 190 300)">
        <path d="M176 230 L204 230 L190 360 Z" fill="#f76707" />
        <path d="M180 260 h12 M184 290 h10 M186 320 h8" stroke="#d9480f" stroke-width="3" stroke-linecap="round" />
        <path d="M190 232 q-14 -30 -4 -46 q8 18 4 46 q6 -30 22 -38 q-4 22 -22 38" fill="#40a14a" />
      </g>
      <g transform="rotate(-12 222 300)">
        <path d="M210 236 L236 236 L223 352 Z" fill="#fd7e14" />
        <path d="M223 238 q-12 -26 -2 -42 q8 16 2 42 q6 -26 20 -32 q-4 20 -20 32" fill="#4caf50" />
      </g>

      <!-- broccoli -->
      <g>
        <path d="M318 330 L326 268 L346 268 L352 330 Z" fill="#8bc34a" />
        <circle cx="314" cy="252" r="26" fill="#2f9e44" />
        <circle cx="346" cy="236" r="30" fill="#37b24d" />
        <circle cx="374" cy="258" r="24" fill="#2b8a3e" />
        <circle cx="338" cy="266" r="22" fill="#40c057" />
        <circle cx="330" cy="232" r="6" fill="#69db7c" opacity="0.6" />
        <circle cx="360" cy="248" r="5" fill="#69db7c" opacity="0.6" />
      </g>

      <!-- aubergine -->
      <g transform="rotate(30 260 300)">
        <ellipse cx="262" cy="306" rx="30" ry="58" fill="#7048e8" />
        <ellipse cx="252" cy="290" rx="8" ry="26" fill="#9775fa" opacity="0.6" />
        <path d="M246 252 q16 -14 32 0 q-16 6 -32 0 Z" fill="#40a14a" />
        <rect x="258" y="234" width="8" height="18" rx="4" fill="#2b8a3e" />
      </g>

      <!-- tomatoes + lemon on top of crate -->
      <circle cx="170" cy="330" r="30" fill="#f03e3e" />
      <circle cx="160" cy="320" r="8" fill="#ffa8a8" opacity="0.6" />
      <path d="M170 302 l-10 -6 l10 2 l2 -10 l4 10 l10 -2 l-8 8" fill="#2f9e44" />
      <circle cx="226" cy="338" r="24" fill="#e03131" />
      <path d="M226 316 l-8 -4 l8 2 l2 -8 l3 8 l8 -2 l-6 6" fill="#2f9e44" />
      <ellipse cx="400" cy="330" rx="34" ry="26" fill="#ffd43b" />
      <ellipse cx="390" cy="322" rx="10" ry="6" fill="#fff3bf" opacity="0.7" />
      <path d="M432 330 l10 -2" stroke="#fab005" stroke-width="6" stroke-linecap="round" />

      <!-- crate -->
      <rect x="110" y="340" width="320" height="180" rx="16" fill="#d9a066" />
      <rect x="110" y="340" width="320" height="22" rx="10" fill="#c48a52" />
      <path d="M110 404 H430 M110 462 H430" stroke="#b97d45" stroke-width="5" />
      <path d="M170 362 V520 M370 362 V520" stroke="#c48a52" stroke-width="8" opacity="0.6" />
      <rect x="226" y="380" width="88" height="20" rx="10" fill="#9c6331" />

      <!-- floating: welcome -->
      <g transform="translate(24 96)" :filter="`url(#shadow-${variant})`">
        <rect width="178" height="64" rx="20" class="art-card" />
        <circle cx="34" cy="32" r="18" class="art-avatar" />
        <path d="M34 26 m-6 0 a6 6 0 1 0 12 0 a6 6 0 1 0 -12 0 M24 44 q10 -12 20 0" class="art-avatar-ink" fill="none" stroke-width="3" stroke-linecap="round" />
        <text x="62" y="38" class="art-chip">{{ $t('auth.art.welcome') }}</text>
      </g>

      <!-- floating: saved -->
      <g transform="translate(374 128)" :filter="`url(#shadow-${variant})`">
        <rect width="128" height="48" rx="24" class="art-card" />
        <path d="M30 34 l-11 -11 a7 7 0 0 1 11 -9 a7 7 0 0 1 11 9 Z" fill="#e5484d" />
        <text x="52" y="30" class="art-chip">{{ $t('auth.art.saved') }}</text>
      </g>

      <!-- floating: price drop -->
      <g transform="translate(332 430)" :filter="`url(#shadow-${variant})`">
        <rect width="170" height="88" rx="18" class="art-card" />
        <text x="16" y="28" class="art-label">{{ $t('auth.art.drop') }}</text>
        <text x="16" y="62" class="art-price">−15%</text>
        <path d="M104 40 L124 52 L138 46 L156 66" fill="none" class="art-line" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M148 66 H156 V58" fill="none" class="art-line" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
      </g>
    </g>
  </svg>
</template>
