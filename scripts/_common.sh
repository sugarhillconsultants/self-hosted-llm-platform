# shellcheck shell=bash
# Shared by up.sh / down.sh. Sourced, not executed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="$ROOT/infra/terraform/envs/demo"
PROJECT=self-hosted-llm-platform
export AWS_REGION="${AWS_REGION:-us-east-1}"

for tool in aws terraform kubectl; do
  command -v "$tool" >/dev/null || { echo "missing: $tool"; exit 1; }
done

if ! ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null); then
  echo "AWS credentials not working. Run: export AWS_PROFILE=llm-platform && aws sso login"
  exit 1
fi
STATE_BUCKET="$PROJECT-tfstate-$ACCOUNT"

tf_init() {
  terraform -chdir="$DEMO_DIR" init -input=false -reconfigure \
    -backend-config="bucket=$STATE_BUCKET" >/dev/null
}
