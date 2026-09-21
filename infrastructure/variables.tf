# Values that identify a particular deployment have no defaults: set them in
# terraform.tfvars, which is gitignored. See terraform.tfvars.example.

variable "aws_profile" {
  description = "AWS CLI profile to use"
  type        = string
  default     = "default"
}

variable "aws_region" {
  description = "Region for S3, Cognito and the Lambdas. Must support Lambda function URLs -- ap-southeast-6 does not."
  type        = string
  default     = "ap-southeast-2"
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
