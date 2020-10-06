from os import path

from setuptools import setup, find_packages

packages = [x for x in find_packages(".") if x.startswith("acq4_autopatch")]

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    author="Luke Campagnola",
    author_email="luke.campagnola@gmail.com",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Other Environment",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python",
        "Topic :: Scientific/Engineering",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    description=("Automated cell patching extension for ACQ4"),
    install_requires=[
        "acq4",
    ],
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="LGPL-3",
    name="acq4_autopatch",
    packages=packages,
    url="https://github.com/sensapex/acq4-autopatch",
    version="0.0.2",
)
