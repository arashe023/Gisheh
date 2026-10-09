project(
  'gisheh',
  version: files('VERSION'),
  meson_version: '>= 1.3.0',
  license: 'MIT',
)

gnome = import('gnome')
i18n = import('i18n')
python = import('python').find_installation('python3', modules: ['gi', 'cairo', 'httpx'])
fs = import('fs')
if not python.language_version().version_compare('>= 3.11')
  error('Gisheh requires Python 3.11 or newer')
endif

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

install_data('LICENSE', install_dir: get_option('datadir') / 'licenses' / 'gisheh')
