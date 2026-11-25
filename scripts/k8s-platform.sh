#!/usr/bin/env bash
# Cluster add-ons that Terraform doesn't manage (ADR 0011):
#   up   : Karpenter controller, NVIDIA device plugin, the gpu NodePool
#   down : remove every Karpenter-launched node, then the add-ons. Must run
#          BEFORE `terraform destroy`: Karpenter's nodes aren't in Terraform
#          state, and a node left running keeps billing and blocks the VPC
#          from being deleted.
# Used by scripts/up.sh, scripts/down.sh and the terraform workflow.
# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "$0")/_common.sh"

KARPENTER_VERSION=1.15.3
DEVICE_PLUGIN_VERSION=0.20.2
# KEDA 2.21's tested window is Kubernetes 1.34-1.36; the cluster runs 1.37.
# up() checks the operator and its metrics API are healthy (ADR 0002).
KEDA_VERSION=2.21.1
METRICS_SERVER_CHART_VERSION=3.14.0

command -v helm >/dev/null || { echo "missing: helm (brew install helm)"; exit 1; }

tf_init
out() { terraform -chdir="$DEMO_DIR" output -raw "$1" 2>/dev/null || true; }
CLUSTER=$(out cluster_name)
QUEUE=$(out karpenter_queue_name)
NODE_ROLE=$(out karpenter_node_role_name)
CLUSTER=${CLUSTER:-$PROJECT-demo}
NODE_ROLE=${NODE_ROLE:-$CLUSTER-karpenter-node}

cluster_exists() { aws eks describe-cluster --name "$CLUSTER" >/dev/null 2>&1; }
kubeconfig() { aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER" >/dev/null; }

up() {
  [[ -n "$QUEUE" ]] || { echo "No karpenter_queue_name output: run terraform apply first."; exit 1; }
  kubeconfig

  # Spot needs this service-linked role once per account; Karpenter can't
  # create it. "has been taken" means it already exists.
  if ! msg=$(aws iam create-service-linked-role --aws-service-name spot.amazonaws.com 2>&1); then
    grep -q "has been taken" <<<"$msg" || { echo "$msg"; exit 1; }
  fi

  echo "== Karpenter $KARPENTER_VERSION"
  # Stale public.ecr.aws credentials make anonymous chart pulls fail with 403.
  helm registry logout public.ecr.aws >/dev/null 2>&1 || true
  helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
    --version "$KARPENTER_VERSION" --namespace kube-system \
    -f "$ROOT/k8s/platform/karpenter-values.yaml" \
    --set "settings.clusterName=$CLUSTER" \
    --set "settings.interruptionQueue=$QUEUE" \
    --wait --timeout 5m

  echo "== NVIDIA device plugin $DEVICE_PLUGIN_VERSION"
  helm repo add nvdp https://nvidia.github.io/k8s-device-plugin --force-update >/dev/null
  helm upgrade --install nvdp nvdp/nvidia-device-plugin \
    --version "$DEVICE_PLUGIN_VERSION" --namespace kube-system \
    -f "$ROOT/k8s/platform/nvidia-device-plugin-values.yaml" \
    --wait --timeout 5m

  echo "== metrics-server chart $METRICS_SERVER_CHART_VERSION (kubectl top; CPU vs demand in Phase 3)"
  helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ --force-update >/dev/null
  helm upgrade --install metrics-server metrics-server/metrics-server \
    --version "$METRICS_SERVER_CHART_VERSION" --namespace kube-system \
    --wait --timeout 5m

  echo "== KEDA $KEDA_VERSION"
  helm repo add kedacore https://kedacore.github.io/charts --force-update >/dev/null
  helm upgrade --install keda kedacore/keda \
    --version "$KEDA_VERSION" --namespace keda --create-namespace \
    -f "$ROOT/k8s/platform/keda-values.yaml" \
    --wait --timeout 5m
  # KEDA serves scaling metrics through the Kubernetes external metrics API;
  # if that isn't Available, ScaledObjects silently never scale.
  kubectl wait apiservice/v1beta1.external.metrics.k8s.io --for=condition=Available --timeout=3m

  echo "== GPU NodePool"
  kubectl apply -f "$ROOT/k8s/karpenter/"
  kubectl wait ec2nodeclass/gpu --for=condition=Ready --timeout=3m
  kubectl wait nodepool/gpu --for=condition=Ready --timeout=3m
  kubectl get nodepool,ec2nodeclass
  echo
  echo "Platform ready. No GPU node exists until a pod asks for one: ./scripts/vllm-smoke.sh"
}

terminate_leftovers() {
  # Failsafe for when the controller is gone or stuck: any instance Karpenter
  # launched for this cluster that is still alive.
  local ids profiles
  # A failed check must stop the teardown loudly, never read as "none"
  # (incident #6).
  if ! ids=$(aws ec2 describe-instances \
    --filters "Name=tag:eks:eks-cluster-name,Values=$CLUSTER" "Name=tag-key,Values=karpenter.sh/nodepool" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text); then
    echo "ERROR: could not check for leftover GPU instances. Do NOT run terraform destroy until this succeeds."
    exit 1
  fi
  if [[ -n "$ids" && "$ids" != "None" ]]; then
    echo "Terminating leftover Karpenter instances: $ids"
    # shellcheck disable=SC2086
    aws ec2 terminate-instances --instance-ids $ids >/dev/null
    # shellcheck disable=SC2086
    aws ec2 wait instance-terminated --instance-ids $ids
  fi
  # Karpenter-made instance profiles still holding the node role would make
  # `terraform destroy` fail with DeleteConflict on that role.
  if ! profiles=$(aws iam list-instance-profiles-for-role --role-name "$NODE_ROLE" \
                    --query 'InstanceProfiles[].InstanceProfileName' --output text 2>&1); then
    # The role is already gone (e.g. destroy ran before): nothing to clean.
    grep -q NoSuchEntity <<<"$profiles" && return 0
    echo "ERROR: could not list instance profiles for $NODE_ROLE: $profiles"
    exit 1
  fi
  local p
  for p in $profiles; do
    [[ "$p" == "None" ]] && continue
    echo "Removing leftover instance profile $p"
    aws iam remove-role-from-instance-profile --instance-profile-name "$p" --role-name "$NODE_ROLE"
    aws iam delete-instance-profile --instance-profile-name "$p"
  done
}

down() {
  if cluster_exists; then
    kubeconfig
    echo "== Removing GPU workloads and Karpenter nodes"
    # The ScaledObject first, or KEDA would scale vLLM straight back up.
    if kubectl get crd scaledobjects.keda.sh >/dev/null 2>&1; then
      kubectl delete scaledobjects --all -A --wait=true --timeout=2m || true
    fi
    kubectl delete -f "$ROOT/k8s/vllm/deployment.yaml" --ignore-not-found --wait=true --timeout=2m || true
    if kubectl get crd nodepools.karpenter.sh >/dev/null 2>&1; then
      kubectl delete nodepool --all --wait=true --timeout=10m || true
      for _ in $(seq 1 60); do
        [[ -z "$(kubectl get nodeclaims -o name 2>/dev/null)" ]] && break
        sleep 10
      done
      kubectl delete ec2nodeclass --all --wait=true --timeout=5m || true
    fi
    echo "== Removing add-ons"
    helm uninstall keda -n keda --wait 2>/dev/null || true
    helm uninstall metrics-server -n kube-system --wait 2>/dev/null || true
    helm uninstall nvdp -n kube-system --wait 2>/dev/null || true
    helm uninstall karpenter -n kube-system --wait 2>/dev/null || true
  else
    echo "Cluster $CLUSTER not found; skipping Kubernetes cleanup."
  fi
  echo "== Checking for leftovers outside Kubernetes"
  terminate_leftovers
  echo "Platform removed. Safe to run terraform destroy."
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  *) echo "usage: $0 up|down"; exit 2 ;;
esac
