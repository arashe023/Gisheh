<script setup>
import { computed } from 'vue'

const props = defineProps({
  name: {
    type: String,
    required: true,
  },
  size: {
    type: [Number, String],
    default: 20,
  },
  strokeWidth: {
    type: [Number, String],
    default: 1.8,
  },
  fill: {
    type: String,
    default: 'none',
  },
  title: {
    type: String,
    default: '',
  },
})

const aliases = {
  chevron: 'chevron-down',
  chevrons: 'chevrons-down',
}

const iconName = computed(() => aliases[props.name] || props.name)
</script>

<template>
  <svg
    class="app-icon"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :fill="fill"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    :width="size"
    :height="size"
    :role="title ? 'img' : undefined"
    :aria-label="title || undefined"
    :aria-hidden="title ? undefined : 'true'"
    focusable="false"
  >
    <template v-if="iconName === 'menu'">
      <path d="M4 6.5h16M4 12h16M4 17.5h16" />
    </template>

    <template v-else-if="iconName === 'search'">
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.4 15.4 4.6 4.6" />
    </template>

    <template v-else-if="iconName === 'grid'">
      <rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1" />
      <rect x="14" y="3.5" width="6.5" height="6.5" rx="1" />
      <rect x="3.5" y="14" width="6.5" height="6.5" rx="1" />
      <rect x="14" y="14" width="6.5" height="6.5" rx="1" />
    </template>

    <template v-else-if="iconName === 'list'">
      <circle cx="4" cy="6" r="0.85" fill="currentColor" stroke="none" />
      <circle cx="4" cy="12" r="0.85" fill="currentColor" stroke="none" />
      <circle cx="4" cy="18" r="0.85" fill="currentColor" stroke="none" />
      <path d="M7.5 6H20M7.5 12H20M7.5 18H20" />
    </template>

    <polyline v-else-if="iconName === 'chevron-down'" points="5.5 8.5 12 15 18.5 8.5" />
    <polyline v-else-if="iconName === 'chevron-up'" points="5.5 15.5 12 9 18.5 15.5" />
    <polyline v-else-if="iconName === 'chevron-left'" points="15.5 5.5 9 12 15.5 18.5" />
    <polyline v-else-if="iconName === 'chevron-right'" points="8.5 5.5 15 12 8.5 18.5" />

    <template v-else-if="iconName === 'chevrons-down'">
      <polyline points="6 5.5 12 11.5 18 5.5" />
      <polyline points="6 12.5 12 18.5 18 12.5" />
    </template>

    <template v-else-if="iconName === 'chevrons-up'">
      <polyline points="6 11.5 12 5.5 18 11.5" />
      <polyline points="6 18.5 12 12.5 18 18.5" />
    </template>

    <template v-else-if="iconName === 'clock'">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3.2 2" />
    </template>

    <template v-else-if="iconName === 'calendar'">
      <rect x="3.5" y="5" width="17" height="15.5" rx="2.25" />
      <path d="M8 3.5V7M16 3.5V7M3.5 9.5h17" />
      <path d="M8 13h.01M12 13h.01M16 13h.01M8 17h.01M12 17h.01" stroke-width="2.4" />
    </template>

    <path
      v-else-if="iconName === 'heart'"
      d="M20.3 5.7a5.1 5.1 0 0 0-7.2 0L12 6.8l-1.1-1.1a5.1 5.1 0 1 0-7.2 7.2L12 21l8.3-8.1a5.1 5.1 0 0 0 0-7.2Z"
    />

    <template v-else-if="iconName === 'archive'">
      <path d="M4 8.5h16V20H4z" />
      <path d="M3 4h18v4.5H3zM9 13h6" />
    </template>

    <template v-else-if="iconName === 'settings'">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.14.36.35.7.64.96.3.27.69.42 1.1.44H21a2 2 0 1 1 0 4h-.09A1.7 1.7 0 0 0 19.4 15Z"
    />
    </template>

    <template v-else-if="iconName === 'film'">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" />
    </template>

    <polygon v-else-if="iconName === 'play'" points="8 5 19 12 8 19 8 5" />

    <path v-else-if="iconName === 'plus'" d="M12 4v16M4 12h16" />
    <polyline v-else-if="iconName === 'check'" points="4.5 12.5 9.5 17.5 19.5 6.5" />

    <path
      v-else-if="iconName === 'bookmark'"
      d="M6 4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21l-6-3.8L6 21V4.5Z"
    />

    <polygon
      v-else-if="iconName === 'star'"
      points="12 3.4 14.65 8.77 20.58 9.63 16.29 13.81 17.3 19.72 12 16.93 6.7 19.72 7.71 13.81 3.42 9.63 9.35 8.77 12 3.4"
    />

    <template v-else-if="iconName === 'more'">
      <circle cx="5" cy="12" r="1.25" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.25" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.25" fill="currentColor" stroke="none" />
    </template>

    <path v-else-if="iconName === 'close'" d="M5.5 5.5 18.5 18.5M18.5 5.5 5.5 18.5" />

    <template v-else-if="iconName === 'user'">
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 21a7.5 7.5 0 0 1 15 0" />
    </template>

    <path
      v-else-if="iconName === 'folder'"
      d="M3 6.5A1.5 1.5 0 0 1 4.5 5h5l2 2h8A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5v-11Z"
    />

    <rect v-else x="4" y="4" width="16" height="16" rx="3" stroke-dasharray="2.5 2.5" />
  </svg>
</template>

<style scoped>
.app-icon {
  display: block;
  flex: 0 0 auto;
  overflow: visible;
  vector-effect: non-scaling-stroke;
}
</style>
