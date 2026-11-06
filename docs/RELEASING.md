# Packaging and release

The current version is **1.5.0-rc1**. It is a test release candidate, not a
Flathub-approved release. Publishing is separate from preparing a local commit
and building an artifact. Do not reuse an existing release tag for changed code.

## Automated release checks

Check the release metadata before packaging:

```sh
python3 build-aux/check-release.py
python3 build-aux/check-release.py --tag v1.5.0-rc1
python3 build-aux/check-release.py --public-urls
```

The gate checks the canonical version/date, changelog heading, AppStream release
type, application ID and launcher. The packaging script runs the metadata gate
before starting a build. A stable version requires AppStream `type="stable"`.
The optional online gate checks every AppStream link and screenshot without
authentication. It must pass before public distribution; private GitHub
repositories and their raw screenshot URLs return 404 to prospective users.

After building, verify integrity and run the installed sandbox test:

```sh
python3 build-aux/check-release.py --artifacts dist
python3 build-aux/smoke-flatpak.py dist/Gisheh-1.5.0-rc1-x86_64.flatpak
```

Artifact verification compares SHA256SUMS with build-info.json, hashes both
files, checks the revision/runtime/architecture, and compares every source
archive file, executable mode and symlink with a fresh archive of HEAD. This
proves source archive provenance, not that the bundle was compiled from it;
the build job and installed smoke test provide separate evidence. Uncommitted
working-tree changes are not included in that HEAD archive.

The smoke helper requires Xvfb, xauth, D-Bus and the manifest's runtime installed
**system-wide**. It uses a disposable user installation, disables application
network access, mounts only the test directory read-only, and checks first
launch, local persistence, resources, installed metadata/icons/license, English
and Persian translation and text direction. It never installs into the user's
normal Flatpak directory. This automated test does not exercise file portals,
real Wayland, upgrades or a real Simkl login.

`.github/workflows/ci.yml` runs native validation and both language/layout
matrices. `.github/workflows/flatpak.yml` builds with the GNOME SDK on native
x86_64 and aarch64 runners, verifies archives and smoke-tests each bundle. Run
it with **Actions → Standalone Flatpak candidate → Run workflow**, or push a
matching `v<VERSION>` tag after reviewing the source. It retains tested bundles
as Actions artifacts and does not create a public GitHub Release. Its first
remote run must pass before treating SDK/ARM packaging as verified.

## Build a standalone Flatpak

Install Flatpak, Flatpak Builder and the GNOME 50 SDK. The builder can be the
native `flatpak-builder` executable or the `org.flatpak.Builder` Flatpak app.
The latter is selected automatically when the native executable is absent.

```sh
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.flatpak.Builder org.gnome.Sdk//50 org.gnome.Platform//50
python3 build-aux/package-flatpak.py
```

The packaging script requires a clean Git working tree. It exports the current
commit into an isolated source directory, builds the existing development
manifest on the `beta` branch, and creates these files in ignored `dist/`:

- `Gisheh-<version>-<architecture>.flatpak`: standalone installable bundle.
- `Gisheh-<version>-source.tar.gz`: exact source snapshot used for that build.
- `SHA256SUMS`: checksums of the bundle and source archive.
- `build-info.json`: source commit, version, architecture, runtime and checksums.

Build caches and the local OSTree repository live in ignored `flatpak-state/`,
`flatpak-build/` and `flatpak-repo/`. Generated files, old build directories,
design experiments and marketing videos are not part of the source snapshot.
The application license is installed under `/app/share/licenses/gisheh/`.

The default Meson configuration includes the public application TMDB read
credential and Simkl client ID. These are extractable application identifiers;
never substitute an account access token or confidential client secret. The
maintainer is responsible for confirming ownership and intended distribution
of the registered application credentials. A successful read request verifies
TMDB access, not ownership of the registered application.

```sh
cd dist
sha256sum --check SHA256SUMS
flatpak install --user ./Gisheh-1.5.0-rc1-x86_64.flatpak
flatpak run io.github.arashe023.Gisheh//beta
```

Bundles do not provide automatic application updates by themselves. Publishing
an OSTree repository or a store release is a separate distribution decision.

## Runtime-only fallback for standalone bundles

When downloading the SDK is unavailable, this pure-Python application can also
be assembled with the native build dependencies from README, `pip`, and an
installed `org.gnome.Platform//50`:

```sh
python3 build-aux/package-flatpak.py --native
```

This uses host Meson/gettext/GResource tools, installs the application into an
architecture-independent Python package directory, and installs only the pinned
`none-any` dependency wheels after SHA256 verification. Host bytecode is removed.
It uses the same permissions, runtime, icons and metadata as the manifest and
exports a normal Flatpak beta bundle. `build-info.json` records
`native-pure-python` instead of `flatpak-builder`. Always run an installed-package
smoke test in the actual Platform runtime; the host's Python version may differ.
This fallback is for standalone testing, not evidence that an SDK build or a
Flathub submission has passed.

## Validate before a stable release

Run the native checks in CONTRIBUTING.md and the installed smoke test. Then test
the actual Flatpak on a real desktop: fresh launch, local library persistence,
upgrade preserving data, import/export portals, offline saved data, Secret
Service, TMDB browsing and optional Simkl login using a test account. Check
Wayland, keyboard navigation, RTL, large text and light/dark appearance.
Record evidence in VALIDATION.md. Do not infer live account or sandbox results
from mocked unit tests. Test aarch64 separately before offering that artifact.

Review changes, update VERSION, RELEASE_DATE, CHANGELOG and the AppStream release
type/notes together. For a stable release remove the `-rcN` suffix and change the
AppStream release type from `development` to `stable`. Run remote CI, freeze a
reviewed commit, and build again from that exact revision. Check screenshot URLs
after publishing the source. Create a new tag and upload artifacts only when
the release has been authorized and its checks are complete.

## Flathub submission

This repository's local-directory manifest is for development and standalone
bundles. It is not a Flathub submission manifest. As checked on 2026-11-06,
[Flathub requirements](https://docs.flathub.org/docs/for-app-authors/requirements)
prohibit AI-generated/AI-assisted submission manifests and AI-authored submission
PRs, commit messages, descriptions and review replies. A human maintainer must
independently author those materials, disclose the affected parts and approximate
extent of AI-assisted upstream code/documentation, and follow the current
[submission procedure](https://docs.flathub.org/docs/for-app-authors/submission).

For that separate submission, establish a controlled public app ID, immutable
upstream revision, supported runtime, source-built dependencies where required,
verified checksums and licenses, minimal permissions, both target architectures,
and successful official lint checks. Native test success and a working standalone
bundle do not imply Flathub acceptance.
