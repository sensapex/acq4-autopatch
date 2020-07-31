from setuptools import setup, find_packages

packages = [x for x in find_packages('.') if x.startswith('acq4_autopatch')]

setup(
    name="acq4_autopatch",
    version="0.0.1",
    author="",
    author_email="",
    description=(""),
    license="",
    url="",
    packages=packages,
)
