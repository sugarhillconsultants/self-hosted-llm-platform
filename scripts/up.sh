#!/usr/bin/env bash
# Create the demo environment from your Mac (the same thing the workflow's
# "apply" does from CI). Costs ~$0.23/hour until ./scripts/down.sh.
# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "$0")/_common.sh"

if grep -q 'SET-ME' "$DEMO_DIR/terraform.tfvars"; then
  echo "Set kubernetes_version in infra/terraform/envs/demo/terraform.tfvars first:"
  echo "  aws eks describe-cluster-versions --default-only --query 'clusterVersions[0].clusterVersion' --output text"
  exit 1
fi

start=$(date +%s)
tf_init
terraform -chdir="$DEMO_DIR" apply -input=false
aws eks update-kubeconfig --region "$AWS_REGION" --name "$(terraform -chdir="$DEMO_DIR" output -raw cluster_name)"
kubectl get nodes -o wide
echo
echo "Up in $(( ($(date +%s) - start) / 60 )) min. Now costing ~\$0.23/hour: run ./scripts/down.sh when finished."
