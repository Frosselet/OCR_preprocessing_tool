// Learn more about clients at https://docs.boundaryml.com/docs/snippets/clients/overview

// Using the new OpenAI Responses API for enhanced formatting
client<llm> CustomGPT5 {
  provider openai-responses
  options {
    model "gpt-5"
    api_key env.OPENAI_API_KEY
  }
}

client<llm> CustomGPT5Mini {
  provider openai-responses
  retry_policy Exponential
  options {
    model "gpt-5-mini"
    api_key env.OPENAI_API_KEY
  }
}

// GPT-4o models for production use
client<llm> CustomGPT4o {
  provider openai
  options {
    model "gpt-4o"
    api_key env.OPENAI_API_KEY
  }
}

// O-series reasoning models
// Note: Reasoning models use max_completion_tokens, not max_tokens
// Optional: reasoning_effort can be "low", "medium", or "high"

// O3 - Full reasoning model for complex multi-step problems
client<llm> CustomO3 {
  provider openai
  options {
    model "o3"
    api_key env.OPENAI_API_KEY
    max_completion_tokens 32000
  }
}

// O3-mini - Smaller, faster reasoning model
client<llm> CustomO3Mini {
  provider openai
  options {
    model "o3-mini"
    api_key env.OPENAI_API_KEY
  }
}

// O4-mini - Latest small reasoning model (successor to o3-mini)
// Supports up to 100k output tokens, 200k context window
client<llm> CustomO4Mini {
  provider openai
  options {
    model "o4-mini"
    api_key env.OPENAI_API_KEY
  }
}

client<llm> CustomGPT4oMini {
  provider openai
  retry_policy Exponential
  options {
    model "gpt-4o-mini"
    api_key env.OPENAI_API_KEY
  }
}

// Openai with chat completion
client<llm> CustomGPT5Chat {
  provider openai
  options {
    model "gpt-5"
    api_key env.OPENAI_API_KEY
  }
}

// Latest Anthropic Claude 4 models
client<llm> CustomOpus4 {
  provider anthropic
  options {
    model "claude-opus-4-1-20250805"
    api_key env.ANTHROPIC_API_KEY
  }
}

client<llm> CustomSonnet4 {
  provider anthropic
  options {
    model "claude-sonnet-4-20250514"
    api_key env.ANTHROPIC_API_KEY
  }
}

client<llm> CustomHaiku {
  provider anthropic
  retry_policy Constant
  options {
    model "claude-3-5-haiku-20241022"
    api_key env.ANTHROPIC_API_KEY
  }
}

// Example Google AI client (uncomment to use)
// client<llm> CustomGemini {
//   provider google-ai
//   options {
//     model "gemini-2.5-pro"
//     api_key env.GOOGLE_API_KEY
//   }
// }

// Example AWS Bedrock client (uncomment to use)
// client<llm> CustomBedrock {
//   provider aws-bedrock
//   options {
//     model "anthropic.claude-sonnet-4-20250514-v1:0"
//     region "us-east-1"
//     // AWS credentials are auto-detected from env vars
//   }
// }

// Example Azure OpenAI client (uncomment to use)
// client<llm> CustomAzure {
//   provider azure-openai
//   options {
//     model "gpt-5"
//     api_key env.AZURE_OPENAI_API_KEY
//     base_url "https://MY_RESOURCE_NAME.openai.azure.com/openai/deployments/MY_DEPLOYMENT_ID"
//     api_version "2024-10-01-preview"
//   }
// }

// Example Vertex AI client (uncomment to use)
// client<llm> CustomVertex {
//   provider vertex-ai
//   options {
//     model "gemini-2.5-pro"
//     location "us-central1"
//     // Uses Google Cloud Application Default Credentials
//   }
// }

// Example Ollama client for local models (uncomment to use)
// client<llm> CustomOllama {
//   provider openai-generic
//   options {
//     base_url "http://localhost:11434/v1"
//     model "llama4"
//     default_role "user" // Most local models prefer the user role
//     // No API key needed for local Ollama
//   }
// }

// https://docs.boundaryml.com/docs/snippets/clients/round-robin
client<llm> CustomFast {
  provider round-robin
  options {
    // This will alternate between the two clients
    strategy [CustomGPT5Mini, CustomHaiku]
  }
}

// https://docs.boundaryml.com/docs/snippets/clients/fallback
client<llm> OpenaiFallback {
  provider fallback
  options {
    // This will try the clients in order until one succeeds
    strategy [CustomGPT5Mini, CustomGPT5]
  }
}

// https://docs.boundaryml.com/docs/snippets/clients/retry
retry_policy Constant {
  max_retries 3
  strategy {
    type constant_delay
    delay_ms 200
  }
}

retry_policy Exponential {
  max_retries 2
  strategy {
    type exponential_backoff
    delay_ms 300
    multiplier 1.5
    max_delay_ms 10000
  }
}