# Account-wide monthly cost budget with email alerts. Created in bootstrap,
# before anything that costs money exists.

variable "name" {
  type = string
}

variable "limit_usd" {
  type = number
}

variable "alert_emails" {
  type = list(string)
  validation {
    condition     = length(var.alert_emails) > 0
    error_message = "At least one alert email is required."
  }
}

variable "actual_thresholds_percent" {
  description = "Alert when actual spend crosses these percentages of the limit."
  type        = list(number)
  default     = [50, 80, 100]
}

resource "aws_budgets_budget" "monthly" {
  name         = var.name
  budget_type  = "COST"
  limit_amount = tostring(var.limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.actual_thresholds_percent
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.alert_emails
    }
  }

  # Early warning: AWS forecasts the month will exceed the limit. Fires days
  # before an ACTUAL alert would, which is what matters for a cluster left on.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.alert_emails
  }
}

output "name" {
  value = aws_budgets_budget.monthly.name
}
