# README artwork

These assets belong to Gisheh's repository presentation. They are not installed
with the application or included in its GResource bundle.

## Design and research

The README follows a desktop-application structure: identity, a short description,
a real screenshot, features, installation, first launch, development and credits.
Build details and the narrow-layout gallery use GitHub's native `details` element.
All images use repository-relative paths; `picture` selects the appropriate
light/dark cover and screenshot. Text alternatives describe each informative image.

References inspected on 2026-11-06:

- [Best-README-Template](https://github.com/othneildrew/Best-README-Template):
  section structure and paths for users and contributors.
- [Gradia](https://github.com/AlexanderVanhee/Gradia/blob/main/README.md):
  product identity, installation and application screenshots.
- [Planify](https://github.com/alainm23/planify/blob/main/README.md):
  a desktop screenshot and expandable build requirements.
- [Make a README](https://www.makeareadme.com/): description, installation,
  usage, contribution and project status.
- [GitHub README documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes):
  repository-relative image paths and links.

The copy and artwork are specific to Gisheh. No screenshots, logos or artwork
were copied from the reference projects. No store, download-count or passing-CI
badges are displayed without an actual corresponding release or result.

## Covers

`cover-{en,fa}-{light,dark}.{svg,png}` are 1600 × 600 covers. Their palette and
ticket shape come from the application's existing purple saved-ticket icon.
The Persian cover mirrors the composition and uses shaped Persian typography.

The source generator is `build-aux/render-readme-assets.py`. It reads the
unchanged application icon and outlines Noto Sans and Vazirmatn text using
PangoCairo, so the SVG exports do not depend on fonts installed on a reader's
device. No font files are bundled. No stock artwork or remote image service
is required to display the covers.

To regenerate from the repository root, install Noto Sans, Vazirmatn and
`rsvg-convert` in addition to the project's PyGObject/Cairo dependencies, then run:

```sh
python3 build-aux/render-readme-assets.py
```

## Screenshots

`library-{en,fa}-{light,dark}.png` are unchanged PNG captures of the installed
application, taken by `tests/installed_smoke.py` with isolated temporary state
and the repository's sample library. They correspond to the 1100-pixel requested
window width; the actual content is 1090 × 690. `narrow-{en,fa}.png` are the
360-pixel requested width, light appearance, 350 × 690 content captures.

English is left-to-right and Persian is right-to-left. Captures contain no
personal account data. The sample library was offline, so poster placeholders
are intentional and disclosed below the README screenshot. The captures were
not repainted or represented as screens with downloaded posters.

Recreate the source captures after installing the application into a temporary
prefix (replace `/tmp/gisheh-install` with that prefix):

```sh
for language in en fa; do
  LANG=C.UTF-8 LANGUAGE="$language" GISHEH_SMOKE_MATRIX=1 \
    GSK_RENDERER=cairo GDK_BACKEND=x11 \
    xvfb-run -a -s '-screen 0 1920x1080x24' dbus-run-session -- \
    python3 tests/installed_smoke.py /tmp/gisheh-install "/tmp/gisheh-shots-$language"
done
```

Use the `1100-force-light.png`, `1100-force-dark.png` and `360-force-light.png`
files from each language's output directory. Keep these raw application captures
separate from the illustrated covers.

## Social preview

`social-preview.png` is an opaque 1280 × 640 PNG, under 1 MB, following
[GitHub's image recommendations](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).
Its vector source is `social-preview.svg`.

Adding an image to a README does not set the repository's link-preview image.
The owner can upload this file under **Settings → General → Social preview →
Edit → Upload an image**. This task prepares the file locally; the GitHub setting
has not been changed.
