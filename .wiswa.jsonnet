local utils = import 'utils.libjsonnet';

{
  uses_user_defaults: true,
  project_name: 'dade',
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
  version: '0.0.2',
  want_main: true,
  want_flatpak: true,
  publishing+: { flathub: 'sh.tat.dade' },
  local top = self,
  python_deps+: {
    main+: {
      anyio: utils.latestPypiPackageVersionCaret('anyio'),
      bascom: '>=0.2.0',
      // cryptography 49 dropped the macOS universal2 wheels, leaving arm64 only, so an Intel Mac
      // builds from the sdist and links against whichever OpenSSL the runner has. PyInstaller then
      // bundles a different libssl and the binary cannot resolve its symbols. Cap Intel Macs at the
      // last release that still ships a wheel, which statically links its own OpenSSL.
      cryptography: [
        {
          markers: "sys_platform != 'darwin' or platform_machine != 'x86_64'",
          version: utils.latestPypiPackageVersionCaret('cryptography'),
        },
        {
          markers: "sys_platform == 'darwin' and platform_machine == 'x86_64'",
          version: '<49',
        },
      ],
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
    },
  },
  pyinstaller+: {
    vcpkg: {
      enabled: true,
      targets: {
        'windows-11-arm': {
          triplet: 'arm64-windows',
          packages: ['openssl'],
        },
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
  readthedocs+: {
    build+: {
      apt_packages: ['graphviz'],
    },
  },
  shared_ignore+: [
    '*.cl',
    // Built by `dade rbplus site`, and a chart collection besides. What is worth keeping is the
    // source under `assets/site` and the bundle under `dade/rbplus/site`.
    '/charts-test/',
    // The deployed copy of the chart collection, which is a checkout of its own.
    '/rbpcharts/',
    '/site/',
  ],
  // The chart viewer's bundle is built from `assets/site`, not written by hand, and is committed
  // because an install from PyPI has no Node to build it with. It is committed exactly as webpack
  // writes it, so Prettier leaves it alone rather than drifting it from a fresh build.
  gitattributes+: ['/dade/rbplus/site/** linguist-generated=true'],
  prettierignore+: ['/dade/rbplus/site/'],
  // Kept out of every pre-commit hook so none of the file-normalising ones (end-of-file, byte-order
  // mark, line ending) rewrites what webpack emits and drifts it from a fresh build.
  pre_commit_config+: { exclude: '^dade/rbplus/site/' },
  package_json+: {
    cspell+: {
      // The whole built bundle is generated — a minified script and stylesheet, their source maps,
      // and the icons and manifest beside them — so none of it is worth spell-checking.
      ignorePaths+: ['dade/rbplus/site/**'],
    },
    devDependencies+: {
      '@popperjs/core': '^2.11.8',
      '@types/react': '^19.0.0',
      '@types/react-dom': '^19.0.0',
      bootstrap: '^5.3.3',
      'css-loader': '^7.1.2',
      'css-minimizer-webpack-plugin': '^7.0.0',
      'html-webpack-plugin': '^5.6.3',
      'mini-css-extract-plugin': '^2.9.2',
      // Drives a real browser over the built site, which is the only way to check that a page
      // lays out as it should.
      playwright: '^1.62.1',
      react: '^19.0.0',
      'react-dom': '^19.0.0',
      sass: '^1.83.0',
      'sass-loader': '^16.0.4',
      'terser-webpack-plugin': '^5.3.11',
      'ts-loader': '^9.5.2',
      typescript: '^5.7.2',
      webpack: '^5.97.1',
      'webpack-cli': '^6.0.1',
    },
    scripts+: {
      build: 'webpack --mode production',
      'build:check': 'webpack --mode production && git diff --exit-code -- dade/rbplus/site',
      'build:dev': 'webpack --mode development',
    },
  },
}
