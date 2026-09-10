Development
===========

Set up a working tree with `uv <https://docs.astral.sh/uv/>`_ and Yarn:

.. code-block:: shell

   uv sync --all-groups --all-extras
   yarn install

Run the formatters and the quality-assurance checks:

.. code-block:: shell

   yarn format
   yarn qa

``yarn qa`` runs the type checks and linters; the test suite runs under
`pytest <https://docs.pytest.org/en/stable/>`_ with full branch coverage. Both ``yarn format`` and
``yarn qa`` must exit cleanly before committing.

Documentation
-------------

The documentation is built with `Sphinx <https://www.sphinx-doc.org/>`_:

.. code-block:: shell

   yarn gen-docs

The build runs with warnings treated as errors, and a new public module must be added to the
:doc:`api/index` reference (or, for a command, to :doc:`utilities`) for the build to pass.
