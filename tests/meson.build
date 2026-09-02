test_environment = environment()
test_environment.set('PYTHONPATH', meson.project_source_root() / 'src')

test(
  'python-unit-tests',
  python,
  args: ['-m', 'unittest', 'discover', '-s', meson.current_source_dir(), '-v'],
  env: test_environment,
  timeout: 120,
)
