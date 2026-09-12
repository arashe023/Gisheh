app_id = 'io.github.gisheh.Gisheh'
python_package_dir = python.get_install_dir() / 'gisheh'

build_configuration = configuration_data()
build_configuration.set_quoted('SIMKL_CLIENT_ID', get_option('simkl_client_id'))
build_configuration.set_quoted('TMDB_READ_TOKEN', get_option('tmdb_read_token'))
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
    'gisheh/window.py',
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

glib_compile_resources = find_program('glib-compile-resources')
gisheh_resources = custom_target(
  'gisheh-resources',
  input: 'gisheh/io.github.gisheh.Gisheh.gresource.xml',
  depend_files: files(
    'gisheh/ui/window.ui',
    'gisheh/style.css',
    'gisheh/library.json',
    'gisheh/assets/tmdb-logo.svg',
  ),
  output: 'gisheh.gresource',
  command: [
    glib_compile_resources,
    '--sourcedir', meson.current_source_dir() / 'gisheh',
    '--target', '@OUTPUT@',
    '@INPUT@',
  ],
  install: true,
  install_dir: python_package_dir,
)
