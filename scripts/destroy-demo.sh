#!/usr/bin/env bash
# Destroy envs/demo in stages, so a leaked network interface can't block it
# (incident #9: an orphaned VPC CNI interface, "aws-K8S-<instance>", held a
# subnet and a security group, and `terraform destroy` retried then failed).
#
#   1. destroy ONLY the system node group resource, so its instances
#      terminate and their interfaces detach. Not module.eks or the node
#      group module: both own security groups the leaked interface holds
#      (incident #9b, the first version of this script made that mistake).
#   2. delete any aws-K8S-* interfaces left in the project VPC
#   3. destroy everything else; if a DependencyViolation still happens,
#      clean up again and retry once
#
# Run scripts/k8s-platform.sh down first (down.sh and the workflow do).
# Pass --auto-approve to skip Terraform's prompts (CI).
# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "$0")/_common.sh"

AUTO=()
[[ "${1:-}" == "--auto-approve" ]] && AUTO=(-auto-approve)
VPC_NAME="$PROJECT-demo"

cleanup_cni_enis() {
  local vpc ids busy
  if ! vpc=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=$VPC_NAME" \
               --query 'Vpcs[0].VpcId' --output text); then
    echo "ERROR: could not look up VPC $VPC_NAME"; exit 1
  fi
  [[ "$vpc" == "None" || -z "$vpc" ]] && { echo "VPC $VPC_NAME already gone."; return 0; }

  # Interfaces detach a little after their instance terminates; wait for them.
  for _ in $(seq 1 18); do
    busy=$(aws ec2 describe-network-interfaces \
      --filters "Name=vpc-id,Values=$vpc" "Name=description,Values=aws-K8S-*" "Name=status,Values=in-use,attaching,detaching" \
      --query 'NetworkInterfaces[].NetworkInterfaceId' --output text) || { echo "ERROR: could not list interfaces"; exit 1; }
    [[ -z "$busy" || "$busy" == "None" ]] && break
    echo "Waiting for CNI interfaces to detach: $busy"
    sleep "${SLEEP:-10}"
  done

  ids=$(aws ec2 describe-network-interfaces \
    --filters "Name=vpc-id,Values=$vpc" "Name=description,Values=aws-K8S-*" "Name=status,Values=available" \
    --query 'NetworkInterfaces[].NetworkInterfaceId' --output text) || { echo "ERROR: could not list interfaces"; exit 1; }
  if [[ -z "$ids" || "$ids" == "None" ]]; then
    echo "No leaked CNI interfaces in $vpc."
    return 0
  fi
  local eni
  for eni in $ids; do
    echo "Deleting leaked CNI interface $eni"
    aws ec2 delete-network-interface --network-interface-id "$eni"
  done
}

NODE_GROUP='module.eks.module.eks_managed_node_group["system"].aws_eks_node_group.this[0]'

tf_init
echo "== 1/3 Destroying the system node group (instances only)"
terraform -chdir="$DEMO_DIR" destroy -input=false -no-color "${AUTO[@]}" -target="$NODE_GROUP"
echo "== 2/3 Removing leaked VPC CNI network interfaces"
cleanup_cni_enis
echo "== 3/3 Destroying everything else"
if ! terraform -chdir="$DEMO_DIR" destroy -input=false -no-color "${AUTO[@]}"; then
  echo "== Destroy failed; removing leaked interfaces again and retrying once"
  cleanup_cni_enis
  terraform -chdir="$DEMO_DIR" destroy -input=false -no-color "${AUTO[@]}"
fi
