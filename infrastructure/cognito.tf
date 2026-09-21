resource "aws_cognito_user_pool" "albums" {
  name = "${var.project_tag}-users"

  # Every account is created by hand (Cognito console or `aws cognito-idp
  # admin-create-user`). There is no public sign-up page.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  # Shown as the comment author. Set it when creating each user.
  schema {
    name                = "name"
    attribute_data_type = "String"
    required            = false
    mutable             = true
    string_attribute_constraints {
      min_length = 1
      max_length = 100
    }
  }

  tags = { Project = var.project_tag }
}

resource "aws_cognito_user_pool_client" "albums" {
  name         = "${var.project_tag}-client"
  user_pool_id = aws_cognito_user_pool.albums.id

  generate_secret = true

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = ["https://${var.domain_name}/auth/callback"]
  logout_urls   = ["https://${var.domain_name}/login.html"]

  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]

  id_token_validity      = 12
  access_token_validity  = 12
  refresh_token_validity = 30
  token_validity_units {
    id_token      = "hours"
    access_token  = "hours"
    refresh_token = "days"
  }
}

resource "aws_cognito_user_pool_domain" "albums" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.albums.id
}

# admin can delete anyone's comment. Anyone signed in and not in the group is
# a viewer: they can read every album and post and delete their own comments.
# Membership is managed by hand in the Cognito console; comments-api reads
# `cognito:groups` from the ID token.
resource "aws_cognito_user_group" "admin" {
  name         = "admin"
  user_pool_id = aws_cognito_user_pool.albums.id
  description  = "Can delete any comment."
  precedence   = 1
}
