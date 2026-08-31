<script setup>
import { computed, useId } from 'vue'

const props = defineProps({
  movie: {
    type: Object,
    required: true,
  },
})

const instanceId = `movie-poster-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
const titleId = `${instanceId}-title`

const defaults = ['#18232d', '#4d6475', '#e8b869']

const palette = computed(() => {
  const supplied = Array.isArray(props.movie.posterPalette) ? props.movie.posterPalette : []
  return defaults.map((fallback, index) => supplied[index] || fallback)
})

const variant = computed(() => {
  const value = Number(props.movie.posterVariant)
  return Number.isFinite(value) ? ((Math.max(1, Math.round(value)) - 1) % 6) + 1 : 1
})

const titleLines = computed(() => {
  const words = String(props.movie.title || 'Untitled').trim().toUpperCase().split(/\s+/)
  const lines = []
  const maxLength = 16

  for (const word of words) {
    const current = lines.at(-1)
    if (!current || (current.length + word.length + 1 > maxLength && lines.length < 3)) {
      lines.push(word)
    } else {
      lines[lines.length - 1] = `${current} ${word}`
    }
  }

  if (lines.length > 3) {
    lines[2] = lines.slice(2).join(' ')
    lines.length = 3
  }

  return lines
})

const titleSize = computed(() => {
  const longest = Math.max(...titleLines.value.map((line) => line.length))
  let size = 26
  if (longest > 20) size = 19
  else if (longest > 16) size = 22

  if (titleLines.value.length >= 3) return Math.min(size, 19)
  if (titleLines.value.length === 2) return Math.min(size, 23)
  return size
})

const yearLabel = computed(() => String(props.movie.year || ''))
const accessibleTitle = computed(() => `${props.movie.title || 'Untitled'}, ${yearLabel.value} — abstract poster artwork`)
const titleStartY = computed(() => 423 - (titleLines.value.length - 1) * (titleSize.value + 2))
const yearY = computed(() => Math.min(388, titleStartY.value - 18))
</script>

<template>
  <svg
    class="movie-poster"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 300 450"
    preserveAspectRatio="xMidYMid slice"
    role="img"
    :aria-labelledby="titleId"
  >
    <title :id="titleId">{{ accessibleTitle }}</title>

    <defs>
      <linearGradient :id="`${instanceId}-background`" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" :stop-color="palette[0]" />
        <stop offset="0.58" :stop-color="palette[1]" />
        <stop offset="1" :stop-color="palette[0]" />
      </linearGradient>
      <radialGradient :id="`${instanceId}-flare`" cx="50%" cy="42%" r="62%">
        <stop offset="0" :stop-color="palette[2]" stop-opacity="0.98" />
        <stop offset="0.38" :stop-color="palette[1]" stop-opacity="0.65" />
        <stop offset="1" :stop-color="palette[0]" stop-opacity="0" />
      </radialGradient>
      <linearGradient :id="`${instanceId}-fade`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#000" stop-opacity="0" />
        <stop offset="0.54" stop-color="#000" stop-opacity="0.15" />
        <stop offset="1" stop-color="#000" stop-opacity="0.82" />
      </linearGradient>
      <linearGradient :id="`${instanceId}-glass`" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#fff" stop-opacity="0.04" />
        <stop offset="0.5" stop-color="#fff" stop-opacity="0.35" />
        <stop offset="1" stop-color="#fff" stop-opacity="0" />
      </linearGradient>
      <filter :id="`${instanceId}-grain`" x="-15%" y="-15%" width="130%" height="130%">
        <feTurbulence type="fractalNoise" baseFrequency="0.88" numOctaves="2" seed="7" result="noise" />
        <feColorMatrix in="noise" type="saturate" values="0" result="mono" />
        <feComponentTransfer in="mono" result="softNoise">
          <feFuncA type="table" tableValues="0 0.12" />
        </feComponentTransfer>
        <feBlend in="SourceGraphic" in2="softNoise" mode="soft-light" />
      </filter>
      <filter :id="`${instanceId}-glow`" x="-60%" y="-60%" width="220%" height="220%">
        <feGaussianBlur stdDeviation="10" />
      </filter>
      <clipPath :id="`${instanceId}-arch`">
        <path d="M67 310V145a83 83 0 0 1 166 0v165Z" />
      </clipPath>
    </defs>

    <rect width="300" height="450" :fill="`url(#${instanceId}-background)`" />

    <g :filter="`url(#${instanceId}-grain)`">
      <!-- Variant 1: moonlit architectural portrait -->
      <g v-if="variant === 1">
        <circle cx="218" cy="94" r="60" :fill="palette[2]" opacity="0.86" />
        <circle cx="239" cy="77" r="61" :fill="palette[0]" opacity="0.88" />
        <path d="M24 336V151a126 126 0 0 1 252 0v185" fill="none" :stroke="palette[2]" stroke-opacity="0.36" stroke-width="3" />
        <path d="M48 336V159a102 102 0 0 1 204 0v177" fill="none" stroke="#fff" stroke-opacity="0.16" stroke-width="1.5" />
        <path d="M107 307c5-47 20-78 43-78s38 31 43 78l12 78H95Z" :fill="palette[0]" opacity="0.96" />
        <ellipse cx="150" cy="202" rx="26" ry="34" :fill="palette[2]" opacity="0.46" />
        <path d="M125 203c5-43 47-48 54-2-9-13-20-20-29-20s-18 7-25 22Z" :fill="palette[0]" />
        <path d="m70 84 30 184M92 68l27 156M232 142l-22 151" stroke="#fff" stroke-opacity="0.11" />
      </g>

      <!-- Variant 2: mirrored figures and a narrow threshold -->
      <g v-else-if="variant === 2">
        <ellipse cx="150" cy="205" rx="130" ry="176" :fill="`url(#${instanceId}-flare)`" opacity="0.72" />
        <path d="M150 27v316" stroke="#fff" stroke-opacity="0.24" />
        <path d="M30 79 150 210 270 79M30 316l120-106 120 106" fill="none" :stroke="palette[2]" stroke-opacity="0.35" stroke-width="2" />
        <g :fill="palette[0]">
          <ellipse cx="106" cy="194" rx="27" ry="34" />
          <path d="M56 347c8-75 23-120 50-120s43 45 50 120Z" />
          <ellipse cx="194" cy="194" rx="27" ry="34" />
          <path d="M144 347c8-75 23-120 50-120s43 45 50 120Z" />
        </g>
        <path d="M84 196c13-12 29-21 44-24M216 196c-13-12-29-21-44-24" fill="none" :stroke="palette[2]" stroke-opacity="0.62" stroke-width="5" />
        <circle cx="150" cy="123" r="7" :fill="palette[2]" />
        <circle cx="150" cy="123" r="25" :stroke="palette[2]" stroke-opacity="0.42" fill="none" />
      </g>

      <!-- Variant 3: heat, orbit and a lone observer -->
      <g v-else-if="variant === 3">
        <circle cx="160" cy="170" r="118" :fill="`url(#${instanceId}-flare)`" />
        <circle cx="164" cy="168" r="76" fill="none" :stroke="palette[2]" stroke-width="3" stroke-opacity="0.72" />
        <circle cx="164" cy="168" r="102" fill="none" stroke="#fff" stroke-width="1" stroke-opacity="0.26" />
        <path d="M-25 239 329 93M-18 280 320 142M-10 315 318 192" :stroke="palette[2]" stroke-opacity="0.43" stroke-width="5" />
        <path d="m42 51 72 292M274 40 190 340" stroke="#fff" stroke-opacity="0.16" />
        <ellipse cx="146" cy="234" rx="31" ry="39" :fill="palette[0]" />
        <path d="M82 386c8-81 28-126 64-126s57 45 65 126Z" :fill="palette[0]" />
        <path d="M117 235c8-24 47-27 59 0-18-8-39-8-59 0Z" :fill="palette[2]" opacity="0.6" />
        <circle cx="164" cy="168" r="18" :fill="palette[2]" :filter="`url(#${instanceId}-glow)`" opacity="0.9" />
      </g>

      <!-- Variant 4: editorial monochrome collage -->
      <g v-else-if="variant === 4">
        <rect x="18" y="22" width="264" height="319" fill="#f4f1e8" opacity="0.92" />
        <rect x="36" y="47" width="93" height="122" :fill="palette[1]" />
        <rect x="151" y="47" width="110" height="58" :fill="palette[0]" />
        <rect x="151" y="120" width="110" height="49" :fill="palette[2]" />
        <rect x="36" y="189" width="225" height="129" :fill="palette[0]" />
        <path d="M27 177h246M140 31v296" stroke="#171717" stroke-width="4" opacity="0.75" />
        <circle cx="83" cy="108" r="37" fill="#fff" opacity="0.72" />
        <path d="m54 143 58-70M48 126l70-42" stroke="#171717" stroke-width="3" opacity="0.72" />
        <path d="M164 306c4-61 18-95 42-95s39 34 43 95Z" fill="#e5e1d8" />
        <ellipse cx="206" cy="195" rx="22" ry="28" fill="#e5e1d8" />
        <path d="M54 214h68M54 232h48M54 250h76M54 268h53" stroke="#f5f2ea" stroke-width="7" />
      </g>

      <!-- Variant 5: nocturnal landscape and signal lines -->
      <g v-else-if="variant === 5">
        <circle cx="228" cy="102" r="50" :fill="palette[2]" opacity="0.72" />
        <circle cx="228" cy="102" r="74" :stroke="palette[2]" stroke-opacity="0.28" stroke-width="2" fill="none" />
        <circle cx="228" cy="102" r="98" :stroke="palette[2]" stroke-opacity="0.13" fill="none" />
        <path d="M0 282 75 205l38 41 47-84 43 78 38-35 59 72v90H0Z" :fill="palette[0]" opacity="0.95" />
        <path d="M0 282 75 205l38 41 47-84 43 78 38-35 59 72" fill="none" :stroke="palette[2]" stroke-opacity="0.66" stroke-width="2" />
        <path d="M21 81h155M4 101h132M49 121h109" stroke="#fff" stroke-opacity="0.2" />
        <path d="M142 146v172M130 158l12-12 12 12M124 199h36M119 234h46" fill="none" :stroke="palette[2]" stroke-width="4" stroke-opacity="0.74" />
        <circle cx="142" cy="318" r="7" :fill="palette[2]" />
      </g>

      <!-- Variant 6: daylight, rhythm and open space -->
      <g v-else>
        <circle cx="68" cy="99" r="76" :fill="palette[2]" opacity="0.9" />
        <circle cx="245" cy="191" r="112" fill="#fff" opacity="0.08" />
        <path d="M-4 287c56-48 110-65 164-49 46 13 92 9 144-26v143H-4Z" :fill="palette[1]" opacity="0.78" />
        <path d="M-4 316c69-52 130-62 184-31 37 22 79 20 124-4v87H-4Z" :fill="palette[0]" opacity="0.86" />
        <g stroke="#fff" stroke-opacity="0.34" fill="none">
          <path d="M31 30v253M48 30v240M65 30v226" />
          <path d="M206 62c-37 51-40 113-8 186M224 54c-35 62-32 130 9 203" />
        </g>
        <path d="M124 284c5-58 20-92 45-92s40 34 45 92Z" :fill="palette[0]" />
        <ellipse cx="169" cy="177" rx="24" ry="30" :fill="palette[0]" />
        <path d="M144 177c8-18 42-22 50 0-15-7-33-7-50 0Z" :fill="palette[2]" opacity="0.68" />
      </g>
    </g>

    <rect width="300" height="450" :fill="`url(#${instanceId}-fade)`" />
    <path d="M18 361h264" stroke="#fff" stroke-opacity="0.28" />

    <g class="poster-copy" fill="#fff">
      <text x="21" :y="yearY" class="poster-year">{{ yearLabel }}</text>
      <text
        x="20"
        :y="titleStartY"
        class="poster-title"
        :font-size="titleSize"
      >
        <tspan
          v-for="(line, index) in titleLines"
          :key="`${line}-${index}`"
          x="20"
          :dy="index === 0 ? 0 : titleSize + 1"
        >{{ line }}</tspan>
      </text>
    </g>

    <rect x="1" y="1" width="298" height="448" rx="8" fill="none" stroke="#fff" stroke-opacity="0.16" stroke-width="2" />
  </svg>
</template>

<style scoped>
.movie-poster {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: #18232d;
  font-family: Inter, "Cantarell", system-ui, sans-serif;
  shape-rendering: geometricPrecision;
}

.poster-copy {
  text-shadow: 0 1px 4px rgb(0 0 0 / 55%);
}

.poster-year {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.2em;
  opacity: 0.75;
}

.poster-title {
  font-weight: 800;
  letter-spacing: -0.035em;
}
</style>
