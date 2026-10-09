# Contributing

Build instructions are in [README.md](README.md), with a
[Persian guide](README.fa.md). Meson is the installation authority;
pyproject.toml configures analysis only.

## Validate a change

```sh
ruff check src tests
meson setup build --prefix="$PWD/_install"
meson compile -C build
meson test -C build --print-errorlogs
msgfmt --check --statistics -o /tmp/gisheh-fa.mo po/fa.po
```

Run pure tests with `python3 tests/run.py unit`. Run graphical tests with
`GSK_RENDERER=cairo GDK_BACKEND=x11 xvfb-run -a dbus-run-session -- python3 tests/run.py gtk`.
These entrypoints isolate XDG paths and use the in-memory settings backend.
Use the runner rather than bare unittest discovery: widget tests require GTK
initialization. Graphical tests fail if the display is unavailable; they are
not silently skipped.

Do not exercise a real Simkl account in automated tests. Mock the service
client or inject a fake into a controller. Do not ship fixtures in the installed
application. Test local persistence failures and stale async callbacks when
changing these paths. UI callbacks must run on the GTK main thread.

After adding modules, register installed sources in Meson and translatable
sources in po/POTFILES.in. Refresh catalogs using the Meson gettext targets.
Preserve existing translations and review new strings in both interfaces.

Keep structural refactors separate from behavior changes where possible.
Describe the user-visible trigger, final behavior and validation in reviews.
The working directory may already contain another contributor's edits; do not
reset or clean it as part of a task.

## Reports

Use the repository issue tracker. Include expected and actual behavior,
reproduction steps, version, desktop, language and installation method.
Do not include access tokens, entire state files or account snapshots.
