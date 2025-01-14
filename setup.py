from setuptools import setup


with open("README.md", encoding='utf-8') as fh:
    long_description = fh.read()

with open("requirements.txt", encoding='utf-8') as fh:
    install_requires = fh.read()

NAME = "vardefunc"
VERSION = "0.7.2"

setup(
    name=NAME,
    version=VERSION,
    author="Vardë",
    author_email="ichunjo.le.terrible@gmail.com",
    description="Vardë's Vapoursynth functions",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Ichunjo/vardefunc",
    packages=["vardefunc"],
    package_data={
        'vardefunc': ['py.typed'],
    },
    install_requires=install_requires,
    python_requires=">=3.10",
    zip_safe=False,
    classifiers=[
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
