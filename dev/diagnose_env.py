#!/usr/bin/env python3
import os
import sys
import site
import platform
import subprocess
from pathlib import Path

def get_poetry_info():
    try:
        result = subprocess.run(['poetry', '--version'], capture_output=True, text=True)
        return result.stdout.strip()
    except:
        return "Poetry not found"

def get_python_info():
    return {
        'version': sys.version,
        'implementation': platform.python_implementation(),
        'platform': platform.platform(),
        'executable': sys.executable
    }

def get_path_info():
    return {
        'PYTHONPATH': os.environ.get('PYTHONPATH', 'Not set'),
        'sys.path': sys.path,
        'site_packages': site.getsitepackages(),
        'current_dir': str(Path.cwd()),
        'src_dir_exists': Path('src').exists(),
        'src_dir_at_parent_exists': Path('../src').exists(),
        'src_cuemsengine_exists': Path('src/cuemsengine').exists()
    }

def get_poetry_env_info():
    try:
        result = subprocess.run(['poetry', 'env', 'info'], capture_output=True, text=True)
        return result.stdout
    except:
        return "Failed to get Poetry environment"

def main():
    print("=== Environment Diagnostic Information ===")
    print("\n=== Poetry Version ===")
    print(get_poetry_info())
    
    print("\n=== Python Information ===")
    python_info = get_python_info()
    for key, value in python_info.items():
        print(f"{key}: {value}")
    
    print("\n=== Path Information ===")
    path_info = get_path_info()
    for key, value in path_info.items():
        if isinstance(value, list):
            print(f"\n{key}:")
            for item in value:
                print(f"  - {item}")
        else:
            print(f"{key}: {value}")
    
    print("\n=== Poetry Environment Information ===")
    print(get_poetry_env_info())

if __name__ == '__main__':
    main() 
