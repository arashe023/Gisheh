<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './components/AppIcon.vue'
import LibraryItem from './components/LibraryItem.vue'
import MoviePoster from './components/MoviePoster.vue'
import { library, libraryTotals } from './data/library'

const mediaTypes = ['Movies', 'Shows', 'Anime']
const embeddedMode = new URLSearchParams(window.location.search).get('embedded') === '1'
const statusItems = [
  { id: 'Watchlist', label: 'Watchlist', icon: 'bookmark' },
  { id: 'Watched', label: 'Watched', icon: 'clock' },
  { id: 'Calendar', label: 'Calendar', icon: 'calendar' },
  { id: 'Dropped', label: 'Dropped', icon: 'archive' },
]

const activeMediaType = ref('Movies')
const activeStatus = ref('Watched')
const selectedId = ref('hush-girls')
const query = ref('')
const genre = ref('All genres')
const sortBy = ref('recent')
const viewMode = ref('list')
const sidebarOpen = ref(false)
const detailsOpen = ref(true)
const searchInput = ref(null)
const toast = ref('')
let toastTimer

const bookmarked = ref(new Set(['hush-girls', 'dune-two', 'past-lives', 'pluto']))
const favorites = ref(new Set(['oppenheimer', 'perfect-days', 'frieren']))
const completed = ref(
  new Set(library.filter((item) => item.status === 'Watched').map((item) => item.id)),
)
const userRatings = ref(
  Object.fromEntries(library.filter((item) => item.userRating).map((item) => [item.id, item.userRating])),
)

const typeItems = computed(() => library.filter((item) => item.type === activeMediaType.value))

const genreOptions = computed(() => {
  const values = new Set(typeItems.value.flatMap((item) => item.genres))
  return ['All genres', ...Array.from(values).sort()]
})

const filteredItems = computed(() => {
  const normalizedQuery = query.value.trim().toLowerCase()
  const items = library.filter((item) => {
    const matchesType = item.type === activeMediaType.value
    const matchesStatus = item.status === activeStatus.value
    const matchesGenre = genre.value === 'All genres' || item.genres.includes(genre.value)
    const haystack = `${item.title} ${item.description} ${item.creator} ${item.genres.join(' ')}`.toLowerCase()
    return matchesType && matchesStatus && matchesGenre && (!normalizedQuery || haystack.includes(normalizedQuery))
  })

  return [...items].sort((a, b) => {
    if (sortBy.value === 'title') return a.title.localeCompare(b.title)
    if (sortBy.value === 'rating') return b.rating - a.rating
    if (sortBy.value === 'year') return b.year - a.year
    return b.order - a.order
  })
})

const selectedItem = computed(() => {
  return library.find((item) => item.id === selectedId.value) ?? filteredItems.value[0] ?? null
})

const totalForView = computed(() => libraryTotals[activeMediaType.value][activeStatus.value])

const resultDescription = computed(() => {
  if (query.value.trim() || genre.value !== 'All genres') {
    return `${filteredItems.value.length} matching ${filteredItems.value.length === 1 ? 'title' : 'titles'}`
  }
  return `Showing ${filteredItems.value.length} recent entries`
})

const detailStyle = computed(() => {
  const palette = selectedItem.value?.posterPalette ?? ['#1c3144', '#3584e4', '#9bbff1']
  return {
    '--detail-a': palette[0],
    '--detail-b': palette[1],
    '--detail-c': palette[2],
  }
})

function statusCount(status) {
  return libraryTotals[activeMediaType.value][status]
}

function chooseMediaType(type) {
  activeMediaType.value = type
  genre.value = 'All genres'
  query.value = ''
  sidebarOpen.value = false
}

function chooseStatus(status) {
  activeStatus.value = status
  query.value = ''
  genre.value = 'All genres'
  sidebarOpen.value = false
}

function selectItem(id) {
  selectedId.value = id
  detailsOpen.value = true
}

function toggleCollection(collectionRef, id, addedMessage, removedMessage) {
  const next = new Set(collectionRef.value)
  const hadItem = next.has(id)
  if (hadItem) next.delete(id)
  else next.add(id)
  collectionRef.value = next
  notify(hadItem ? removedMessage : addedMessage)
}

function toggleCompleted(id) {
  toggleCollection(completed, id, 'Marked as watched', 'Marked as unwatched')
}

function setUserRating(id, ratingValue) {
  userRatings.value = { ...userRatings.value, [id]: ratingValue }
  notify(`Your rating is now ${ratingValue}/10`)
}

function notify(message) {
  toast.value = message
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toast.value = ''
  }, 2400)
}

function focusSearch() {
  searchInput.value?.focus()
}

function handleShortcut(event) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    focusSearch()
  }
  if (event.key === 'Escape' && document.activeElement === searchInput.value) {
    query.value = ''
    searchInput.value?.blur()
  }
}

function handleNativeCommand(event) {
  const command = event.detail ?? {}

  if (command.action === 'set-media-type' && mediaTypes.includes(command.value)) {
    chooseMediaType(command.value)
  }

  if (command.action === 'focus-search') {
    focusSearch()
  }
}

watch([activeMediaType, activeStatus, genre], async () => {
  await nextTick()
  if (!filteredItems.value.some((item) => item.id === selectedId.value)) {
    selectedId.value = filteredItems.value[0]?.id ?? null
  }
})

watch(filteredItems, (items) => {
  if (items.length && !items.some((item) => item.id === selectedId.value)) {
    selectedId.value = items[0].id
  }
})

onMounted(() => {
  window.addEventListener('keydown', handleShortcut)
  window.addEventListener('cineshelf:native-command', handleNativeCommand)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleShortcut)
  window.removeEventListener('cineshelf:native-command', handleNativeCommand)
  window.clearTimeout(toastTimer)
})
</script>

<template>
  <div
    class="app-window"
    :class="{ 'sidebar-is-open': sidebarOpen, 'is-embedded': embeddedMode }"
  >
    <header class="titlebar">
      <div class="titlebar-start">
        <button
          class="icon-button flat navigation-toggle"
          type="button"
          aria-label="Toggle navigation"
          @click="sidebarOpen = !sidebarOpen"
        >
          <AppIcon name="menu" :size="19" />
        </button>

        <div class="app-identity" aria-label="CineShelf">
          <span class="app-symbol"><AppIcon name="film" :size="18" /></span>
          <span>CineShelf</span>
        </div>
      </div>

      <nav class="media-switcher" aria-label="Media type">
        <button
          v-for="type in mediaTypes"
          :key="type"
          type="button"
          :class="{ active: activeMediaType === type }"
          :aria-pressed="activeMediaType === type"
          @click="chooseMediaType(type)"
        >
          {{ type }}
        </button>
      </nav>

      <div class="titlebar-end">
        <button class="sync-state" type="button" @click="notify('Your library is up to date')">
          <span class="sync-dot"></span>
          <span>Synced</span>
        </button>
        <button class="icon-button flat header-search" type="button" aria-label="Search" @click="focusSearch">
          <AppIcon name="search" :size="18" />
        </button>
        <button class="profile-button" type="button" aria-label="Open profile">
          <span>AS</span>
        </button>
      </div>
    </header>

    <div class="workspace">
      <aside class="sidebar" aria-label="Library navigation">
        <div class="sidebar-scroll">
          <div class="sidebar-heading">
            <span>Library</span>
            <button class="icon-button flat small" type="button" aria-label="Add to library" @click="notify('Add dialog opened')">
              <AppIcon name="plus" :size="16" />
            </button>
          </div>

          <nav class="status-navigation">
            <button
              v-for="item in statusItems"
              :key="item.id"
              type="button"
              :class="{ active: activeStatus === item.id }"
              :aria-current="activeStatus === item.id ? 'page' : undefined"
              @click="chooseStatus(item.id)"
            >
              <AppIcon :name="item.icon" :size="18" />
              <span>{{ item.label }}</span>
              <span class="nav-count">{{ statusCount(item.id) }}</span>
            </button>
          </nav>

          <div class="sidebar-separator"></div>

          <div class="sidebar-heading">
            <span>Collections</span>
          </div>
          <nav class="collection-navigation">
            <button type="button" @click="notify('Favorites selected')">
              <span class="collection-icon favorite"><AppIcon name="heart" :size="15" /></span>
              <span>Favorites</span>
              <span class="nav-count">12</span>
            </button>
            <button type="button" @click="notify('Weekend picks selected')">
              <span class="collection-icon weekend"><AppIcon name="play" :size="14" /></span>
              <span>Weekend picks</span>
              <span class="nav-count">8</span>
            </button>
            <button type="button" @click="notify('Modern classics selected')">
              <span class="collection-icon classics"><AppIcon name="star" :size="14" /></span>
              <span>Modern classics</span>
              <span class="nav-count">16</span>
            </button>
          </nav>
        </div>

        <div class="sidebar-footer">
          <button class="storage-card" type="button" @click="notify('Library storage: 68% used')">
            <span class="storage-icon"><AppIcon name="folder" :size="17" /></span>
            <span class="storage-copy">
              <strong>Local library</strong>
              <span>12.4 GB of 18 GB</span>
            </span>
            <span class="storage-meter"><span></span></span>
          </button>
          <button class="settings-link" type="button" @click="notify('Preferences opened')">
            <AppIcon name="settings" :size="17" />
            <span>Preferences</span>
          </button>
        </div>
      </aside>

      <button class="sidebar-scrim" type="button" aria-label="Close navigation" @click="sidebarOpen = false"></button>

      <main class="library-view">
        <section class="library-header">
          <div class="heading-row">
            <div>
              <span class="eyebrow">My library / {{ activeMediaType }}</span>
              <div class="title-line">
                <h1>{{ activeStatus }}</h1>
                <span class="title-count">{{ totalForView }}</span>
              </div>
            </div>
            <button class="primary-button add-title" type="button" @click="notify(`Add ${activeMediaType.toLowerCase()} to ${activeStatus.toLowerCase()}`)">
              <AppIcon name="plus" :size="17" />
              <span>Add title</span>
            </button>
          </div>

          <div class="toolbar">
            <label class="search-entry">
              <AppIcon name="search" :size="17" />
              <input
                ref="searchInput"
                v-model="query"
                type="search"
                :placeholder="`Search ${activeMediaType.toLowerCase()}…`"
                aria-label="Search library"
              />
              <kbd v-if="!query">Ctrl K</kbd>
              <button v-else type="button" aria-label="Clear search" @click="query = ''">
                <AppIcon name="close" :size="14" />
              </button>
            </label>

            <label class="select-control">
              <span class="sr-only">Sort by</span>
              <select v-model="sortBy">
                <option value="recent">Last watched</option>
                <option value="title">Title</option>
                <option value="rating">Highest rated</option>
                <option value="year">Release year</option>
              </select>
              <AppIcon name="chevron-down" :size="15" />
            </label>

            <label class="select-control genre-select">
              <span class="sr-only">Filter by genre</span>
              <select v-model="genre">
                <option v-for="genreName in genreOptions" :key="genreName" :value="genreName">
                  {{ genreName }}
                </option>
              </select>
              <AppIcon name="chevron-down" :size="15" />
            </label>

            <div class="view-switcher" aria-label="View mode">
              <button
                type="button"
                aria-label="List view"
                :class="{ active: viewMode === 'list' }"
                :aria-pressed="viewMode === 'list'"
                @click="viewMode = 'list'"
              >
                <AppIcon name="list" :size="17" />
              </button>
              <button
                type="button"
                aria-label="Grid view"
                :class="{ active: viewMode === 'grid' }"
                :aria-pressed="viewMode === 'grid'"
                @click="viewMode = 'grid'"
              >
                <AppIcon name="grid" :size="17" />
              </button>
            </div>
          </div>
        </section>

        <section class="results-area">
          <div class="results-heading">
            <div>
              <strong>All ({{ totalForView }})</strong>
              <span>{{ resultDescription }}</span>
            </div>
            <button class="sort-direction" type="button" aria-label="Sort descending" @click="notify('Newest titles are shown first')">
              <AppIcon name="chevron-down" :size="17" />
            </button>
          </div>

          <div
            v-if="filteredItems.length"
            class="items"
            :class="`view-${viewMode}`"
            role="listbox"
            aria-label="Library titles"
          >
            <LibraryItem
              v-for="movie in filteredItems"
              :key="movie.id"
              :movie="movie"
              :selected="selectedItem?.id === movie.id"
              :view-mode="viewMode"
              @select="selectItem"
              @menu="notify(`More options for ${$event.title}`)"
            />
          </div>

          <div v-else class="empty-state">
            <span class="empty-icon"><AppIcon name="search" :size="26" /></span>
            <h2>No titles found</h2>
            <p>Try a different search term or clear the current genre filter.</p>
            <button class="secondary-button" type="button" @click="query = ''; genre = 'All genres'">
              Clear filters
            </button>
          </div>
        </section>
      </main>

      <aside
        v-if="selectedItem"
        class="details-pane"
        :class="{ 'is-closed': !detailsOpen }"
        :style="detailStyle"
        aria-label="Title details"
      >
        <div class="details-scroll">
          <div class="detail-hero">
            <div class="hero-orb orb-one"></div>
            <div class="hero-orb orb-two"></div>
            <div class="hero-lines"></div>
            <div class="detail-poster">
              <MoviePoster :movie="selectedItem" />
            </div>
            <span class="status-pill">
              <AppIcon :name="completed.has(selectedItem.id) ? 'check' : 'bookmark'" :size="13" />
              {{ completed.has(selectedItem.id) ? 'Watched' : selectedItem.status }}
            </span>
            <button class="icon-button flat detail-close" type="button" aria-label="Close details" @click="detailsOpen = false">
              <AppIcon name="close" :size="17" />
            </button>
          </div>

          <div class="detail-content">
            <div class="detail-title-row">
              <div>
                <span class="detail-overline">{{ selectedItem.year }} · {{ selectedItem.country }}</span>
                <h2>{{ selectedItem.title }}</h2>
              </div>
              <div class="rating-badge" :aria-label="`Community rating ${selectedItem.rating}`">
                <AppIcon name="star" :size="15" />
                <strong>{{ selectedItem.rating.toFixed(1) }}</strong>
              </div>
            </div>

            <div class="detail-actions">
              <button class="primary-button watched-action" type="button" @click="toggleCompleted(selectedItem.id)">
                <AppIcon :name="completed.has(selectedItem.id) ? 'check' : 'plus'" :size="17" />
                <span>{{ completed.has(selectedItem.id) ? 'Watched' : 'Mark watched' }}</span>
              </button>
              <button
                class="icon-button raised"
                :class="{ toggled: favorites.has(selectedItem.id) }"
                type="button"
                :aria-pressed="favorites.has(selectedItem.id)"
                aria-label="Favorite"
                @click="toggleCollection(favorites, selectedItem.id, 'Added to favorites', 'Removed from favorites')"
              >
                <AppIcon name="heart" :size="18" :fill="favorites.has(selectedItem.id) ? 'currentColor' : 'none'" />
              </button>
              <button
                class="icon-button raised"
                :class="{ toggled: bookmarked.has(selectedItem.id) }"
                type="button"
                :aria-pressed="bookmarked.has(selectedItem.id)"
                aria-label="Bookmark"
                @click="toggleCollection(bookmarked, selectedItem.id, 'Added to watchlist', 'Removed from watchlist')"
              >
                <AppIcon name="bookmark" :size="18" :fill="bookmarked.has(selectedItem.id) ? 'currentColor' : 'none'" />
              </button>
              <button class="icon-button raised" type="button" aria-label="More options" @click="notify(`More options for ${selectedItem.title}`)">
                <AppIcon name="more" :size="18" />
              </button>
            </div>

            <div class="metadata-chips">
              <span>{{ selectedItem.runtime }}</span>
              <span v-for="genreName in selectedItem.genres" :key="genreName">{{ genreName }}</span>
            </div>

            <section class="detail-section synopsis">
              <h3>Overview</h3>
              <p>{{ selectedItem.description }}</p>
            </section>

            <dl class="facts-grid">
              <div>
                <dt>Director / Creator</dt>
                <dd>{{ selectedItem.creator }}</dd>
              </div>
              <div>
                <dt>Release</dt>
                <dd>{{ selectedItem.year }}</dd>
              </div>
              <div>
                <dt>Country</dt>
                <dd>{{ selectedItem.country }}</dd>
              </div>
              <div>
                <dt>Activity</dt>
                <dd>{{ selectedItem.date }}</dd>
              </div>
            </dl>

            <section class="activity-card">
              <div class="activity-heading">
                <div>
                  <span>Your activity</span>
                  <strong>{{ completed.has(selectedItem.id) ? 'Completed' : 'Not watched yet' }}</strong>
                </div>
                <span>{{ completed.has(selectedItem.id) ? '100%' : '0%' }}</span>
              </div>
              <div class="progress-track" aria-label="Watch progress">
                <span :style="{ width: completed.has(selectedItem.id) ? '100%' : '0%' }"></span>
              </div>
            </section>

            <section class="detail-section rating-section">
              <div class="section-heading-row">
                <h3>Your rating</h3>
                <strong v-if="userRatings[selectedItem.id]">{{ userRatings[selectedItem.id] }}/10</strong>
                <span v-else>Not rated</span>
              </div>
              <div class="rating-scale" role="radiogroup" aria-label="Your rating">
                <button
                  v-for="score in 10"
                  :key="score"
                  type="button"
                  :class="{ active: userRatings[selectedItem.id] === score }"
                  :aria-checked="userRatings[selectedItem.id] === score"
                  role="radio"
                  @click="setUserRating(selectedItem.id, score)"
                >
                  {{ score }}
                </button>
              </div>
            </section>
          </div>
        </div>
      </aside>

      <button
        v-if="selectedItem && !detailsOpen"
        class="show-details-button"
        type="button"
        @click="detailsOpen = true"
      >
        <AppIcon name="chevron-left" :size="16" />
        Show details
      </button>
    </div>

    <Transition name="toast">
      <div v-if="toast" class="toast" role="status">
        <AppIcon name="check" :size="15" />
        {{ toast }}
      </div>
    </Transition>
  </div>
</template>
