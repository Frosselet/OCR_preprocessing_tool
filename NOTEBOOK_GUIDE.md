# Jupyter Notebook Guide

## Quick Start

```bash
# 1. First-time setup: Install Jupyter kernel
python setup_jupyter_kernel.py
# This registers our uv environment with Jupyter (only needed once)

# 2. Launch Jupyter notebook
uv run jupyter notebook pipeline_demo.ipynb

# Your browser will open automatically
```

### Why Do I Need to Setup a Kernel?

Jupyter notebooks run code in a "kernel" - essentially a Python interpreter. By default, Jupyter might use your system Python, which doesn't have our dependencies installed. The `setup_jupyter_kernel.py` script registers our uv virtual environment (`.venv/`) as a Jupyter kernel, ensuring the notebook has access to all required packages (pytesseract, baml-py, opencv, etc.).

**You only need to run this once per project.**

## What the Notebook Does

### Section 1: Setup Validation (Cells 1-4)
Checks your environment and verifies:
- ✅ Python dependencies (numpy, opencv, pytesseract, baml-py, etc.)
- ✅ System dependencies (Tesseract OCR, Poppler)
- ✅ API keys (ANTHROPIC_API_KEY or OPENAI_API_KEY)
- ✅ Pipeline modules are importable

**Action:** Run these cells to ensure everything is ready.

### Section 2: Browse PDFs (Cells 5-6)
- Lists all PDFs in `test_images/` folder
- Shows file sizes and page counts
- Generates thumbnail previews of first page

**Action:** See what PDFs are available to process.

### Section 3: Select PDF (Cells 7-8)
- Choose which PDF to process
- Configure OCR settings (DPI, language)
- Set output paths

**Action:** Edit Cell 8 to select your PDF:
```python
selected_pdf = "graincorp.pdf"  # <-- Change this
```

### Section 4: PDF → Markdown (Cells 9-10)
- Converts PDF to images at specified DPI
- Runs Tesseract OCR with spatial table extraction
- Generates markdown with GitHub-flavored tables
- Shows preview of output

**Action:** Run to get markdown output.

### Section 5: Define Schema (Cells 11-12)
- Choose to use example schema or create custom
- Define the structure for 1NF output
- Specify field names, types, and descriptions

**Action:** Use example schema or customize for your use case.

### Section 6: Markdown → 1NF (Cells 13-17)
- Analyzes table structure with BAML
- Detects table type (hierarchical, pivot, etc.)
- Converts to normalized 1NF records
- Saves to JSON file
- Displays results

**Action:** Run to get structured data.

### Section 7: Summary (Cell 18)
- Shows complete pipeline results
- Lists output files
- Provides next steps

### Section 8: Batch Processing (Cell 19)
- Optional: Process ALL PDFs in test_images/
- Runs complete pipeline on each file
- Generates summary report

**Action:** Set `run_batch = True` to process multiple PDFs.

## Troubleshooting

### "No module named 'pytesseract'" or other import errors in notebook

This usually means the notebook is using the wrong kernel.

**Solution:**
1. Run the kernel setup: `python setup_jupyter_kernel.py`
2. In Jupyter, go to **Kernel → Change Kernel → OCR Pipeline (uv)**
3. Restart the kernel and re-run cells

**Verify kernel:**
```bash
jupyter kernelspec list
# Should show: ocr-pipeline
```

### Wrong Python environment in notebook

Check which Python the notebook is using by running this in a cell:
```python
import sys
print(sys.executable)
```

It should show: `/path/to/OCR_preprocessing_tool/.venv/bin/python3`

If not, change the kernel to "OCR Pipeline (uv)" from the Kernel menu.

### "Tesseract not found"
Install Tesseract:
- macOS: `brew install tesseract`
- Ubuntu: `sudo apt-get install tesseract-ocr`

### "No API key found"
Set your API key before launching notebook:
```bash
export ANTHROPIC_API_KEY=your_key_here
uv run jupyter notebook pipeline_demo.ipynb
```

### "pdf2image error"
Install Poppler:
- macOS: `brew install poppler`
- Ubuntu: `sudo apt-get install poppler-utils`

### Notebook won't open
Try launching Jupyter Lab instead:
```bash
uv run jupyter lab
# Then navigate to pipeline_demo.ipynb
```

## Tips

### Processing Different PDFs
Simply edit Cell 8 and change the filename:
```python
selected_pdf = "your_document.pdf"
```

Then re-run cells 9+ to process the new file.

### Custom Schemas
Uncomment and edit Cell 12 to define your own schema:
```python
user_schema = {
    "className": "YourRecord",
    "fields": {
        "field1": {"type": "string", "required": True},
        # ...
    }
}
```

### Viewing Results
- **Markdown:** Check `output/{filename}_output.md`
- **JSON:** Check `output/{filename}_normalized.json`

You can open these files in VS Code or any text editor.

### Batch Processing
Enable in Cell 19:
```python
run_batch = True  # Process all PDFs
```

This will:
1. Convert all PDFs to markdown
2. Normalize all tables to 1NF
3. Save results for each file
4. Generate summary report

## Keyboard Shortcuts

- **Run cell:** `Shift + Enter`
- **Run cell and insert below:** `Alt + Enter`
- **Insert cell above:** `A`
- **Insert cell below:** `B`
- **Delete cell:** `D D` (press D twice)
- **Restart kernel:** `0 0` (press 0 twice)

## Example Workflow

1. Run cells 1-4 to validate setup ✅
2. Run cells 5-6 to browse PDFs 📁
3. Edit cell 8 to select a PDF ✏️
4. Run cells 9-10 to convert to markdown 📄
5. Run cell 11 to load schema 📋
6. Run cells 13-17 to normalize to 1NF 🔬
7. Check output files! 🎉

## Next Steps

After successfully running the notebook:

1. **Try different PDFs:** Add your own PDFs to `test_images/`
2. **Create custom schemas:** Edit Cell 12 to match your data structure
3. **Process in production:** Use the command-line scripts:
   ```bash
   uv run python pdf_to_markdown.py input.pdf output.md
   uv run python table_normalizer.py output.md result.json --schema schema.json
   ```
4. **Integrate into your pipeline:** Import the modules in your own code

## Questions?

See the main documentation:
- [README.md](README.md) - Main documentation
- [BAML_README.md](BAML_README.md) - BAML normalization details
- [QUICKSTART.md](QUICKSTART.md) - Quick setup guide
