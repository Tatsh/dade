local utils = import 'utils.libjsonnet';

{
  uses_user_defaults: true,
  project_name: 'destin',
  description: 'Extract and convert assets from a collection of PC and console video games.',
  keywords: [
    'acclaim',
    'activision',
    'amplitude',
    'bit192labs',
    'bitrock',
    'dreamcast',
    'extractor',
    'extreme-g',
    'harmonix',
    'incoming',
    'installbuilder',
    'interplay',
    'interstate 76',
    'interstate 82',
    'marmalade',
    'monopoly',
    'neversoft',
    'rage software',
    'tone sphere',
    'tony hawk',
  ],
  version: '0.0.0',
  want_main: true,
  want_flatpak: true,
  publishing+: { flathub: 'sh.tat.destin' },
  local top = self,
  python_deps+: {
    main+: {
      anyio: utils.latestPypiPackageVersionCaret('anyio'),
      // debug_option (used by every game's CLI) was added in bascom 0.2.0.
      bascom: '>=0.2.0',
      // Parses the Apple FairPlay certificate embedded in an SC_Info supplement file.
      cryptography: utils.latestPypiPackageVersionCaret('cryptography'),
      jinja2: utils.latestPypiPackageVersionCaret('jinja2'),
      mido: utils.latestPypiPackageVersionCaret('mido'),
      // numpy 2.3 dropped Python 3.10 (it requires >=3.11), which the project still supports, so
      // cap at the last 2.2.x release. Windows on ARM64 is the exception: numpy ships win_arm64
      // wheels only from 2.3, so there (Python is always >=3.11) require >=2.3 to install from a
      // wheel rather than build from source.
      numpy: [
        {
          markers: "platform_machine != 'ARM64' or sys_platform != 'win32' or python_version < '3.11'",
          version: '<=2.2.6',
        },
        {
          markers: "platform_machine == 'ARM64' and sys_platform == 'win32' and python_version >= '3.11'",
          version: '>=2.3',
        },
      ],
      pillow: utils.latestPypiPackageVersionCaret('pillow'),
      rich: utils.latestPypiPackageVersionCaret('rich'),
    },
    tests+: {
      'pytest-asyncio': utils.latestPypiPackageVersionCaret('pytest-asyncio'),
    },
  },
  pyproject+: {
    project+: {
      'optional-dependencies'+: {
        cuda: ['cupy-cuda12x>=13.0.0'],
        lzham: ['pylzham>=0.1.3'],
        opencl: ['pyopencl>=2024.1'],
      },
    },
    tool+: {
      coverage+: {
        report+: {
          omit+: [
            // GPU-only backends: require cupy/pyopencl and a real device, so they cannot run in
            // CI. Excluded from coverage.
            '%s/bitrock/password_cracker/cuda.py' % top.primary_module,
            '%s/bitrock/password_cracker/opencl.py' % top.primary_module,
            '%s/*/__main__.py' % top.primary_module,
            '%s/*/typing.py' % top.primary_module,
          ],
        },
        run+: {
          omit+: [
            // GPU-only backends: require cupy/pyopencl and a real device, so they cannot run in
            // CI. Excluded from coverage.
            '%s/bitrock/password_cracker/cuda.py' % top.primary_module,
            '%s/bitrock/password_cracker/opencl.py' % top.primary_module,
            '%s/*/__main__.py' % top.primary_module,
            '%s/*/typing.py' % top.primary_module,
          ],
        },
      },
      pytest+: {
        ini_options+: {
          addopts: '--import-mode=importlib',
          asyncio_mode: 'strict',
        },
      },
      uv+: {
        // bascom 0.2.0 is newer than the one-week cooldown window, so exempt it and let
        // debug_option resolve.
        'exclude-newer-package': { bascom: '2026-08-08' },
      },
    },
  },
  docs_conf+: {
    config+: {
      intersphinx_mapping+: {
        PIL: ['https://pillow.readthedocs.io/en/stable/', null],
        click: ['https://click.palletsprojects.com/en/stable/', null],
        cryptography: ['https://cryptography.io/en/stable/', null],
        numpy: ['https://numpy.org/doc/stable/', null],
      },
    },
  },
  shared_ignore+: ['*.cl'],
}
