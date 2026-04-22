# ollama_client.py — REMOVED
#
# This file was an early prototype that used the `ollama` Python SDK
# (pip package) and hardcoded `DEFAULT_MODEL = "llama3"`.
#
# The current pipeline uses `service/llm.py` which calls the Ollama HTTP
# API directly (requests.post to OLLAMA_URL) with the model specified via
# the OLLAMA_ENTITY_MODEL environment variable. The `ollama` SDK is not
# installed in the Docker image.
#
# DO NOT import this file from anywhere in the pipeline.