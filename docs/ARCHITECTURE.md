# Architecture

`application` owns activation, first-run onboarding and startup recovery.
`main` initializes localization and GTK and registers the installed GResource.
`window` connects navigation, view state, GTK signals and asynchronous results.

## GTK-independent components

- `constants`, `localization`, `models` and `layout`: domain records, serialization,
  catalog conversion, watch calculations, display names and responsive decisions.
- `state_store`: schema validation/migration, private atomic writes, backup and
  explicit recovery. Missing state differs from corrupt/unreadable/future state.
- `library_backup`: versioned local interchange with validation and credential/
  filesystem-cache exclusion. It performs no network operations.
- `controllers`: injected service orchestration for Calendar, Explore, Details
  and Sync. Calendar grouping/filtering and incremental reconciliation are
  testable without constructing a window.
- `jobs`: shared worker pools, context propagation and session invalidation.
- `app_logging`: private rotating application logs.

## UI components

`widgets` contains standalone poster, media viewer and sidebar widgets.
`data_actions` owns portal file dialogs and explicit local-library replacement.
`recovery` owns the startup recovery window. `transactions` wraps mutation
boundaries so failed local writes restore in-memory personal state. A server
mutation that has already succeeded is reported distinctly and never retried
automatically because local persistence failed.

The window retains view construction and view-specific async assembly. Existing
imports of moved public helpers from window remain compatibility exports;
new domain tests and modules should import their owning module directly.

## Data contracts

State uses schema_version 1; an absent version is legacy schema 0 and migrates
in memory, preserving unknown fields. Writes persist the upgraded representation.
Future schemas are not writable. Recovery preserves original bytes before
replacement. The backup is the previous healthy state, not a second independent
sync source. Personal state for Local-first is retained separately from Simkl.

Portable backups use format `io.github.arashe023.Gisheh.local-library` and
format_version 1. The envelope includes app_version, exported_at (UTC),
localLibrary and localProfile. Restore replaces local records and personal
state while retaining preferences and cloud-account data. It never changes
cloud records. The import limit is 50 MiB. Import also keeps a timestamped recovery copy, so subsequent ordinary saves cannot overwrite the pre-import recovery point.

## Background lifecycle

A window owns four orchestration workers and eight shared image workers.
Callbacks are dispatched through GLib on the main thread. A session epoch is
carried through nested image work and checked on delivery; closing a window or
changing library ownership invalidates old work. Existing request-generation
checks also guard page-specific results. Running network requests finish under
the client's timeouts; queued work is cancelled on shutdown. Already issued
remote writes cannot be undone by cancelling a callback.
