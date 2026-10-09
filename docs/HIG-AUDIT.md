# GNOME HIG audit — 2026-10-09

This review covers the current working tree, including existing contributor
changes. It is not a certification of complete HIG compliance or a review of
every backend path. No release, commit, personal account mutation, or replacement
of the user's installed application was performed.

## Findings corrected

| Problem and trigger | Result |
| --- | --- |
| Closing the main window while title details were open only dismissed the details. | Closing now saves state and shuts down background jobs. A failed save still keeps the window open. Escape and Back remain navigation actions. |
| The window intercepted Escape during capture, before search fields and other focused controls. | Window navigation now runs during bubbling and ignores Escape when a dialog is visible. |
| Search only exposed Ctrl+K and there was no shortcut reference. | Ctrl+F searches the current collection or opens Explore search. Ctrl+K retains direct Explore search. Added F10 for Main Menu, Alt+Left for Back, Ctrl+W for closing the active dialog/window, and Ctrl+? for a native `Adw.ShortcutsDialog`. |
| The primary menu included Quit and did not group standard actions. | Removed the Quit menu entry; Ctrl+Q remains. Preferences, Keyboard Shortcuts and About Gisheh form the final section. All menu entries have translatable mnemonics. |
| Application Log used an alert with a fixed 700px minimum content width. | It now uses an adaptive `Adw.Dialog`, header bar, selectable wrapping text, native close control, initial text focus, and an internal toast overlay. |
| Settings confirmations were presented against the underlying main window. | Cache and TMDB credential confirmations are attached to Preferences. |
| Preference feedback was sent to the obscured main-window toast overlay. | Feedback is displayed inside visible Preferences. Ordinary toasts remain visible for five seconds. |
| The token dialog allowed an empty Save and Connect action, then dismissed the form before reporting the missing value. | Connect is disabled until non-whitespace input exists; the token entry receives initial focus and an accessible name. |
| Icon controls and search/filter fields relied on implicit accessible metadata. | Added explicit translated labels to GtkBuilder controls, calendar navigation and media-viewer controls. GTK tests now use the accessibility test backend rather than disabling accessibility. |
| Account subtitles/buttons and several calendar messages bypassed gettext. | These messages, calendar row labels and poster descriptions now enter the translation catalog. Persian translations were added. Interface language continues to follow the system; TMDB content language stays independent. |

## Guidance used

- [Primary menus](https://developer.gnome.org/hig/patterns/controls/menus.html): standard items, grouping, mnemonics and excluding Quit.
- [Standard keyboard shortcuts](https://developer.gnome.org/hig/reference/keyboard.html): search, navigation, preferences and window actions.
- [Dialogs](https://developer.gnome.org/hig/patterns/feedback/dialogs.html): parent surfaces, initial focus and input-dependent actions.
- [Scaling and adaptiveness](https://developer.gnome.org/hig/guidelines/adaptive.html): constrained window sizes and bounded content.
- [Accessibility](https://developer.gnome.org/hig/guidelines/accessibility.html) and [UI styling](https://developer.gnome.org/hig/guidelines/ui-styling.html): accessible names, large text, high contrast and native widgets.
- [GTK accessibility](https://docs.gtk.org/gtk4/section-accessibility.html): explicit accessible properties and the test backend.

## Verification

- Ruff and `git diff --check`: passed.
- Python unit tests: 86 passed.
- GTK tests: 331 passed, including 11 new HIG regression cases.
- All four Meson suites passed: unit, GTK, desktop entry and AppStream.
- Native build and install passed in `/tmp/gisheh-hig-build` and
  `/tmp/gisheh-hig-install`; the test build contains no service credentials.
- `msgfmt --check`: passed; 585 Persian messages translated.
- Inspected actual installed-app captures of the library, Preferences,
  Application Log, Keyboard Shortcuts and Main Menu in English and Persian at
  **360×640 content pixels**. X11 client decoration borders are separate.
- Repeated the same five surfaces with Persian RTL, large text (`Sans 16`) and
  high contrast at **1024×640 content pixels**. Dialog widths and initial focus
  for Preferences and Log are asserted by the smoke helper.
- Rendering used Xvfb/X11, Cairo and isolated temporary profiles, with service
  reads disabled. No personal state or live Simkl account was used.

## Reproduce

```sh
meson setup /tmp/gisheh-hig-build --prefix=/tmp/gisheh-hig-install \
  -Dtmdb_read_token= -Dsimkl_client_id=
meson compile -C /tmp/gisheh-hig-build
meson install -C /tmp/gisheh-hig-build
meson test -C /tmp/gisheh-hig-build --print-errorlogs

LANG=en_US.UTF-8 LANGUAGE=fa GSK_RENDERER=cairo GDK_BACKEND=x11 \
  xvfb-run -a -s '-screen 0 1440x1200x24' dbus-run-session -- \
  python tests/hig_smoke.py /tmp/gisheh-hig-install /tmp/gisheh-hig-captures/fa

LANG=en_US.UTF-8 LANGUAGE=fa HIG_WIDTH=1024 HIG_LARGE_TEXT=1 \
  ADW_DEBUG_HIGH_CONTRAST=1 GSK_RENDERER=cairo GDK_BACKEND=x11 \
  xvfb-run -a -s '-screen 0 1440x1200x24' dbus-run-session -- \
  python tests/hig_smoke.py /tmp/gisheh-hig-install \
  /tmp/gisheh-hig-captures/fa-large-contrast
```

Use an installed non-C UTF-8 locale when checking `LANGUAGE=fa`; native gettext
does not handle the C locale like Python gettext. Run graphical captures
sequentially. Raw Meson logs can include inherited environment values and should
not be published unreviewed.

## Remaining boundaries and observations

- A full Orca/screen-reader workflow, on-screen keyboard and real Wayland session
  were not exercised. Accessible-property tests are not a substitute for them.
- Live TMDB and Simkl account interactions, Flatpak portals, keyring behavior
  and final Flatpak installation remain outside this offline UI pass.
- The large-text run emitted a GTK measurement warning (minimum height 107,
  natural height 106) while presenting Preferences. The captures showed no
  corresponding clipping. Its cause has not been established and it should be
  rechecked on the target GTK/libadwaita runtime rather than reported as fixed.
- Translation work here addresses the reviewed surfaces, not a claim that every
  dynamic string in the application has been audited. Identified calendar
  summaries, external-video messages and watch-date messages were also moved
  into gettext, including plural-aware release counts.
- The review preserves existing custom navigation and media presentation.
  It does not claim exhaustive visual conformance for every details, season,
  episode, recovery and first-run state.
