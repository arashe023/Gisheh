project(
  'gisheh',
  version: files('VERSION'),
  meson_version: '>= 1.3.0',
  license: 'MIT',
)

gnome = import('gnome')
i18n = import('i18n')
python = import('python').find_installation('python3')
fs = import('fs')

release_date = fs.read('RELEASE_DATE').strip()

dependency('gtk4', version: '>= 4.12')
dependency('libadwaita-1', version: '>= 1.9')
dependency('libsecret-1', version: '>= 0.20')

subdir('data')
subdir('src')
subdir('po')
if get_option('tests')
  subdir('tests')
endif
