# Image repository for the gateway. Immutable tags: a tag, once pushed, can
# never point at different bytes (log-anomaly-platform incident #5 was a
# mutable :latest silently not rolling out).

variable "name" {
  type = string
}

variable "keep_last_images" {
  type    = number
  default = 20
}

resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  # Demo environment: `destroy` must not be blocked by leftover images.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last ${var.keep_last_images} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.keep_last_images
      }
      action = { type = "expire" }
    }]
  })
}

output "repository_url" {
  value = aws_ecr_repository.this.repository_url
}
