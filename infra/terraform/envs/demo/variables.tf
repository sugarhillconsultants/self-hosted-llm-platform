variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "self-hosted-llm-platform"
}

variable "kubernetes_version" {
  description = "EKS version. Use AWS's current default: aws eks describe-cluster-versions --default-only"
  type        = string
  validation {
    condition     = can(regex("^1\\.[0-9]{2}$", var.kubernetes_version))
    error_message = "Set kubernetes_version in terraform.tfvars to a version like \"1.34\"."
  }
}

variable "system_node_instance_type" {
  description = "CPU nodes for the gateway and cluster add-ons. GPUs arrive in Phase 2."
  type        = string
  default     = "t3.medium"
}

variable "api_allowed_cidrs" {
  description = "Who can reach the Kubernetes API endpoint. GitHub-hosted runners have no fixed IPs, so CI needs 0.0.0.0/0; access still requires IAM auth via an access entry."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
