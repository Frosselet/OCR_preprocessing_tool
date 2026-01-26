# Switching AI Providers in BAML

## Current Configuration

**Default Provider:** OpenAI GPT-5

The pipeline is configured to use OpenAI's GPT-5 model for table analysis and normalization.

## Quick Switch to Other Providers

### Option 1: Use Anthropic Claude (Sonnet 4)

```bash
# 1. Set API key
export ANTHROPIC_API_KEY=your_key_here

# 2. Edit baml_src/table_analysis.baml
# Change both functions from:
client CustomGPT5
# To:
client CustomSonnet4

# 3. Regenerate BAML client
baml-cli generate

# 4. Done! Pipeline now uses Claude Sonnet 4
```

### Option 2: Use OpenAI GPT-5 Mini (Faster, Cheaper)

```bash
# 1. Ensure OPENAI_API_KEY is set
export OPENAI_API_KEY=your_key_here

# 2. Edit baml_src/table_analysis.baml
# Change both functions from:
client CustomGPT5
# To:
client CustomGPT5Mini

# 3. Regenerate BAML client
baml-cli generate

# 4. Done! Pipeline now uses GPT-5 Mini
```

### Option 3: Use Claude Haiku (Fast & Cheap)

```bash
# 1. Set API key
export ANTHROPIC_API_KEY=your_key_here

# 2. Edit baml_src/table_analysis.baml
# Change both functions from:
client CustomGPT5
# To:
client CustomHaiku

# 3. Regenerate BAML client
baml-cli generate

# 4. Done! Pipeline now uses Claude Haiku
```

## Available Clients

All clients are pre-configured in `baml_src/clients.baml`:

| Client | Provider | Model | Speed | Cost | Best For |
|--------|----------|-------|-------|------|----------|
| CustomGPT5 | OpenAI | gpt-5 | Medium | Medium | Default - Good balance |
| CustomGPT5Mini | OpenAI | gpt-5-mini | Fast | Low | Quick testing, simple tables |
| CustomSonnet4 | Anthropic | claude-sonnet-4 | Medium | Medium | Complex tables, high accuracy |
| CustomOpus4 | Anthropic | claude-opus-4 | Slow | High | Maximum accuracy |
| CustomHaiku | Anthropic | claude-haiku-3.5 | Very Fast | Very Low | Simple tables, batch processing |

## How to Edit the Configuration

### 1. Open the BAML Schema File

```bash
# Edit with your preferred editor
code baml_src/table_analysis.baml
# or
vim baml_src/table_analysis.baml
```

### 2. Find the Two Functions

Look for:
```baml
function AnalyzeTableStructure(markdownTable: string, pageContext: string?) -> TableMetadata {
  client CustomGPT5  // <-- Change this line
  prompt #"
    ...
  "#
}

function GenerateNormalizedTable(
  markdownTable: string,
  metadata: TableMetadata,
  userSchema: UserSchema
) -> string {
  client CustomGPT5  // <-- Change this line
  prompt #"
    ...
  "#
}
```

### 3. Replace the Client Name

Change `client CustomGPT5` to any of:
- `CustomGPT5Mini` - OpenAI GPT-5 Mini
- `CustomSonnet4` - Anthropic Claude Sonnet 4
- `CustomOpus4` - Anthropic Claude Opus 4
- `CustomHaiku` - Anthropic Claude Haiku 3.5

### 4. Regenerate the Client

```bash
baml-cli generate
```

### 5. Verify

Check that the new client is being used:
```python
from baml_client import b
print("BAML client updated!")
```

## Using Different Clients for Different Functions

You can use different models for analysis vs normalization:

```baml
// Fast analysis with Haiku
function AnalyzeTableStructure(...) -> TableMetadata {
  client CustomHaiku
  prompt #"..."#
}

// Detailed normalization with Sonnet
function GenerateNormalizedTable(...) -> string {
  client CustomSonnet4
  prompt #"..."#
}
```

This optimizes for speed during structure detection and accuracy during data extraction.

## Setting Up Other Providers (Advanced)

### Google Gemini

1. Uncomment in `baml_src/clients.baml`:
```baml
client<llm> CustomGemini {
  provider google-ai
  options {
    model "gemini-2.5-pro"
    api_key env.GOOGLE_API_KEY
  }
}
```

2. Set API key:
```bash
export GOOGLE_API_KEY=your_key_here
```

3. Use in functions:
```baml
function AnalyzeTableStructure(...) -> TableMetadata {
  client CustomGemini
  ...
}
```

### AWS Bedrock

1. Uncomment in `baml_src/clients.baml`:
```baml
client<llm> CustomBedrock {
  provider aws-bedrock
  options {
    model "anthropic.claude-sonnet-4-20250514-v1:0"
    region "us-east-1"
  }
}
```

2. Ensure AWS credentials are configured (AWS CLI)

3. Use in functions:
```baml
function AnalyzeTableStructure(...) -> TableMetadata {
  client CustomBedrock
  ...
}
```

## Cost Optimization Strategies

### Strategy 1: Tiered Processing

Use cheap models first, expensive for errors:

```baml
// Try with Haiku first
client<llm> FastFirst {
  provider fallback
  options {
    strategy [CustomHaiku, CustomSonnet4]
  }
}
```

### Strategy 2: Round Robin

Distribute load across providers:

```baml
client<llm> LoadBalanced {
  provider round-robin
  options {
    strategy [CustomGPT5Mini, CustomHaiku]
  }
}
```

### Strategy 3: Simple Tables = Cheap, Complex = Expensive

Check table complexity first, then choose model programmatically.

## Troubleshooting

### "API key not set" Error

**Problem:**
```
BamlError: LLM client 'CustomSonnet4' requires environment variable 'ANTHROPIC_API_KEY'
```

**Solution:**
```bash
# Set the correct API key for your chosen provider
export OPENAI_API_KEY=your_key    # For OpenAI
export ANTHROPIC_API_KEY=your_key # For Anthropic
export GOOGLE_API_KEY=your_key    # For Google
```

### Changes Not Taking Effect

**Problem:** Modified `table_analysis.baml` but still using old client

**Solution:**
```bash
# Always regenerate after changes
baml-cli generate

# Restart Jupyter kernel if using notebook
# (Kernel → Restart)
```

### Which Client is Currently Active?

Check `baml_src/table_analysis.baml` lines 36 and 54:
```bash
grep "client Custom" baml_src/table_analysis.baml
```

Output shows current configuration:
```
  client CustomGPT5
  client CustomGPT5
```

## Summary

✅ **Current default:** OpenAI GPT-5
✅ **Switch:** Edit `baml_src/table_analysis.baml` → change client names → `baml-cli generate`
✅ **Available:** GPT-5, GPT-5 Mini, Claude Sonnet 4, Claude Opus 4, Claude Haiku
✅ **Advanced:** Gemini, Bedrock (uncomment in `clients.baml`)

**For most users:** Stick with OpenAI GPT-5 (current default) - good balance of speed, cost, and accuracy.
