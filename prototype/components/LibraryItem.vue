<script setup>
import AppIcon from './AppIcon.vue'
import MoviePoster from './MoviePoster.vue'

defineProps({
  movie: {
    type: Object,
    required: true,
  },
  selected: {
    type: Boolean,
    default: false,
  },
  viewMode: {
    type: String,
    default: 'list',
  },
})

const emit = defineEmits(['select', 'menu'])
</script>

<template>
  <article
    class="library-item"
    :class="[{ 'is-selected': selected }, `is-${viewMode}`]"
    role="option"
    tabindex="0"
    :aria-selected="selected"
    @click="emit('select', movie.id)"
    @keydown.enter="emit('select', movie.id)"
    @keydown.space.prevent="emit('select', movie.id)"
  >
    <div class="poster-frame">
      <MoviePoster :movie="movie" />
      <span v-if="movie.userRating" class="user-score" :title="`Your rating: ${movie.userRating}`">
        {{ movie.userRating }}
      </span>
      <span v-if="movie.status === 'Watched'" class="watched-mark" title="Watched">
        <AppIcon name="check" :size="13" :stroke-width="2.8" />
      </span>
    </div>

    <div class="item-copy">
      <div class="item-kicker">
        <span>{{ movie.date }}</span>
        <span class="community-score" :aria-label="`Community rating ${movie.rating}`">
          <AppIcon name="star" :size="14" />
          {{ movie.rating.toFixed(1) }}
        </span>
      </div>

      <h3>{{ movie.title }}</h3>
      <p>{{ movie.description }}</p>

      <div class="item-meta">
        <span>{{ movie.year }}</span>
        <span>{{ movie.runtime }}</span>
        <span v-for="genreName in movie.genres.slice(0, 2)" :key="genreName">
          {{ genreName }}
        </span>
      </div>
    </div>

    <button
      class="icon-button flat item-menu"
      type="button"
      aria-label="More options"
      @click.stop="emit('menu', movie)"
    >
      <AppIcon name="more" :size="18" />
    </button>
  </article>
</template>
