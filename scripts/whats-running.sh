#!/usr/bin/env bash
# List anything in the region that bills by the hour. Checks the whole region,
# not just Terraform state: a leaked load balancer created by Kubernetes isn't
# in state.
#
# Exit codes: 0 = verified nothing billable, 1 = billable resources found,
# 2 = could not check. A check that fails is never reported as "none"
# (incident #6: an expired SSO token once produced a false all-clear).
set -uo pipefail
export AWS_REGION="${AWS_REGION:-us-east-1}"
found=0
failed=0

if ! who=$(aws sts get-caller-identity --query Arn --output text 2>&1); then
  echo "Cannot check: AWS credentials are not working."
  echo "  $who"
  echo "Run: aws sso login --profile \"${AWS_PROFILE:-llm-platform}\""
  exit 2
fi
echo "Checking $AWS_REGION as ${who##*/}"
echo

check() { # $1 label, then the aws command
  local label=$1 out
  shift
  if ! out=$("$@" 2>&1); then
    echo "?? $label: CHECK FAILED"
    while IFS= read -r line; do echo "     $line"; done <<< "$out"
    failed=1
    return
  fi
  if [[ -n "$out" && "$out" != "None" ]]; then
    echo "!! $label:"
    while IFS= read -r line; do echo "     $line"; done <<< "$out"
    found=1
  else
    echo "ok $label: none"
  fi
}

check "EKS clusters" aws eks list-clusters --query 'clusters[]' --output text
check "NAT gateways" aws ec2 describe-nat-gateways --filter Name=state,Values=pending,available \
  --query 'NatGateways[].NatGatewayId' --output text
check "Running EC2 instances" aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=pending,running \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType]' --output text
check "Load balancers" aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
check "Unattached EBS volumes" aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[].[VolumeId,Size]' --output text
check "Unassociated Elastic IPs" aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].PublicIp' --output text

echo
if (( found )); then
  echo "Billable resources found in $AWS_REGION (see !! above)."
  exit 1
fi
if (( failed )); then
  echo "Could not verify $AWS_REGION: some checks failed (see ?? above). This is NOT an all-clear."
  exit 2
fi
echo "Verified: nothing billable by the hour in $AWS_REGION."
