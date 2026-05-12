from setuptools import setup, find_packages

setup(
    name="keri",
    version="0.1.0",
    description="Key Event Receipt Infrastructure (KERI) Python Library",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="KERI Contributors",
    packages=find_packages(),
    python_requires=">=3.8",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Topic :: Security :: Cryptography",
        "Topic :: Software Development :: Libraries",
    ],
)
