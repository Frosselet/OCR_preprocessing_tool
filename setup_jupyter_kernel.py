#!/usr/bin/env python3
"""
Setup Jupyter kernel for OCR Pipeline

This script:
1. Installs Python dependencies with uv
2. Registers a Jupyter kernel using the uv virtual environment
3. Verifies the setup
"""

import subprocess
import sys
import shutil
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        print(f"✅ {description} - Done")
        return result
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} - Failed")
        print(f"Error: {e.stderr}")
        sys.exit(1)


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║                                                          ║")
    print("║     Jupyter Kernel Setup for OCR Pipeline               ║")
    print("║                                                          ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Check uv is installed
    if not shutil.which('uv'):
        print("❌ uv not found. Please install uv first:")
        print("   curl -LsSf https://astral.sh/uv/install.sh | sh")
        sys.exit(1)

    print("✅ uv found")
    print()

    # Install dependencies
    run_command("uv sync", "Installing Python dependencies")
    print()

    # Install ipykernel and register kernel
    run_command(
        "uv run python -m ipykernel install --user --name=ocr-pipeline --display-name='OCR Pipeline (uv)'",
        "Installing Jupyter kernel"
    )
    print()

    # Verify kernel installation
    print("🔍 Verifying kernel installation...")
    result = subprocess.run(
        "jupyter kernelspec list",
        shell=True,
        capture_output=True,
        text=True
    )

    if "ocr-pipeline" in result.stdout:
        print("✅ Kernel verified")
        print()
        print("Installed kernels:")
        for line in result.stdout.split('\n'):
            if 'ocr-pipeline' in line:
                print(f"  ✓ {line}")
    else:
        print("⚠️  Kernel installed but not showing in list")

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║                                                          ║")
    print("║                 ✅ Setup Complete!                       ║")
    print("║                                                          ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print("Kernel installed: OCR Pipeline (uv)")
    print()
    print("To launch Jupyter:")
    print("  uv run jupyter notebook pipeline_demo.ipynb")
    print()
    print("The notebook will automatically use the correct kernel.")
    print()


if __name__ == '__main__':
    main()
