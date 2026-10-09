app_id = 'io.github.arashe023.Gisheh'
python_package_dir = python.get_install_dir() / 'gisheh'

build_configuration = configuration_data()
build_configuration.set_quoted('APP_VERSION', meson.project_version())
build_configuration.set_quoted('SIMKL_CLIENT_ID', get_option('simkl_client_id'))
build_configuration.set_quoted('TMDB_READ_TOKEN', get_option('tmdb_read_token'))
build_configuration.set_quoted(
  'LOCALE_DIR',
  get_option('prefix') / get_option('localedir'),
)
configured_build_module = configure_file(
  input: 'gisheh/_build_config.py.in',
  output: '_build_config.py',
  configuration: build_configuration,
  install: true,
  install_dir: python_package_dir,
)

python.install_sources(
  files(
    'gisheh/__init__.py',
    'gisheh/application.py',
    'gisheh/main.py',
    'gisheh/onboarding.py',
    'gisheh/state_store.py',
    'gisheh/version.py',
    'gisheh/window.py',
    'gisheh/controllers.py',
    'gisheh/jobs.py',
    'gisheh/transactions.py',
    'gisheh/recovery.py',
    'gisheh/library_backup.py',
    'gisheh/data_actions.py',
    'gisheh/app_logging.py',
    'gisheh/constants.py',
    'gisheh/layout.py',
    'gisheh/localization.py',
    'gisheh/models.py',
    'gisheh/widgets.py',
    'gisheh/profile.py',

  ),
  subdir: 'gisheh',
)

python.install_sources(
  files(
    'gisheh/services/__init__.py',
    'gisheh/services/image_http.py',
    'gisheh/services/simkl_client.py',
    'gisheh/services/tmdb_client.py',
  ),
  subdir: 'gisheh/services',
)

launcher_configuration = configuration_data()
launcher_configuration.set('PYTHON', python.full_path())
launcher_configuration.set('PYTHON_PACKAGE_ROOT', python.get_install_dir())
configured_launcher = configure_file(
  input: 'gisheh.in',
  output: 'gisheh-configured',
  configuration: launcher_configuration,
)

gisheh_launcher = custom_target(
  'gisheh',
  input: configured_launcher,
  output: 'gisheh',
  command: [
    python,
    meson.project_source_root() / 'build-aux/prepare-launcher.py',
    '@INPUT@',
    '@OUTPUT@',
  ],
  build_by_default: true,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

gisheh_resources = gnome.compile_resources(
  'gisheh',
  'gisheh/io.github.arashe023.Gisheh.gresource.xml',
  source_dir: 'gisheh',
  gresource_bundle: true,
  install: true,
  install_dir: python_package_dir,
)
