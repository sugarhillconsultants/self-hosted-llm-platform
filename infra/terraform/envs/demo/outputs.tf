output "cluster_name" {
  value = module.eks.cluster_name
}

output "region" {
  value = var.region
}

output "gateway_repository_url" {
  value = module.ecr_gateway.repository_url
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
