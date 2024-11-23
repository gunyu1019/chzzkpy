# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys

from dataclasses import asdict
from sphinxawesome_theme import ThemeOptions

sys.path.insert(0, os.path.abspath('..'))
sys.path.append(os.path.abspath('chat'))

project = 'chzzkpy'
copyright = '2024, gunyu1019'
author = 'gunyu1019'
release = 'v1.0.3'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    'sphinx.ext.intersphinx',
]
add_module_names = False

intersphinx_mapping = {
  'py': ('https://docs.python.org/3', None),
  'aio': ('https://docs.aiohttp.org/en/stable/', None)
}

templates_path = ['_templates']
exclude_patterns = []

language = 'en'

locale_dirs = ['locale/']
gettext_compact = False

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinxawesome_theme'
html_static_path = ['_static']
html_css_files = ["custom_theme.css"]

## Template Option
html_title = "chzzkpy"
html_sidebars = {
  "**": ["sidebar_main_nav_links.html", "global_sidebar_toc.html"]
}