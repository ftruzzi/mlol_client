import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="mlol_client",
    version="0.0.1",
    author="Francesco Truzzi",
    author_email="francesco@truzzi.me",
    description="A Python client for MLOL (medialibrary.it)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ftruzzi/mlol_client",
    packages=setuptools.find_packages(),
    python_requires=">=3.6",
)
