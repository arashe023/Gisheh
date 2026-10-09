app_id = 'io.github.arashe023.Gisheh'

release_configuration = configuration_data()
release_configuration.set('PROJECT_VERSION', meson.project_version())
release_configuration.set('RELEASE_DATE', release_date)

desktop_template = configure_file(
  input: app_id + '.desktop.in',
  output: app_id + '.desktop.in',
  configuration: {'EXECUTABLE': 'gisheh'},
)

metainfo_template = configure_file(
  input: app_id + '.metainfo.xml.in',
  output: app_id + '.metainfo.xml.in',
  configuration: release_configuration,
)

desktop_file = i18n.merge_file(
  input: desktop_template,
  output: app_id + '.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications',
)
metainfo_file = i18n.merge_file(
  input: metainfo_template,
  output: app_id + '.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
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
    args: ['validate', '--no-net', metainfo_file],
  )
endif

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
