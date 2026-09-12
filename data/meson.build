app_id = 'io.github.gisheh.Gisheh'

desktop_file = configure_file(
  input: app_id + '.desktop.in',
  output: app_id + '.desktop',
  configuration: {'EXECUTABLE': 'gisheh'},
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

install_data(
  app_id + '.metainfo.xml.in',
  install_dir: get_option('datadir') / 'metainfo',
  rename: app_id + '.metainfo.xml',
)

install_data(
  app_id + '.gschema.xml',
  install_dir: get_option('datadir') / 'glib-2.0/schemas',
)

install_data(
  'icons/hicolor/scalable/apps/' + app_id + '.svg',
  install_dir: get_option('datadir') / 'icons/hicolor/scalable/apps',
)

install_data(
  'icons/hicolor/symbolic/apps/' + app_id + '-symbolic.svg',
  install_dir: get_option('datadir') / 'icons/hicolor/symbolic/apps',
)

gnome.compile_schemas(depend_files: files(app_id + '.gschema.xml'))

desktop_file_validate = find_program('desktop-file-validate', required: false)
if desktop_file_validate.found()
  test('validate-desktop', desktop_file_validate, args: [desktop_file])
endif

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test(
    'validate-appstream',
    appstreamcli,
    args: ['validate', '--no-net', meson.current_source_dir() / (app_id + '.metainfo.xml.in')],
  )
endif

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
