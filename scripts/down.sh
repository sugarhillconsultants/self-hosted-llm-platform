#!/usr/bin/env bash
# Remove Karpenter nodes and add-ons, destroy the demo environment, then
# check nothing billable is left behind.
# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "$0")/_common.sh"

# Karpenter's GPU nodes aren't in Terraform state: remove them first, or they
# keep billing and block the VPC from being deleted.
"$ROOT/scripts/k8s-platform.sh" down
tf_init
terraform -chdir="$DEMO_DIR" destroy -input=false
echo
"$ROOT/scripts/whats-running.sh"
