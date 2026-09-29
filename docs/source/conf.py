"""Sphinx configuration file."""  # noqa: INP001

import sys
from pathlib import Path

from sphinx.application import Sphinx
from sphinx.ext import apidoc

SOURCE_DIR = Path(__file__).parent.resolve()
PACKAGE_DIR = (SOURCE_DIR / "../../src/aio_remeha_modbus").resolve()

sys.path.insert(0, str(PACKAGE_DIR.parent))
# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "aio-remeha-modbus"
copyright = "2026, houthacker"  # noqa: A001
author = "houthacker"
release = "4.0.1"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ["sphinx.ext.autodoc", "sphinx.ext.napoleon"]

templates_path = ["_templates"]
exclude_patterns = []

# The builtin `type` in annotations fuzzy-matches unrelated `.type` attributes.
suppress_warnings = ["ref.python"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "alabaster"


def run_apidoc(_app: Sphinx) -> None:
    """Regenerate the API reference pages from the package source."""

    apidoc.main(["--force", "--no-toc", "--separate", "--module-first", "-o", str(SOURCE_DIR / "api"), str(PACKAGE_DIR)])


def setup(app: Sphinx) -> None:
    """Register the apidoc hook."""

    app.connect("builder-inited", run_apidoc)
