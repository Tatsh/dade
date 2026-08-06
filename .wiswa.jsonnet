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
            '%s/*/__main__.py' % top.primary_module,
            '%s/*/typing.py' % top.primary_module,
          ],
        },
        run+: {
          omit+: [
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
          // numpy 2.5+ requires Python >= 3.12; keep a loose lower bound so uv can fork-resolve an
          // older numpy for Python 3.10 and 3.11.
          numpy: '>=1.26',
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
