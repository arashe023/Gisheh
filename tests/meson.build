test_environment = environment()
test_environment.set('PYTHONPATH', meson.project_source_root() / 'src')
test_environment.set('GSETTINGS_SCHEMA_DIR', meson.project_build_root() / 'data')
test_environment.set('GSETTINGS_BACKEND', 'memory')
test_environment.set('GDK_BACKEND', 'x11')
test_environment.set('GSK_RENDERER', 'cairo')
test_environment.set('PYTHONFAULTHANDLER', '1')
test_runner = meson.current_source_dir() / 'run.py'
test('python-unit-tests', python, args: [test_runner, 'unit'], env: test_environment, timeout: 120)
xvfb = find_program('xvfb-run')
dbus = find_program('dbus-run-session')
test('gtk-tests', xvfb,
  args: ['-a', dbus.full_path(), '--', python.full_path(), test_runner, 'gtk'],
  env: test_environment, timeout: 180, is_parallel: false)
