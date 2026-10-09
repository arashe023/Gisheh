"""Layout shared by Gisheh components."""

from __future__ import annotations
import random
from dataclasses import dataclass
from typing import Any
from .constants import (
    GRID_CARD_WIDTH,
    GRID_COLUMN_GAP,
    GRID_HORIZONTAL_PADDING,
    GRID_MAX_COLUMNS,
)
from .models import (
    TitleRecord,
)


def grid_columns_for_width(width: int) -> int:
    """Return the FlowBox column count implied by the card's real minimum width."""
    content_width = max(1, width - GRID_HORIZONTAL_PADDING)
    columns = (content_width + GRID_COLUMN_GAP) // (GRID_CARD_WIDTH + GRID_COLUMN_GAP)
    return max(1, min(GRID_MAX_COLUMNS, columns))


SIDEBAR_EXPANDED = "expanded"

SIDEBAR_HIDDEN = "hidden"

DETAILS_INLINE = "inline"

DETAILS_OVERLAY = "overlay"

DETAILS_NAVIGATION = "navigation"

EXPLORE_SAFE_CONTENT_WIDTH = 480

RESPONSIVE_LAYOUT_GAPS = 24

RESPONSIVE_WIDE_ENTER_WIDTH = 1200

RESPONSIVE_WIDE_EXIT_WIDTH = 1160

RESPONSIVE_SIDEBAR_ENTER_WIDTH = 1040

RESPONSIVE_SIDEBAR_EXIT_WIDTH = 1000

RESPONSIVE_INLINE_ENTER_WIDTH = 980

RESPONSIVE_INLINE_EXIT_WIDTH = 940

RESPONSIVE_NARROW_ENTER_WIDTH = 720

RESPONSIVE_NARROW_EXIT_WIDTH = 760

RESPONSIVE_WIDE_WIDTH = RESPONSIVE_WIDE_ENTER_WIDTH

RESPONSIVE_MEDIUM_WIDTH = RESPONSIVE_INLINE_ENTER_WIDTH

RESPONSIVE_NARROW_WIDTH = RESPONSIVE_NARROW_ENTER_WIDTH

SIDEBAR_EXPANDED_MIN_WIDTH = 248

SIDEBAR_EXPANDED_MAX_WIDTH = 300

DETAILS_INLINE_WIDTH = 384

DETAILS_OVERLAY_MAX_WIDTH = 388

DETAILS_OVERLAY_MIN_WIDTH = 280

DETAILS_NARROW_SAFE_MARGIN = 48

EXPLORE_COLUMN_HYSTERESIS = 20

COMPACT_MEDIA_SWITCHER_WIDTH = 640


@dataclass(frozen=True, slots=True)
class ResponsiveLayout:
    sidebar_mode: str
    details_mode: str


def responsive_layout_for_width(
    width: int,
    *,
    details_open: bool = False,
    current_layout: ResponsiveLayout | None = None,
) -> ResponsiveLayout:
    """Map allocated window width to an explicit responsive layout decision.

    The result depends only on its inputs so layout states stay deterministic
    and unit-testable without GTK widgets.
    """
    normalized = max(0, int(width))
    previous_sidebar = (
        current_layout.sidebar_mode if current_layout is not None else None
    )
    previous_details = (
        current_layout.details_mode if current_layout is not None else None
    )

    # A docked sidebar is allowed only when its own minimum, the fixed details
    # panel, gaps and a useful Explore allocation can coexist.  When details
    # are closed, the panel has no allocation and the normal wide breakpoint
    # may keep the sidebar docked.
    required_inline_with_sidebar = (
        SIDEBAR_EXPANDED_MIN_WIDTH
        + DETAILS_INLINE_WIDTH
        + EXPLORE_SAFE_CONTENT_WIDTH
        + RESPONSIVE_LAYOUT_GAPS
    )
    if details_open:
        wide_enter = max(RESPONSIVE_WIDE_ENTER_WIDTH, required_inline_with_sidebar)
        wide_exit = max(RESPONSIVE_WIDE_EXIT_WIDTH, required_inline_with_sidebar)
    else:
        wide_enter = RESPONSIVE_SIDEBAR_ENTER_WIDTH
        wide_exit = RESPONSIVE_SIDEBAR_EXIT_WIDTH
    keep_wide = previous_sidebar == SIDEBAR_EXPANDED and normalized >= wide_exit
    can_dock = normalized >= wide_enter or keep_wide
    if details_open and normalized < required_inline_with_sidebar:
        can_dock = False
    sidebar_mode = SIDEBAR_EXPANDED if can_dock else SIDEBAR_HIDDEN

    if not details_open:
        # The inactive surface stays in its desktop home.  This prevents an
        # unnecessary mobile reparent before a title has been selected.
        return ResponsiveLayout(sidebar_mode, DETAILS_INLINE)

    keep_navigation = (
        previous_details == DETAILS_NAVIGATION
        and normalized < RESPONSIVE_NARROW_EXIT_WIDTH
    )
    if normalized < RESPONSIVE_NARROW_ENTER_WIDTH or keep_navigation:
        return ResponsiveLayout(SIDEBAR_HIDDEN, DETAILS_NAVIGATION)

    required_inline = (
        (SIDEBAR_EXPANDED_MIN_WIDTH if sidebar_mode == SIDEBAR_EXPANDED else 0)
        + DETAILS_INLINE_WIDTH
        + EXPLORE_SAFE_CONTENT_WIDTH
        + RESPONSIVE_LAYOUT_GAPS
    )
    inline_enter = max(RESPONSIVE_INLINE_ENTER_WIDTH, required_inline)
    inline_exit = max(RESPONSIVE_INLINE_EXIT_WIDTH, required_inline)
    keep_inline = previous_details == DETAILS_INLINE and normalized >= inline_exit
    if normalized >= inline_enter or keep_inline:
        return ResponsiveLayout(sidebar_mode, DETAILS_INLINE)
    return ResponsiveLayout(SIDEBAR_HIDDEN, DETAILS_OVERLAY)


def details_back_action(inner_tag: str) -> str:
    """Map the visible inner details page to its Back behavior.

    Returns ``"pop-season"`` (episode → season), ``"pop-title"``
    (season → title), or ``"close"`` (title → content).
    """
    if inner_tag == "episode":
        return "pop-season"
    if inner_tag == "season":
        return "pop-title"
    return "close"


def should_refresh_simkl_stats(
    *,
    has_incremental_state: bool,
    repairing_metadata: bool,
    cached_stats: dict[str, Any],
    activities: dict[str, Any],
    last_sync: str,
) -> bool:
    """Avoid the expensive statistics request when account activity is unchanged."""
    if not cached_stats:
        return True
    if repairing_metadata:
        return False
    return not has_incremental_state or activities.get("all") != last_sync


def build_explore_layout_plan(
    count: int,
    columns: int,
    seed: int,
) -> tuple[tuple[tuple[str, int], ...], ...]:
    """Build varied rows without ever assigning one card the complete width."""
    columns = max(1, columns)
    if columns == 1:
        patterns = ((("poster", 1),),)
    elif columns == 2:
        patterns = ((("poster", 1), ("poster", 1)),)
    elif columns == 3:
        patterns = ((("poster", 1), ("poster", 1), ("poster", 1)),)
    elif columns == 4:
        patterns = (
            (("poster", 1), ("poster", 1), ("poster", 1), ("poster", 1)),
            (("landscape", 2), ("landscape", 2)),
            (("landscape", 2), ("poster", 1), ("poster", 1)),
            (("poster", 1), ("poster", 1), ("landscape", 2)),
        )
    else:
        patterns = (
            tuple(("poster", 1) for _ in range(columns)),
            (
                ("hero", 3),
                ("landscape", 2),
                *(("poster", 1) for _ in range(columns - 5)),
            ),
            (
                ("landscape", 2),
                ("hero", 3),
                *(("poster", 1) for _ in range(columns - 5)),
            ),
            (("hero", 3), *(("poster", 1) for _ in range(columns - 3))),
            (
                ("landscape", 2),
                ("landscape", 2),
                *(("poster", 1) for _ in range(columns - 4)),
            ),
            (("landscape", 2), *(("poster", 1) for _ in range(columns - 2))),
        )

    rng = random.Random(seed)
    rows: list[tuple[tuple[str, int], ...]] = []
    remaining = max(0, count)
    previous_signature: tuple[str, ...] | None = None
    while remaining:
        candidates = [pattern for pattern in patterns if len(pattern) <= remaining]
        if not candidates:
            rows.append(tuple(("poster", 1) for _ in range(remaining)))
            break
        alternatives = [
            pattern
            for pattern in candidates
            if tuple(kind for kind, _span in pattern) != previous_signature
        ]
        pattern = rng.choice(alternatives or candidates)
        rows.append(pattern)
        previous_signature = tuple(kind for kind, _span in pattern)
        remaining -= len(pattern)
    return tuple(rows)


def preserve_explore_page_prefix(
    existing: tuple[TitleRecord, ...],
    filtered: tuple[TitleRecord, ...],
) -> tuple[TitleRecord, ...]:
    """Keep rendered pagination results stable and append newly visible rows."""
    filtered_by_id = {record.id: record for record in filtered}
    existing_ids = tuple(
        record.id for record in existing if record.id in filtered_by_id
    )
    existing_id_set = set(existing_ids)
    return (
        *(filtered_by_id[record_id] for record_id in existing_ids),
        *(record for record in filtered if record.id not in existing_id_set),
    )
