import re

from setuptools import setup

version = ""
with open("chzzkpy/__init__.py") as f:
    version = re.search(
        r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', f.read(), re.MULTILINE
    ).group(1)

if not version:
    raise RuntimeError("version is not set")


extras_require = {
    "test": ["pytest", "pytest-cov"],
    "lint": ["pycodestyle", "black"],
    "docs": ["Sphinx", "sphinxawesome-theme", "sphinx-intl"],
}

setup(
    name="chzzkpy",
    version=version,
    packages=["chzzkpy", "chzzkpy.chat", "chzzkpy.manage", "chzzkpy.offical"],
    url="https://github.com/gunyu1019/chzzkpy",
    project_urls={
        "Documentation (한국어)": "https://gunyu1019.github.io/chzzkpy/ko/",
        "Documentation (English)": "https://gunyu1019.github.io/chzzkpy/en/",
    },
    license="MIT",
    author="gunyu1019",
    author_email="gunyu1019@gmail.com",
    description="An unofficial Python library of Chzzk(Naver live-streaming service)",
    python_requires=">=3.10",
    extras_require=extras_require,
    long_description=open("README.md", encoding="UTF-8").read(),
    long_description_content_type="text/markdown",
    include_package_data=True,
    install_requires=open("requirements.txt", encoding="UTF-8").read(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved :: MIT License",
        "Intended Audience :: Developers",
        "Natural Language :: Korean",
        "Natural Language :: English",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Internet",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Utilities",
    ],
)
