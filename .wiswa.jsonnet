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
      poetry+: {
        dependencies+: {
          anyio: utils.latestPypiPackageVersionCaret('anyio'),
          jinja2: utils.latestPypiPackageVersionCaret('jinja2'),
          mido: utils.latestPypiPackageVersionCaret('mido'),
          // numpy 2.3+ drops Python 3.10 and 3.11, which the project still supports, so cap at the
          // last 2.2.x release rather than the floating caret the helper would produce.
          numpy: '<=2.2.6',
          pillow: utils.latestPypiPackageVersionCaret('pillow'),
          rich: utils.latestPypiPackageVersionCaret('rich'),
        },
        group+: {
          tests+: {
            dependencies+: {
              'pytest-asyncio': utils.latestPypiPackageVersionCaret('pytest-asyncio'),
            },
          },
        },
      },
      pytest+: {
        ini_options+: {
          addopts: '--import-mode=importlib',
          asyncio_mode: 'strict',
        },
      },
    },
  },
  docs_conf+: {
    config+: {
      intersphinx_mapping+: {
        PIL: ['https://pillow.readthedocs.io/en/stable/', null],
        click: ['https://click.palletsprojects.com/en/stable/', null],
        numpy: ['https://numpy.org/doc/stable/', null],
      },
    },
  },
  shared_ignore+: ['*.cl'],
}
