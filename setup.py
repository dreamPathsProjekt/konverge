from setuptools import setup, find_packages
from konverge import VERSION


setup(
    name="konverge",
    version=VERSION,
    author="DreamPathsProjekt",
    url="https://github.com/dreamPathsProjekt/konverge",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "bcrypt ==3.1.7",
        "certifi ==2019.11.28",
        "cffi ==1.13.2",
        "chardet ==3.0.4",
        "colorama ==0.4.3",
        "crayons ==0.3.0",
        "cryptography ==2.8",
        "fabric2 ==2.5.0",
        "idna ==2.8",
        "invoke ==1.4.1",
        "paramiko ==2.7.1",
        "proxmoxer ==1.0.4",
        "pycparser ==2.19",
        "PyNaCl ==1.3.0",
        "PyYAML ==5.3",
        "requests ==2.22.0",
        "six ==1.14.0",
        "urllib3 ==1.25.8"
    ],
    entry_points="""
    [console_scripts]
    konverge=konverge:execute
    """,
)
