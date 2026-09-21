resource "aws_s3_bucket" "albums" {
  bucket = var.bucket_name
  tags   = { Project = var.project_tag }
}

resource "aws_s3_bucket_public_access_block" "albums" {
  bucket                  = aws_s3_bucket.albums.id
  block_public_acls       = true
  block_public_policy     = false # the bucket policy below grants CloudFront, not the public
  ignore_public_acls      = true
  restrict_public_buckets = false
}

resource "aws_s3_bucket_versioning" "albums" {
  bucket = aws_s3_bucket.albums.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_cloudfront_origin_access_control" "albums" {
  name                              = "${var.project_tag}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Bucket contents are readable only through CloudFront. "photos/*" is further
# restricted at the CloudFront behaviour level by signed cookies, and
# "comments/*" has no CloudFront behaviour at all -- only comments-api
# touches it.
resource "aws_s3_bucket_policy" "albums" {
  bucket = aws_s3_bucket.albums.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontServicePrincipal"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.albums.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.albums.arn
        }
      }
    }]
  })
}

# Created only if absent; album_sync.py owns the contents from then on.
resource "aws_s3_object" "manifest_bootstrap" {
  bucket = aws_s3_bucket.albums.id
  key    = "photos/manifest.json"
  content = jsonencode({
    generated = "1970-01-01T00:00:00Z"
    albums    = []
  })
  content_type  = "application/json"
  cache_control = "no-cache"

  lifecycle {
    ignore_changes = [content, content_type, cache_control, etag]
  }
}
