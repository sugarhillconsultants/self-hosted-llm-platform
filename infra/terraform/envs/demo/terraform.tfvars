# Set to AWS's current default EKS version before the first apply:
#   aws eks describe-cluster-versions --default-only \
#     --query 'clusterVersions[0].clusterVersion' --output text
kubernetes_version = "1.37"
