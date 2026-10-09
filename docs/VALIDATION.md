# Implementation validation and release gates

## 1.5.0-rc1 preparation — 2026-10-09

The current candidate adds the native Profile redesign, system-driven RTL
navigation, independent TMDB language selection, release metadata and bilingual
README. Native validation uses `/tmp/gisheh-release-build` and
`/tmp/gisheh-release-install`. The latest suite contains 86 unit tests and
338 GTK tests (424 distinct tests), plus desktop/AppStream validation.
Ruff, translation validation and whitespace checks pass. A live read-only TMDB
configuration request returned HTTP 200; no Simkl account writes were performed.
The installed application includes scalable/symbolic icons and the MIT license.

The earlier implementation record below is historical; its test counts and
missing-tool observations describe that earlier run. Flatpak candidate results
are recorded separately after packaging. The SDK download was interrupted by
repeated timeouts and an HTTP 403 from the upstream object server. A standalone
candidate can be assembled with the documented native-pure-python fallback;
that does not count as a successful Flatpak Builder/SDK build.

## Earlier implementation record


Validation date: 2026-10-09. These results describe the current working tree,
including the pre-existing contributor changes. They do not certify a published
commit, a Flatpak artifact or Flathub acceptance. No commit or release was made.

## Verified native environment

- Python 3.14.7; GTK 4.22.5; libadwaita 1.9.4; libsecret 0.21.8.2.
- Meson build: `/tmp/gisheh-implementation-build`.
- Temporary installed prefix: `/tmp/gisheh-implementation-install`.
- Graphical tests: Xvfb/X11, private D-Bus session, Cairo renderer.
- Tests use temporary XDG directories, memory GSettings and isolated state.
  Automated service tests use controlled responses, not a real account.

| Check | Result and boundary |
| --- | --- |
| Ruff | Passed for `src`, `tests` and `build-aux` |
| Whitespace | `git diff --check` passed |
| Independent Python tests | 82 passed |
| GTK Python tests | 320 passed; no crash |
| GTK repeatability | Three additional sequential runs passed |
| Meson test suites | All four passed: unit, GTK, desktop and AppStream |
| Native build/install | Passed into a temporary prefix |
| Installed startup | First-run window, local mode, main window, resources and state passed outside the checkout |
| Incremental resources | Changing only a Welcome SVG mtime rebuilt GResource; original source mtime restored |
| Translation catalog | `msgfmt --check` passed; 523 translated messages |
| UI dimensions | Installed local-library smoke captures in English and Persian, requested widths 360, 720, 1100 and 1366, light and dark themes |
| High contrast | Explicitly activated and checked with the installed app; not inferred from a dark theme |
| Keyboard | Basic forward focus acquisition checked; full keyboard and screen-reader audit remains manual |
| GitHub Actions | Workflow added; remote execution has not been observed |

The 402 Python tests are the sum of the unit and GTK suites, not an additional
suite. Repeated runs do not add new distinct tests. Test names and assertions
are the authoritative statement of coverage; this table does not claim every
possible failure or every screen has been tested.

The initial widget crash occurred when GTK/libadwaita had not been initialized
in the test process. Explicit initialization and isolated graphical execution
resolved the reproduced crash. Parallel Xvfb repeats also exposed a display
startup race; graphical Meson tests now run sequentially. The final three-run
repeat passed. Missing a graphical display is an error in the required suite.

A narrow-window minimum-width constraint was reproduced and corrected by
adjusting when the media switcher changes layout. Window borders account for
the difference between requested and content widths. The installed smoke test
checks the actual allocation, rather than merely requesting a window size.
These checks cover the local library window, not every preferences/detail flow.

## Data and lifecycle checks

Automated cases cover absent/corrupt/unreadable/future state, schema migration,
unknown-field preservation, private file modes, failed writes, backup/recovery,
round-trip local export/import, invalid imports, preservation of cloud settings,
worker shutdown and stale delivery, and local versus remotely committed save
failures. Review `test_state_store.py`, `test_library_backup.py`,
`test_transactions.py`, `test_jobs.py`, `test_data_actions.py` and
`test_recovery.py` for exact cases.

Import/export uses Gtk.FileDialog and asynchronous Gio operations. A native
Gio private-write path has been tested. This does **not** establish that a file
portal works inside the final Flatpak sandbox. Local import has no service
client and performs no Simkl write.

## Screenshot provenance

`data/screenshots/local-library.png` is an actual rendering of the installed
Linux application using six repository fixture records in an isolated profile.
No personal account or personal viewing library was used. Network credentials
were disabled in the smoke process; artwork placeholders are intentional.
The screenshot is not installed as a runtime asset. The AppStream screenshot
URL must be checked after this file is published to the upstream repository.

## Reproducing the checks

```sh
ruff check src tests build-aux
meson setup build --prefix=/tmp/gisheh-install
meson compile -C build
meson test -C build --print-errorlogs
meson test -C build gtk-tests --repeat=3 --print-errorlogs
msgfmt --check --statistics -o /tmp/gisheh-fa.mo po/fa.po
meson install -C build
GSK_RENDERER=cairo GDK_BACKEND=x11 xvfb-run -a dbus-run-session -- \
  python3 tests/installed_smoke.py /tmp/gisheh-install
LANG=en_US.UTF-8 LANGUAGE=fa ADW_DEBUG_HIGH_CONTRAST=1 GISHEH_SMOKE_MATRIX=1 \
  GSK_RENDERER=cairo GDK_BACKEND=x11 xvfb-run -a -s '-screen 0 1920x1080x24' dbus-run-session -- \
  python3 tests/installed_smoke.py /tmp/gisheh-install /tmp/gisheh-ui-captures
```

Use an empty temporary install prefix and a locale installed on the host (`locale -a`).
`LANGUAGE=fa` selects the Persian catalog without requiring a Persian system locale. The smoke helper isolates its own state
and disables credentials. Raw Meson logs can contain inherited environment
variables: do not publish them unreviewed. The CI result collector emits
selected test fields and omits the inherited environment and command line.

## Outstanding release gates

The following are unverified or require the human maintainer; they are not
reported as passing:

- Build and lint the actual Flatpak artifact. Flatpak Builder and the required
  SDK are unavailable in this environment; a native install is not a substitute.
- Validate clean sandbox installation, upgrade preserving the library, offline
  existing data, file selection portals and Secret Service/keyring.
- Build and test both x86_64 and aarch64 packages and verify dependency licenses,
  source checksums, offline build and runtime support at submission time.
- Test real Wayland and the user's actual desktop/session. Xvfb proves neither.
- Manually exercise recovery confirmations, import cancellation/replacement,
  preferences and details at all target widths in both languages/themes.
- Audit every icon-only action's accessible name, visible focus, full keyboard
  navigation and a screen reader. Basic focus acquisition is not that audit.
- Verify live TMDB connectivity and optional Simkl authentication with an
  explicitly approved test account. Do not write to a personal account as a test.
- Obtain human English/Persian text review and publish/validate screenshot URLs.
- Run the new CI workflow remotely and review its artifacts.
- Choose the actual release version/date, freeze a reviewed commit, and build
  the release from that exact source. Existing VERSION/RELEASE_DATE were retained.
- Human-author the Flathub submission manifest and submission interactions,
  disclose AI-assisted upstream work, and follow `RELEASING.md`.

Refactoring is incremental: extracted models, storage, service orchestration
and widgets have dedicated modules, while `window.py` still contains substantial
view construction and view-specific asynchronous assembly. Continued extraction
can proceed behind these boundaries; line count is not a release criterion.
