# Data and privacy

Local-first keeps your watchlist, ratings and viewing history on your device.
It does not upload your local library to Simkl. Browsing Explore, searching,
loading catalog details and fetching artwork still contact TMDB and its image
service. These requests reveal normal network information and requested titles
or searches to those services. Local-first is not a network-free mode.

Simkl mode is optional. Connecting uses Simkl's PIN flow. Library changes in
that mode are sent to Simkl. A local snapshot supports fast startup and recovery
from network failures. Switching ownership does not itself import a portable
backup into the cloud. Calendar requests use the calendar integration.

The Simkl access token is stored in the system Secret Service where available,
with a private file fallback. The build's TMDB read credential and public Simkl
client identifier are extractable application configuration, not client secrets.
Do not put confidential credentials in Meson release options.

Application state, automatic backups and recovery copies contain personal
viewing data. They use private filesystem permissions. Export files also contain
viewing data, but omit credentials, logs and cached artwork paths. The user
chooses their destination through the desktop file chooser. Exports may remain
after resetting or uninstalling the application.

Logs are local and rotated. Review them before sharing a bug report. Reset
removes the application's state, credentials, caches, logs and automatic state
backups; independently exported files remain under the user's control.
