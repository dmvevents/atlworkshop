#!/bin/bash
# Test script for Qwen2.5-Coder-7B-Instruct on Dynamo

SERVICE_URL="http://qwen-coder-frontend.workshop.svc.cluster.local:8000"

echo "Testing Qwen2.5-Coder-7B-Instruct deployment..."
echo ""

# Test with a coding question
curl -s -X POST "$SERVICE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [
      {
        "role": "user",
        "content": "Write a Python function to compute the Fibonacci sequence using dynamic programming."
      }
    ],
    "max_tokens": 500,
    "temperature": 0.7
  }' | jq -r '.choices[0].message.content'

echo ""
echo "---"
echo ""
echo "Model deployment successful! Access the API at:"
echo "  Service: qwen-coder-frontend.workshop.svc.cluster.local:8000"
echo "  Endpoint: /v1/chat/completions"
