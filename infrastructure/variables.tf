# Deployment-specific values have NO default: an incomplete config fails
# before anything is created. They come from .env via scripts/tf.py, which
# exports them as TF_VAR_*.
#
# Non-identifying values keep defaults and live in terraform.tfvars, which is
# committed.

variable "aws_profile" {
  description = "AWS CLI profile to deploy with. .env: AWS_PROFILE"
  type        = string
}

variable "aws_region" {
  description = "Region for S3 / Cognito / Lambda"
  type        = string
  default     = "ap-southeast-6"
}

variable "bucket_name" {
  description = "S3 bucket holding the static site, the private photos and the comments. Must be globally unique."
  type        = string
}

variable "domain_name" {
  description = "Custom domain the site is served on"
  type        = string
}

variable "project_tag" {
  description = "Tag and name prefix for every resource"
  type        = string
  default     = "photo-albums"
}

variable "cognito_domain_prefix" {
  description = "Prefix for the Cognito Hosted UI domain (<prefix>.auth.<region>.amazoncognito.com). Must be globally unique."
  type        = string
}
