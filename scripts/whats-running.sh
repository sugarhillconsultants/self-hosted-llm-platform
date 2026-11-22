#!/usr/bin/env bash
# List anything in the region that bills by the hour. Exit 1 if any is found,
# so it can gate "I'm done for the day". Checks the whole region, not just
# Terraform state: a leaked load balancer created by Kubernetes isn't in state.
set -uo pipefail
export AWS_REGION="${AWS_REGION:-us-east-1}"
found=0

check() { # $1 label, $2 output
  if [[ -n "$2" && "$2" != "None" ]]; then
    echo "!! $1:"; while IFS= read -r line; do echo "     $line"; done <<< "$2"; found=1
  else
    echo "ok $1: none"
  fi
}

check "EKS clusters" "$(aws eks list-clusters --query 'clusters[]' --output text)"
check "NAT gateways" "$(aws ec2 describe-nat-gateways --filter Name=state,Values=pending,available \
  --query 'NatGateways[].NatGatewayId' --output text)"
check "Running EC2 instances" "$(aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=pending,running \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType]' --output text)"
check "Load balancers" "$(aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text)"
check "Unattached EBS volumes" "$(aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[].[VolumeId,Size]' --output text)"
check "Unassociated Elastic IPs" "$(aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].PublicIp' --output text)"

echo
if (( found )); then
  echo "Billable resources found in $AWS_REGION (see !! above)."
  exit 1
fi
echo "Nothing billable by the hour in $AWS_REGION."
