from setuptools import setup, find_packages

setup(
    name="dsl_executor",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="A Python library for executing DSL-based workflows using DAGs.",
    long_description="",
    long_description_content_type="text/markdown",
    url="",
    packages=find_packages(),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
    install_requires=[
        "requests>=2.20.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "flake8>=3.9.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "dsl-executor=dsl_executor.cli:main",
        ],
    },
)
