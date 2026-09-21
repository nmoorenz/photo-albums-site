# Key pair CloudFront uses to check the signed cookies the auth Lambda issues
# for /photos/*.
resource "tls_private_key" "cookie_signing" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "aws_cloudfront_public_key" "cookie_signing" {
  name        = "${var.project_tag}-cookie-key"
  comment     = "Verifies signed cookies issued by the auth callback Lambda"
  encoded_key = tls_private_key.cookie_signing.public_key_pem
}

resource "aws_cloudfront_key_group" "cookie_signing" {
  name    = "${var.project_tag}-cookie-key-group"
  comment = "Trusted key group for /photos/* signed-cookie access"
  items   = [aws_cloudfront_public_key.cookie_signing.id]
}

# The private key (for signing cookies) and the Cognito app client secret
# (for the code-for-token exchange) are SecureStrings in SSM, not Lambda
# environment variables.
resource "aws_ssm_parameter" "cookie_signing_private_key" {
  name  = "/${var.project_tag}/cloudfront-private-key"
  type  = "SecureString"
  value = tls_private_key.cookie_signing.private_key_pem
  tags  = { Project = var.project_tag }
}

resource "aws_ssm_parameter" "cognito_client_secret" {
  name  = "/${var.project_tag}/cognito-client-secret"
  type  = "SecureString"
  value = aws_cognito_user_pool_client.albums.client_secret
  tags  = { Project = var.project_tag }
}
