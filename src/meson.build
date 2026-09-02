app_id = 'io.github.cineshelf.CineShelf'
python_package_dir = python.get_install_dir() / 'cineshelf'

python.install_sources(
  files(
    'cineshelf/__init__.py',
    'cineshelf/application.py',
    'cineshelf/main.py',
    'cineshelf/window.py',
  ),
  subdir: 'cineshelf',
)

python.install_sources(
  files(
    'cineshelf/services/__init__.py',
    'cineshelf/services/image_http.py',
    'cineshelf/services/simkl_client.py',
    'cineshelf/services/tmdb_client.py',
  ),
  subdir: 'cineshelf/services',
)

launcher_configuration = configuration_data()
launcher_configuration.set('PYTHON', python.full_path())
launcher_configuration.set('PYTHON_PACKAGE_ROOT', python.get_install_dir())
configure_file(
  input: 'cineshelf.in',
  output: 'cineshelf',
  configuration: launcher_configuration,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

glib_compile_resources = find_program('glib-compile-resources')
cineshelf_resources = custom_target(
  'cineshelf-resources',
  input: 'cineshelf/io.github.cineshelf.CineShelf.gresource.xml',
  output: 'cineshelf.gresource',
  command: [
    glib_compile_resources,
    '--sourcedir', meson.current_source_dir() / 'cineshelf',
    '--target', '@OUTPUT@',
    '@INPUT@',
  ],
  install: true,
  install_dir: python_package_dir,
)
