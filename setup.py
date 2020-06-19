import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="osc-control-stagelab", 
    version="0.0.0",
    author="Ion Reguera",
    author_email="ion@stagelab.net",
    description="A small example package",
    long_description=long_description,
    url="https://github.com/stagesoft/osc_control",
    package_dir={'osc-control': 'src'},

    packages=setuptools.find_packages(where='src'),
    package_data={  # Optional
        'xml': ['settings.xml'],
        'xds': ['settings.xds'],
    },
    entry_points={  # Optional
        'console_scripts': [
            'ossia_server=ossia_server:main',
        ],
    },

    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)