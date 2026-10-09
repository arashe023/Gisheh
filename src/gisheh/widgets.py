"""Widgets shared by Gisheh components."""

from __future__ import annotations
import math
from gettext import gettext as _
from pathlib import Path
import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo
from .models import (
    TitleRecord,
)


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.removeprefix("#")
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _rounded_rectangle(
    context: cairo.Context,
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float,
) -> None:
    radius = min(radius, width / 2, height / 2)
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    context.arc(x + radius, y + radius, radius, math.pi, math.pi * 1.5)
    context.close_path()


class GeneratedPosterWidget(Gtk.DrawingArea):
    """Tiny native poster renderer; no image decoder or browser is required."""

    def __init__(
        self,
        record: TitleRecord,
        width: int,
        height: int,
        *,
        variant_offset: int = 0,
        show_text: bool = True,
        fixed_size: bool = True,
    ) -> None:
        super().__init__()
        self.record = record
        self.variant_offset = variant_offset
        self.show_text = show_text
        if fixed_size:
            self.set_content_width(width)
            self.set_content_height(height)
            self.set_size_request(width, height)
        self.set_tooltip_text(f"{record.title}, {record.year}")
        self.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Poster artwork for {title}").format(title=record.title)],
        )
        self.set_draw_func(self._draw)

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        context: cairo.Context,
        width: int,
        height: int,
    ) -> None:
        first, second, third = (
            _hex_to_rgb(color) for color in self.record.poster_palette
        )
        radius = min(11.0, width * 0.12)

        context.save()
        _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
        context.clip()

        gradient = cairo.LinearGradient(0, 0, width, height)
        gradient.add_color_stop_rgb(0, *first)
        gradient.add_color_stop_rgb(0.58, *second)
        gradient.add_color_stop_rgb(1, *third)
        context.set_source(gradient)
        context.paint()

        self._draw_art(context, width, height, third)

        if not self.show_text:
            fade = cairo.LinearGradient(0, height * 0.54, 0, height)
            fade.add_color_stop_rgba(0, 0, 0, 0, 0)
            fade.add_color_stop_rgba(1, 0, 0, 0, 0.48)
            context.set_source(fade)
            context.rectangle(0, height * 0.54, width, height * 0.46)
            context.fill()
            context.restore()
            context.set_line_width(1)
            context.set_source_rgba(1, 1, 1, 0.16)
            _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
            context.stroke()
            return

        context.set_source_rgba(0, 0, 0, 0.58)
        context.rectangle(0, height * 0.73, width, height * 0.27)
        context.fill()

        context.set_source_rgb(1, 1, 1)
        title = self.record.title.upper()
        context.move_to(width * 0.08, height * 0.87)
        title_layout = PangoCairo.create_layout(context)
        title_layout.set_text(title, -1)
        title_layout.set_width(int(width * 0.84 * Pango.SCALE))
        title_layout.set_ellipsize(Pango.EllipsizeMode.END)
        title_layout.set_single_paragraph_mode(True)
        title_font = Pango.FontDescription("Sans Bold")
        title_font.set_absolute_size(int(max(7.0, width * 0.085) * Pango.SCALE))
        title_layout.set_font_description(title_font)
        PangoCairo.show_layout(context, title_layout)

        context.set_source_rgba(1, 1, 1, 0.78)
        context.move_to(width * 0.08, height * 0.95)
        year_layout = PangoCairo.create_layout(context)
        year_layout.set_text(str(self.record.year), -1)
        year_font = Pango.FontDescription("Sans")
        year_font.set_absolute_size(int(max(6.0, width * 0.07) * Pango.SCALE))
        year_layout.set_font_description(year_font)
        PangoCairo.show_layout(context, year_layout)

        context.restore()

        context.set_line_width(1)
        context.set_source_rgba(1, 1, 1, 0.16)
        _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
        context.stroke()

    def _draw_art(
        self,
        context: cairo.Context,
        width: int,
        height: int,
        accent: tuple[float, float, float],
    ) -> None:
        variant = ((self.record.poster_variant - 1 + self.variant_offset) % 6) + 1
        context.set_line_width(max(1.0, width * 0.018))

        if variant == 1:
            context.set_source_rgba(*accent, 0.9)
            context.arc(width * 0.68, height * 0.23, width * 0.2, 0, math.tau)
            context.fill()
            context.set_source_rgba(0, 0, 0, 0.55)
            context.arc(width * 0.75, height * 0.18, width * 0.18, 0, math.tau)
            context.fill()
            context.arc(width * 0.5, height * 0.5, width * 0.1, 0, math.tau)
            context.fill()
            context.rectangle(width * 0.4, height * 0.57, width * 0.2, height * 0.26)
            context.fill()
        elif variant == 2:
            context.set_source_rgba(0, 0, 0, 0.56)
            for center_x in (0.36, 0.64):
                context.arc(width * center_x, height * 0.48, width * 0.14, 0, math.tau)
                context.fill()
                context.rectangle(
                    width * (center_x - 0.13),
                    height * 0.56,
                    width * 0.26,
                    height * 0.27,
                )
                context.fill()
        elif variant == 3:
            context.set_source_rgba(*accent, 0.72)
            context.arc(width * 0.55, height * 0.4, width * 0.27, 0, math.tau)
            context.fill()
            context.set_source_rgba(1, 0.78, 0.25, 0.72)
            for index in range(12):
                angle = math.tau * index / 12
                context.move_to(
                    width * 0.55 + math.cos(angle) * width * 0.31,
                    height * 0.4 + math.sin(angle) * width * 0.31,
                )
                context.line_to(
                    width * 0.55 + math.cos(angle) * width * 0.44,
                    height * 0.4 + math.sin(angle) * width * 0.44,
                )
            context.stroke()
        elif variant == 4:
            context.set_source_rgba(1, 1, 1, 0.78)
            context.rectangle(width * 0.08, height * 0.1, width * 0.38, height * 0.6)
            context.fill()
            context.set_source_rgba(0, 0, 0, 0.7)
            context.rectangle(width * 0.14, height * 0.18, width * 0.2, height * 0.22)
            context.fill()
            context.set_source_rgba(*accent, 0.86)
            context.rectangle(width * 0.5, height * 0.28, width * 0.42, height * 0.25)
            context.fill()
        elif variant == 5:
            context.set_source_rgba(*accent, 0.74)
            for index in range(5):
                angle = -math.pi / 2 + index * math.tau / 5
                next_angle = angle + math.tau * 2 / 5
                context.move_to(
                    width * 0.5 + math.cos(angle) * width * 0.33,
                    height * 0.42 + math.sin(angle) * width * 0.33,
                )
                context.line_to(
                    width * 0.5 + math.cos(next_angle) * width * 0.33,
                    height * 0.42 + math.sin(next_angle) * width * 0.33,
                )
            context.stroke()
            context.set_source_rgba(0, 0, 0, 0.55)
            context.arc(width * 0.5, height * 0.43, width * 0.16, 0, math.tau)
            context.fill()
        else:
            context.set_source_rgba(*accent, 0.72)
            context.arc(width * 0.62, height * 0.29, width * 0.25, 0, math.tau)
            context.fill()
            context.set_source_rgba(1, 1, 1, 0.38)
            context.move_to(width * 0.08, height * 0.67)
            context.curve_to(
                width * 0.32,
                height * 0.48,
                width * 0.6,
                height * 0.8,
                width * 0.94,
                height * 0.56,
            )
            context.line_to(width * 0.94, height * 0.78)
            context.line_to(width * 0.08, height * 0.78)
            context.close_path()
            context.fill()


class PosterWidget(Gtk.Widget):
    """Display cached TMDB artwork, falling back to the local poster renderer."""

    def __init__(
        self,
        record: TitleRecord,
        width: int,
        height: int,
        *,
        variant_offset: int = 0,
        show_text: bool = True,
        flexible_width: bool = False,
    ) -> None:
        super().__init__()
        self.fixed_width = width
        self.fixed_height = height
        self.flexible_width = flexible_width
        if flexible_width:
            self.set_size_request(-1, height)
        else:
            self.set_size_request(width, height)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.add_css_class("rounded-media")
        self.set_tooltip_text(f"{record.title}, {record.year}")
        self.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Artwork for {record.title}"],
        )

        artwork_path = Path(record.artwork_file) if record.artwork_file else None
        if artwork_path is not None and artwork_path.is_file():
            picture = Gtk.Picture.new_for_filename(str(artwork_path))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_can_shrink(True)
            picture.set_hexpand(True)
            picture.set_vexpand(True)
            self._media_child: Gtk.Widget = picture
        else:
            pending = Gtk.Box()
            pending.set_hexpand(True)
            pending.set_vexpand(True)
            pending.add_css_class("content-skeleton-surface")
            pending.set_tooltip_text(
                _("Loading artwork for {title}").format(title=record.title)
            )
            self._media_child = pending
        self._media_child.set_parent(self)

    def do_measure(
        self,
        orientation: Gtk.Orientation,
        _for_size: int,
    ) -> tuple[int, int, int, int]:
        """Keep cached images from imposing their intrinsic size on card layouts."""
        if orientation == Gtk.Orientation.HORIZONTAL:
            if self.flexible_width:
                # The parent grid assigns this width.  A natural artwork width
                # would otherwise be propagated through GtkGrid and make the
                # outer window request room for a card span.
                return 0, 0, -1, -1
            return self.fixed_width, self.fixed_width, -1, -1
        return self.fixed_height, self.fixed_height, -1, -1

    def do_size_allocate(
        self,
        width: int,
        height: int,
        baseline: int,
    ) -> None:
        self._media_child.allocate(width, height, baseline, None)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        self.snapshot_child(self._media_child, snapshot)

    def do_dispose(self) -> None:
        if self._media_child is not None:
            self._media_child.unparent()
            self._media_child = None
        super().do_dispose()


class MediaViewer(Gtk.Overlay):
    """A Tuba-inspired, in-window viewer for a collection of local images."""

    def __init__(self, window: Adw.ApplicationWindow) -> None:
        super().__init__()
        self.window = window
        self.items: tuple[tuple[str, str], ...] = ()
        self.position = 0
        self.zoom_level = 1.0
        self.texture: Gdk.Texture | None = None
        self._fullscreen_from_viewer = False

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_focusable(True)
        self.set_visible(False)
        self.set_can_target(False)
        self.add_css_class("media-viewer")

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        header.add_css_class("media-viewer-header")

        close_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        close_button.set_tooltip_text(_("Back to Gisheh"))
        close_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Back to Gisheh")])
        close_button.connect("clicked", lambda *_args: self.close())
        header.pack_start(close_button)

        self.window_title = Adw.WindowTitle(
            title=_("Media Viewer"),
            subtitle="",
        )
        header.set_title_widget(self.window_title)

        copy_button = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_button.set_tooltip_text(_("Copy image"))
        copy_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Copy image")])
        copy_button.connect("clicked", self._copy_image)
        header.pack_end(copy_button)

        self.fullscreen_button = Gtk.Button.new_from_icon_name(
            "view-fullscreen-symbolic"
        )
        self.fullscreen_button.set_tooltip_text(_("Toggle fullscreen"))
        self.fullscreen_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Toggle fullscreen")])
        self.fullscreen_button.connect("clicked", self._toggle_fullscreen)
        header.pack_end(self.fullscreen_button)
        toolbar.add_top_bar(header)

        stage = Gtk.Overlay()
        stage.set_hexpand(True)
        stage.set_vexpand(True)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)
        self.scroller.add_css_class("media-viewer-stage")

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_halign(Gtk.Align.CENTER)
        self.picture.set_valign(Gtk.Align.CENTER)
        self.picture.add_css_class("media-viewer-picture")
        self.scroller.set_child(self.picture)
        stage.set_child(self.scroller)

        page_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        page_controls.set_halign(Gtk.Align.START)
        page_controls.set_valign(Gtk.Align.END)
        page_controls.set_margin_start(18)
        page_controls.set_margin_bottom(18)
        page_controls.add_css_class("media-viewer-osd-box")
        self.previous_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.previous_button.set_tooltip_text(_("Previous image (Left)"))
        self.previous_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Previous image (Left)")])
        self.previous_button.add_css_class("flat")
        self.previous_button.connect("clicked", lambda *_args: self.previous())
        page_controls.append(self.previous_button)
        self.page_label = Gtk.Label(label="1 / 1")
        self.page_label.add_css_class("numeric")
        self.page_label.add_css_class("caption")
        page_controls.append(self.page_label)
        self.next_button = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_button.set_tooltip_text(_("Next image (Right)"))
        self.next_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Next image (Right)")])
        self.next_button.add_css_class("flat")
        self.next_button.connect("clicked", lambda *_args: self.next())
        page_controls.append(self.next_button)
        stage.add_overlay(page_controls)

        zoom_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        zoom_controls.set_halign(Gtk.Align.END)
        zoom_controls.set_valign(Gtk.Align.END)
        zoom_controls.set_margin_end(18)
        zoom_controls.set_margin_bottom(18)
        zoom_controls.add_css_class("media-viewer-osd-box")
        zoom_out = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        zoom_out.set_tooltip_text(_("Zoom out (Ctrl+-)"))
        zoom_out.update_property([Gtk.AccessibleProperty.LABEL], [_("Zoom out (Ctrl+-)")])
        zoom_out.add_css_class("flat")
        zoom_out.connect("clicked", lambda *_args: self.zoom_out())
        zoom_controls.append(zoom_out)
        self.zoom_label = Gtk.Label(label=_("Fit"))
        self.zoom_label.set_width_chars(6)
        self.zoom_label.add_css_class("numeric")
        self.zoom_label.add_css_class("caption")
        zoom_controls.append(self.zoom_label)
        zoom_in = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        zoom_in.set_tooltip_text(_("Zoom in (Ctrl++)"))
        zoom_in.update_property([Gtk.AccessibleProperty.LABEL], [_("Zoom in (Ctrl++)")])
        zoom_in.add_css_class("flat")
        zoom_in.connect("clicked", lambda *_args: self.zoom_in())
        zoom_controls.append(zoom_in)
        stage.add_overlay(zoom_controls)

        toolbar.set_content(stage)
        self.set_child(toolbar)

        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        double_click = Gtk.GestureClick()
        double_click.set_button(Gdk.BUTTON_PRIMARY)
        double_click.connect("pressed", self._on_picture_pressed)
        self.picture.add_controller(double_click)

        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.DISCRETE
        )
        scroll.connect("scroll", self._on_scroll)
        self.picture.add_controller(scroll)

    def open(
        self,
        items: tuple[tuple[str, str], ...],
        position: int = 0,
    ) -> None:
        valid_items = tuple(
            (path, label) for path, label in items if path and Path(path).is_file()
        )
        if not valid_items:
            return
        self.items = valid_items
        self.position = max(0, min(position, len(valid_items) - 1))
        self.set_visible(True)
        self.set_can_target(True)
        self._show_current()
        GLib.idle_add(self._focus_viewer)

    def _focus_viewer(self) -> bool:
        self.grab_focus()
        return GLib.SOURCE_REMOVE

    def close(self) -> None:
        if not self.get_visible():
            return
        if self._fullscreen_from_viewer and self.window.is_fullscreen():
            self.window.unfullscreen()
        self._fullscreen_from_viewer = False
        self.fullscreen_button.set_icon_name("view-fullscreen-symbolic")
        self.picture.set_paintable(None)
        self.texture = None
        self.items = ()
        self.set_can_target(False)
        self.set_visible(False)

    def _show_current(self) -> None:
        if not self.items:
            return
        path, label = self.items[self.position]
        try:
            self.texture = Gdk.Texture.new_from_filename(path)
        except GLib.Error:
            self.texture = None
        self.picture.set_paintable(self.texture)
        self.picture.set_alternative_text(label)
        self.window_title.set_title(label)
        self.window_title.set_subtitle(
            f"Image {self.position + 1} of {len(self.items)}"
        )
        self.page_label.set_label(f"{self.position + 1} / {len(self.items)}")
        self.previous_button.set_sensitive(self.position > 0)
        self.next_button.set_sensitive(self.position < len(self.items) - 1)
        self.zoom_level = 1.0
        self._apply_zoom()

    def previous(self) -> None:
        if self.position <= 0:
            return
        self.position -= 1
        self._show_current()

    def next(self) -> None:
        if self.position >= len(self.items) - 1:
            return
        self.position += 1
        self._show_current()

    def zoom_in(self) -> None:
        self.zoom_level = min(4.0, self.zoom_level + 0.5)
        self._apply_zoom()

    def zoom_out(self) -> None:
        self.zoom_level = max(1.0, self.zoom_level - 0.5)
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        if self.texture is None or self.zoom_level <= 1.0:
            self.picture.set_size_request(-1, -1)
            self.picture.set_hexpand(True)
            self.picture.set_vexpand(True)
            self.zoom_label.set_label(_("Fit"))
            return
        self.picture.set_hexpand(False)
        self.picture.set_vexpand(False)
        self.picture.set_size_request(
            round(self.texture.get_width() * self.zoom_level),
            round(self.texture.get_height() * self.zoom_level),
        )
        self.zoom_label.set_label(f"{round(self.zoom_level * 100)}%")

    def _on_picture_pressed(
        self,
        _gesture: Gtk.GestureClick,
        press_count: int,
        _x: float,
        _y: float,
    ) -> None:
        if press_count != 2:
            return
        self.zoom_level = 1.0 if self.zoom_level > 1.0 else 2.0
        self._apply_zoom()

    def _on_scroll(
        self,
        controller: Gtk.EventControllerScroll,
        _dx: float,
        dy: float,
    ) -> bool:
        state = controller.get_current_event_state()
        if not state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if dy < 0:
            self.zoom_in()
        else:
            self.zoom_out()
        return True

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.previous()
            return True
        if keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.next()
            return True
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.zoom_in()
                return True
            if keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self.zoom_out()
                return True
        return False

    def _toggle_fullscreen(self, _button: Gtk.Button) -> None:
        if self.window.is_fullscreen():
            self.window.unfullscreen()
            self._fullscreen_from_viewer = False
            self.fullscreen_button.set_icon_name("view-fullscreen-symbolic")
        else:
            self.window.fullscreen()
            self._fullscreen_from_viewer = True
            self.fullscreen_button.set_icon_name("view-restore-symbolic")

    def _copy_image(self, _button: Gtk.Button) -> None:
        if self.texture is not None:
            self.window.get_clipboard().set_texture(self.texture)


class SidebarRow(Gtk.ListBoxRow):
    def __init__(
        self,
        key: str,
        label: str,
        icon_name: str,
    ) -> None:
        super().__init__()
        self.key = key

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_margin_top(6)
        content.set_margin_bottom(6)
        content.set_margin_start(8)
        content.set_margin_end(8)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        title = Gtk.Label(label=label, xalign=0)
        title.set_hexpand(True)

        content.append(icon)
        content.append(title)
        self.set_child(content)
        self.title_label = title

    def set_label(self, label: str) -> None:
        """Update the visible label (used for live language switches)."""
        self.title_label.set_label(label)


def build_calendar_row(
    event,
    record,
    library_record,
    poster,
    *,
    configure_label,
    effective_status,
    can_add,
    on_add,
):
    """Render a calendar entry using supplied data and action callbacks."""
    row = Gtk.Box(spacing=12)
    row.add_css_class("movie-row-content")
    row.append(poster)

    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    text.set_hexpand(True)

    top = Gtk.CenterBox()
    media_label = {
        "movies": _("Movie"),
        "shows": _("Show"),
        "anime": _("Anime"),
    }[event.media_type]
    schedule = media_label
    if event.local_datetime:
        schedule = f"{media_label} · {event.local_datetime.strftime('%H:%M')}"
    schedule_label = Gtk.Label(label=schedule, xalign=0)
    schedule_label.add_css_class("caption")
    schedule_label.add_css_class("dim-label")
    top.set_start_widget(schedule_label)
    score = record.rating if record is not None else event.title.rating
    if score is not None:
        rating = Gtk.Label(label=f"★ {score:.1f}")
        rating.add_css_class("caption")
        rating.add_css_class("numeric")
        top.set_end_widget(rating)
    text.append(top)

    title_label = Gtk.Label(label=event.title.title, xalign=0)
    configure_label(title_label, 22, lines=2)
    title_label.add_css_class("title-3")
    title_label.set_tooltip_text(event.title.title)
    text.append(title_label)

    episode_details: list[str] = []
    if event.episode is not None:
        if event.season is not None:
            episode_details.append(f"S{event.season:02d}E{event.episode_number:02d}")
        else:
            episode_details.append(f"E{event.episode_number:02d}")
        if event.episode_title:
            episode_details.append(event.episode_title)
    elif event.title.dvd_date:
        episode_details.append(_("Home release {date}").format(date=event.title.dvd_date))
    subtitle = Gtk.Label(label=" · ".join(episode_details), xalign=0)
    subtitle.set_ellipsize(Pango.EllipsizeMode.END)
    subtitle.set_lines(2)
    subtitle.set_wrap(True)
    subtitle.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    subtitle.add_css_class("dim-label")
    subtitle.add_css_class("body")
    if episode_details:
        text.append(subtitle)

    original_title = event.title.original_title
    if original_title and original_title.casefold() == event.title.title.casefold():
        original_title = None
    metadata_values = [
        value
        for value in (
            str(record.year) if record is not None else None,
            event.title.network,
            event.title.runtime,
            original_title,
        )
        if value
    ]
    if metadata_values:
        metadata = Gtk.Label(label="  ·  ".join(metadata_values), xalign=0)
        metadata.set_ellipsize(Pango.EllipsizeMode.END)
        metadata.add_css_class("caption")
        metadata.add_css_class("dim-label")
        text.append(metadata)

    badges = Adw.WrapBox(child_spacing=5, line_spacing=5)
    badge_values: list[str] = []
    if event.season == 1 and event.episode_number == 1:
        badge_values.append(_("Premiere"))
    if event.finale_label:
        badge_values.append(event.finale_label)
    if library_record is not None:
        badge_values.append(_(effective_status(library_record)))
    for value in badge_values:
        badge = Gtk.Label(label=value)
        badge.add_css_class("status-pill")
        badges.append(badge)
    if badge_values:
        text.append(badges)
    row.append(text)
    if library_record is None and can_add:
        add = Gtk.Button(
            icon_name="bookmark-new-symbolic", tooltip_text=_("Add to Watchlist")
        )
        add.set_valign(Gtk.Align.START)
        add.add_css_class("flat")
        add.add_css_class("circular")
        add.connect("clicked", lambda button: on_add(button, event))
        row.append(add)
    return row


def build_library_row(record, poster, copy, popover):
    """Render a title row without knowing the window or library owner."""
    row = Gtk.ListBoxRow()
    row.record = record

    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    content.add_css_class("movie-row-content")
    content.append(poster)
    content.append(copy)

    menu_button = Gtk.MenuButton()
    menu_button.set_icon_name("view-more-symbolic")
    menu_button.set_tooltip_text(
        _("More Options for {title}").format(title=record.title)
    )
    menu_button.set_valign(Gtk.Align.START)
    menu_button.add_css_class("flat")
    menu_button.add_css_class("circular")
    menu_button.set_popover(popover)
    content.append(menu_button)
    row.set_child(content)
    return row
