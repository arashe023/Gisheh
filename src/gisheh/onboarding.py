"""First-run welcome tour and data-ownership choice."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .services import simkl_client
from .state_store import LIBRARY_MODE_LOCAL, LIBRARY_MODE_SIMKL


RESOURCE_PREFIX = "/io/github/arashe023/Gisheh"
CSS_RESOURCE = f"{RESOURCE_PREFIX}/style.css"
CSS_FILE = Path(__file__).resolve().parent / "style.css"


class WelcomeTour(Adw.ApplicationWindow):
    """A compact GNOME-style first-run tour."""

    def __init__(
        self,
        application: Adw.Application,
        *,
        simkl_available: bool,
        on_complete: Callable[[str], None],
        initial_mode: str = LIBRARY_MODE_LOCAL,
    ) -> None:
        super().__init__(application=application, title="Welcome to Gisheh")
        self.set_default_size(720, 560)
        self.set_size_request(420, 460)
        self._on_complete = on_complete
        self._selected_mode = (
            initial_mode if simkl_available else LIBRARY_MODE_LOCAL
        )
        self._page_index = 0
        self._simkl_auth_generation = 0
        self._simkl_auth_active = False
        self._simkl_pin_dialog: Adw.AlertDialog | None = None
        self._ui_ready = False
        self.connect("close-request", self._on_close_request)

        provider = Gtk.CssProvider()
        try:
            provider.load_from_resource(CSS_RESOURCE)
        except GLib.Error:
            provider.load_from_path(str(CSS_FILE))
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_title_widget(Adw.WindowTitle(title="Gisheh", subtitle="Welcome"))
        toolbar.add_top_bar(header)

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.carousel = Adw.Carousel()
        self.carousel.set_hexpand(True)
        self.carousel.set_vexpand(True)
        self.carousel.set_allow_mouse_drag(True)
        self.carousel.connect("notify::position", self._on_position_changed)
        self.carousel.append(
            self._tour_page(
                "🎬",
                "Welcome to Gisheh",
                "Keep films, shows and anime in one calm, native library built "
                "for the GNOME desktop.",
                (
                    "Browse with TMDB metadata",
                    "Track titles, seasons and episodes",
                    "Use your GNOME accent colour automatically",
                ),
            )
        )
        self.carousel.append(
            self._tour_page(
                "🔒",
                "Your library stays yours",
                "Gisheh can work entirely on this device, or keep your watch "
                "activity synchronized through Simkl. You can change this later.",
                (
                    "Local-first never requires an account",
                    "Simkl uses a browser PIN—never your password",
                    "TMDB supplies catalog details and artwork",
                ),
            )
        )
        self.carousel.append(self._choice_page(simkl_available))
        layout.append(self.carousel)

        footer = Gtk.CenterBox()
        footer.add_css_class("welcome-footer")
        self.back_button = Gtk.Button(label="Back")
        self.back_button.set_visible(False)
        self.back_button.connect("clicked", self._go_back)
        footer.set_start_widget(self.back_button)

        indicator = Adw.CarouselIndicatorDots()
        indicator.set_carousel(self.carousel)
        footer.set_center_widget(indicator)

        self.next_button = Gtk.Button(label="Next")
        self.next_button.add_css_class("suggested-action")
        self.next_button.connect("clicked", self._go_forward)
        footer.set_end_widget(self.next_button)
        layout.append(footer)

        toolbar.set_content(layout)
        self.set_content(toolbar)
        self._ui_ready = True

    @staticmethod
    def _feature_row(text: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_halign(Gtk.Align.CENTER)
        icon = Gtk.Label(label="✅")
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        icon.set_xalign(0.5)
        icon.set_yalign(0.5)
        icon.add_css_class("welcome-feature-emoji")
        label = Gtk.Label(label=text, xalign=0)
        row.append(icon)
        row.append(label)
        return row

    def _tour_page(
        self,
        emoji: str,
        title: str,
        description: str,
        features: tuple[str, ...],
    ) -> Gtk.Widget:
        page = Gtk.ScrolledWindow()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page.set_propagate_natural_height(True)
        page.set_hexpand(True)
        page.set_vexpand(True)

        clamp = Adw.Clamp(maximum_size=580, tightening_threshold=420)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.add_css_class("welcome-page")
        content.set_valign(Gtk.Align.CENTER)

        icon_surface = Gtk.Box()
        icon_surface.set_halign(Gtk.Align.CENTER)
        icon_surface.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Label(label=emoji)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        icon.set_xalign(0.5)
        icon.set_yalign(0.5)
        icon.add_css_class("welcome-emoji")
        icon_surface.append(icon)
        content.append(icon_surface)

        heading = Gtk.Label(label=title)
        heading.add_css_class("welcome-title")
        heading.set_wrap(True)
        heading.set_justify(Gtk.Justification.CENTER)
        content.append(heading)

        body = Gtk.Label(label=description)
        body.add_css_class("welcome-body")
        body.set_wrap(True)
        body.set_justify(Gtk.Justification.CENTER)
        body.set_max_width_chars(58)
        content.append(body)

        feature_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        feature_list.set_margin_top(8)
        for feature in features:
            feature_list.append(self._feature_row(feature))
        content.append(feature_list)
        clamp.set_child(content)
        page.set_child(clamp)
        return page

    def _choice_button(
        self,
        title: str,
        subtitle: str,
        emoji: str,
        mode: str,
        leader: Gtk.ToggleButton | None = None,
    ) -> Gtk.ToggleButton:
        button = Gtk.ToggleButton()
        button.add_css_class("welcome-choice")
        if leader is not None:
            button.set_group(leader)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        icon = Gtk.Label(label=emoji)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        icon.set_xalign(0.5)
        icon.set_yalign(0.5)
        icon.add_css_class("welcome-choice-emoji")
        row.append(icon)

        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        copy.set_hexpand(True)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class("dim-label")
        subtitle_label.set_wrap(True)
        subtitle_label.set_max_width_chars(48)
        copy.append(title_label)
        copy.append(subtitle_label)
        row.append(copy)

        check = Gtk.Label(label="✓")
        check.add_css_class("welcome-choice-check")
        row.append(check)
        button.set_child(row)
        button.connect("toggled", self._on_mode_toggled, mode)
        return button

    def _choice_page(self, simkl_available: bool) -> Gtk.Widget:
        page = Gtk.ScrolledWindow()
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page.set_propagate_natural_height(True)
        page.set_hexpand(True)
        page.set_vexpand(True)
        clamp = Adw.Clamp(maximum_size=580, tightening_threshold=420)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.add_css_class("welcome-page")
        content.set_valign(Gtk.Align.CENTER)

        eyebrow = Gtk.Label(label="ONE CHOICE BEFORE YOU START")
        eyebrow.add_css_class("welcome-eyebrow")
        content.append(eyebrow)
        title = Gtk.Label(label="How should Gisheh manage your library?")
        title.add_css_class("welcome-choice-title")
        title.set_wrap(True)
        title.set_justify(Gtk.Justification.CENTER)
        content.append(title)
        description = Gtk.Label(
            label="Your selection controls where watch history, lists and ratings are saved."
        )
        description.add_css_class("welcome-body")
        description.set_wrap(True)
        description.set_justify(Gtk.Justification.CENTER)
        content.append(description)

        choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        choices.set_margin_top(8)
        self.local_button = self._choice_button(
            "Local-first",
            "Keep everything on this device. No account and no automatic upload.",
            "💾",
            LIBRARY_MODE_LOCAL,
        )
        self.local_button.set_active(self._selected_mode == LIBRARY_MODE_LOCAL)
        choices.append(self.local_button)

        self.simkl_button = self._choice_button(
            "Sync with Simkl",
            "Use a PIN to connect, then synchronize lists, ratings and watch history.",
            "☁️",
            LIBRARY_MODE_SIMKL,
            self.local_button,
        )
        self.simkl_button.set_sensitive(simkl_available)
        self.simkl_button.set_active(self._selected_mode == LIBRARY_MODE_SIMKL)
        choices.append(self.simkl_button)
        content.append(choices)

        if not simkl_available:
            unavailable = Gtk.Label(
                label="Simkl sync is unavailable in this build; Local-first will be used."
            )
            unavailable.add_css_class("dim-label")
            unavailable.add_css_class("caption")
            unavailable.set_wrap(True)
            unavailable.set_justify(Gtk.Justification.CENTER)
            content.append(unavailable)

        clamp.set_child(content)
        page.set_child(clamp)
        return page

    def _on_mode_toggled(self, button: Gtk.ToggleButton, mode: str) -> None:
        if button.get_active():
            self._selected_mode = mode
            self._update_next_button()
            if (
                self._ui_ready
                and self._page_index == 2
                and mode == LIBRARY_MODE_SIMKL
                and not self._simkl_auth_active
                and not simkl_client.read_token()
            ):
                GLib.idle_add(self._start_simkl_sign_in)

    def _on_position_changed(self, _carousel: Adw.Carousel, _parameter: object) -> None:
        self._page_index = min(2, max(0, round(self.carousel.get_position())))
        self.back_button.set_visible(self._page_index > 0)
        self._update_next_button()

    def _update_next_button(self) -> None:
        if not hasattr(self, "next_button"):
            return
        if self._simkl_auth_active:
            self.next_button.set_label("Waiting for Simkl…")
        elif self._page_index < 2:
            self.next_button.set_label("Next")
        elif self._selected_mode == LIBRARY_MODE_SIMKL:
            self.next_button.set_label("Continue to Simkl sign in")
        else:
            self.next_button.set_label("Start using Gisheh")

    def _go_back(self, _button: Gtk.Button) -> None:
        if self._page_index > 0:
            self.carousel.scroll_to(self.carousel.get_nth_page(self._page_index - 1), True)

    def _go_forward(self, _button: Gtk.Button) -> None:
        if self._page_index < 2:
            self.carousel.scroll_to(self.carousel.get_nth_page(self._page_index + 1), True)
            return
        if self._selected_mode == LIBRARY_MODE_SIMKL:
            if simkl_client.read_token():
                self._on_complete(LIBRARY_MODE_SIMKL)
            else:
                self._start_simkl_sign_in()
            return
        self._on_complete(self._selected_mode)

    def _set_auth_busy(self, busy: bool) -> None:
        self._simkl_auth_active = busy
        self.back_button.set_sensitive(not busy)
        self.next_button.set_sensitive(not busy)
        self.local_button.set_sensitive(not busy)
        self.simkl_button.set_sensitive(not busy)
        self.carousel.set_allow_mouse_drag(not busy)
        self._update_next_button()

    def _start_simkl_sign_in(self) -> None:
        if self._simkl_auth_active:
            return
        client_id = simkl_client.read_client_id()
        if not client_id:
            self._show_sign_in_error(
                "This build does not include Gisheh's public Simkl Client ID."
            )
            return
        self._simkl_auth_generation += 1
        generation = self._simkl_auth_generation
        self._set_auth_busy(True)
        threading.Thread(
            target=self._request_simkl_pin,
            args=(client_id, generation),
            name="gisheh-welcome-simkl-pin",
            daemon=True,
        ).start()

    def _request_simkl_pin(self, client_id: str, generation: int) -> None:
        try:
            payload = simkl_client.request_pin(client_id)
        except simkl_client.SimklError as error:
            GLib.idle_add(self._on_simkl_sign_in_failed, generation, str(error))
            return
        GLib.idle_add(self._present_simkl_pin, client_id, payload, generation)

    def _present_simkl_pin(
        self,
        client_id: str,
        payload: dict[str, Any],
        generation: int,
    ) -> bool:
        if generation != self._simkl_auth_generation or not self._simkl_auth_active:
            return GLib.SOURCE_REMOVE

        user_code = str(payload["user_code"])
        verification_uri = str(
            payload.get("verification_uri") or "https://simkl.com/pin"
        )
        interval = max(5, int(payload.get("interval") or 5))
        expires_in = max(60, int(payload.get("expires_in") or 900))
        dialog = Adw.AlertDialog(
            heading="Sign in to Simkl",
            body=(
                "The Simkl page has been opened in your browser. Sign in and "
                "enter this code; Gisheh will continue automatically."
            ),
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        code = Gtk.Label(label=user_code)
        code.set_selectable(True)
        code.add_css_class("simkl-pin-code")
        content.append(code)
        waiting = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        waiting.set_halign(Gtk.Align.CENTER)
        waiting.append(Gtk.Spinner(spinning=True))
        waiting.append(Gtk.Label(label="Waiting for approval…"))
        content.append(waiting)
        dialog.set_extra_child(content)
        dialog.add_response("cancel", "Cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_simkl_pin_response, generation)
        self._simkl_pin_dialog = dialog
        dialog.present(self)

        try:
            Gio.AppInfo.launch_default_for_uri(verification_uri, None)
        except GLib.Error:
            pass

        threading.Thread(
            target=self._poll_simkl_pin,
            args=(client_id, user_code, interval, expires_in, generation),
            name="gisheh-welcome-simkl-poll",
            daemon=True,
        ).start()
        return GLib.SOURCE_REMOVE

    def _poll_simkl_pin(
        self,
        client_id: str,
        user_code: str,
        interval: int,
        expires_in: int,
        generation: int,
    ) -> None:
        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline:
            time.sleep(interval)
            if (
                generation != self._simkl_auth_generation
                or not self._simkl_auth_active
            ):
                return
            try:
                payload = simkl_client.poll_pin(client_id, user_code)
            except simkl_client.SimklError as error:
                GLib.idle_add(
                    self._on_simkl_sign_in_failed, generation, str(error)
                )
                return
            access_token = str(payload.get("access_token") or "")
            if payload.get("result") == "OK" and access_token:
                GLib.idle_add(
                    self._on_simkl_authorized, generation, access_token
                )
                return
            if payload.get("device_code"):
                GLib.idle_add(
                    self._on_simkl_sign_in_failed,
                    generation,
                    "The Simkl PIN expired. Request a new code.",
                )
                return
        GLib.idle_add(
            self._on_simkl_sign_in_failed,
            generation,
            "The Simkl PIN expired. Request a new code.",
        )

    def _on_simkl_pin_response(
        self,
        dialog: Adw.AlertDialog,
        _response: str,
        generation: int,
    ) -> None:
        if self._simkl_pin_dialog is dialog:
            self._simkl_pin_dialog = None
        if generation != self._simkl_auth_generation:
            return
        self._simkl_auth_generation += 1
        self._set_auth_busy(False)

    def _on_simkl_authorized(self, generation: int, access_token: str) -> bool:
        if generation != self._simkl_auth_generation or not self._simkl_auth_active:
            return GLib.SOURCE_REMOVE
        try:
            simkl_client.clear_account_cache()
            simkl_client.store_token(access_token)
        except simkl_client.SimklError as error:
            return self._on_simkl_sign_in_failed(generation, str(error))

        self._simkl_auth_generation += 1
        self._simkl_auth_active = False
        dialog = self._simkl_pin_dialog
        self._simkl_pin_dialog = None
        if dialog is not None:
            dialog.close()
        self._on_complete(LIBRARY_MODE_SIMKL)
        return GLib.SOURCE_REMOVE

    def _on_simkl_sign_in_failed(self, generation: int, message: str) -> bool:
        if generation != self._simkl_auth_generation:
            return GLib.SOURCE_REMOVE
        self._simkl_auth_generation += 1
        dialog = self._simkl_pin_dialog
        self._simkl_pin_dialog = None
        if dialog is not None:
            dialog.close()
        self._set_auth_busy(False)
        self._show_sign_in_error(message)
        return GLib.SOURCE_REMOVE

    def _show_sign_in_error(self, message: str) -> None:
        dialog = Adw.AlertDialog(
            heading="Could not sign in to Simkl",
            body=message,
        )
        dialog.add_response("close", "Close")
        dialog.set_close_response("close")
        dialog.present(self)

    def _on_close_request(self, _window: Adw.ApplicationWindow) -> bool:
        self._simkl_auth_generation += 1
        self._simkl_auth_active = False
        return False
