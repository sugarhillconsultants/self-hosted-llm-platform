#!/usr/bin/env bash
set -euo pipefail
kind delete cluster --name llm-local
echo "Deleted. Credentials in local/.env.local are kept for next time."
