#!/bin/bash
# Setup Jupyter kernel for OCR Pipeline

set -e

echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║     Jupyter Kernel Setup for OCR Pipeline               ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv not found. Please install uv first:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "✅ uv found"

# Install dependencies
echo ""
echo "📦 Installing Python dependencies..."
uv sync

# Install ipykernel in the venv and register it
echo ""
echo "🔧 Installing Jupyter kernel..."
uv run python -m ipykernel install --user --name=ocr-pipeline --display-name="OCR Pipeline (uv)"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║                 ✅ Setup Complete!                       ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Kernel installed: OCR Pipeline (uv)"
echo ""
echo "To launch Jupyter:"
echo "  uv run jupyter notebook pipeline_demo.ipynb"
echo ""
echo "The notebook will automatically use the correct kernel."
echo ""
