from setuptools import setup, find_packages
from konverge import VERSION


setup(
    name="konverge",
    version=VERSION,
    author="DreamPathsProjekt",
    url="https://github.com/dreamPathsProjekt/konverge",
    packages=find_packages(),
    include_package_data=True,
    package_dir={'konverge': 'konverge'},
    package_data={'konverge': ['bootstrap/*.sh', 'bootstrap/*.yaml', 'bootstrap/*.json']},
    install_requires=[
        "bcrypt ==3.1.7",
        "certifi ==2019.11.28",
        "cffi ==1.13.2",
        "chardet ==3.0.4",
        "click ==7.1.1",
        "colorama ==0.4.3",
        "crayons ==0.3.0",
        "cryptography ==3.2",
        "fabric2 ==2.5.0",
        "idna ==2.8",
        "invoke ==1.4.1",
        "jsonschema ==3.2.0",
        "attrs ==19.3.0",
        "importlib-metadata ==1.5.0",
        "pyrsistent ==0.15.7",
        "zipp ==2.1.0",
        "paramiko ==2.7.1",
        "proxmoxer ==1.0.4",
        "pycparser ==2.19",
        "PyNaCl ==1.3.0",
        "PyYAML ==5.4",
        "requests ==2.22.0",
        "retrying ==1.3.3",
        "six ==1.14.0",
        "urllib3 ==1.26.5"
    ],
    entry_points="""
    [console_scripts]
    konverge=konverge.cli:cli
    """,
)
