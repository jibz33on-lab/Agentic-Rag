# The frontend: a private S3 bucket holding the built React app, and one
# CloudFront distribution that serves it and routes the API paths to the ALB.
#
# Why a CDN for a single-user project, when the ALB alone could serve traffic:
# it is the cheapest way to get HTTPS and a single origin at once.
#
#   - HTTPS. ACM will not issue a certificate for an *.elb.amazonaws.com name,
#     so TLS on the ALB needs a domain we do not have. CloudFront supplies a
#     certificate on its own *.cloudfront.net name for nothing.
#   - One origin. The browser talks only to the distribution, so /query is a
#     same-origin request and no CORS middleware is needed in api.py. The
#     frontend fetches relative paths and holds no hostname at all -- see
#     agentic-rag-ui/docs/superpowers/specs/2026-09-22-frontend-design.md.
#
# Cost: no hourly charge. CloudFront bills per request and per GB out, and the
# free tier (1 TB out, 10M requests/month) is far beyond one user. The bucket
# holds ~500 KB. The ALB remains the only meaningful ongoing cost here.

locals {
  # Bucket names are globally unique across all of AWS, so the account id is
  # appended rather than hoping "basic-rag-ui" is free.
  frontend_bucket_name = "basic-rag-ui-${data.aws_caller_identity.current.account_id}"

  # Everything the API owns. Listed once and used for both the cache behaviours
  # below and the documentation above them -- two lists that can disagree is a
  # routing bug that looks like a frontend bug.
  api_paths = ["/query", "/health"]
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# The bucket. Private in every way S3 offers.
#
# No website hosting, no public read, no ACLs. CloudFront reaches it with an
# Origin Access Control identity and nothing else can reach it at all, which is
# why the SPA fallback below is a CloudFront error response rather than S3's
# website-hosting error document -- that feature requires a public bucket.
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "frontend" {
  bucket = local.frontend_bucket_name
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ---------------------------------------------------------------------------
# How CloudFront proves who it is to S3.
#
# OAC, not the older Origin Access Identity: it signs requests with SigV4 and
# is what AWS documents for new distributions.
# ---------------------------------------------------------------------------
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "basic-rag-ui-oac"
  description                       = "CloudFront -> the frontend bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# The bucket trusts one distribution, named by ARN. Without the SourceArn
# condition any CloudFront distribution in any account could read the bucket.
data "aws_iam_policy_document" "frontend" {
  count = var.cloudfront_enabled ? 1 : 0

  statement {
    sid       = "AllowCloudFrontRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.main[0].arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  count = var.cloudfront_enabled ? 1 : 0

  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend[0].json
}

# ---------------------------------------------------------------------------
# Managed policies, read by name rather than pasted as UUIDs.
#
# A wrong UUID fails at apply time with an opaque message; a wrong name fails
# in the plan saying it could not be found.
# ---------------------------------------------------------------------------
data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

# Forwards everything the viewer sent except Host. The ALB has no host-based
# rules, and sending it the CloudFront hostname would be meaningless to it.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# ---------------------------------------------------------------------------
# The distribution: the only thing a browser talks to.
#
# Default behaviour serves the app from S3. /query and /health are routed to
# the ALB, which is what makes them same-origin as the page.
# ---------------------------------------------------------------------------
resource "aws_cloudfront_distribution" "main" {
  count = var.cloudfront_enabled ? 1 : 0

  enabled             = true
  comment             = "basic-rag: frontend from S3, API from the ALB"
  default_root_object = "index.html"

  # US, Canada and Europe only. The cheapest class, and this has one user.
  price_class = "PriceClass_100"

  origin {
    origin_id                = "s3-frontend"
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # The ALB origin exists only while the ALB does. With alb_enabled = false
  # there is no load balancer to name, and a distribution cannot hold an origin
  # pointing at nothing -- so the API behaviours below are conditional too, and
  # the site then serves the frontend alone.
  dynamic "origin" {
    for_each = var.alb_enabled ? [1] : []

    content {
      origin_id   = "alb-api"
      domain_name = aws_lb.main[0].dns_name

      custom_origin_config {
        http_port  = 80
        https_port = 443
        # HTTP, because the ALB has no certificate -- ACM will not issue one for
        # an *.elb.amazonaws.com name. The viewer's connection to CloudFront is
        # HTTPS; this last hop is inside AWS's network between CloudFront and
        # the ALB. Terminating TLS at the ALB is a domain-name problem, not a
        # CloudFront one, and is the natural next step if this ever needs one.
        origin_protocol_policy = "http-only"
        origin_ssl_protocols   = ["TLSv1.2"]

        # An answer takes a recorded P50 of 5.10s and the tail is longer.
        # CloudFront's default is 30s; 60 is the maximum without a quota
        # increase and costs nothing when unused.
        origin_read_timeout      = 60
        origin_keepalive_timeout = 5
      }
    }
  }

  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_optimized.id
  }

  # One behaviour per API path. Both are uncached and forward the whole request.
  dynamic "ordered_cache_behavior" {
    for_each = var.alb_enabled ? local.api_paths : []

    content {
      path_pattern           = ordered_cache_behavior.value
      target_origin_id       = "alb-api"
      viewer_protocol_policy = "redirect-to-https"

      # POST and its friends, because /query is a POST. A behaviour that
      # allowed only GET would answer 405 before the request left CloudFront.
      allowed_methods = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods  = ["GET", "HEAD"]
      compress        = true

      # Caching disabled, not merely short. Two people asking the same question
      # must both reach the model; a cached answer would also cache its
      # request_id, which exists to identify one request.
      cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    }
  }

  # The SPA fallback. S3 answers 403 for a key that does not exist (403 rather
  # than 404, because the bucket is private and listing is denied), so both are
  # mapped to the app's own entry point with a 200. Without this, refreshing on
  # any path but / would show an XML access-denied document.
  #
  # ONLY 403, and deliberately not 404. A custom error response is
  # distribution-wide -- CloudFront offers no way to scope one to a behaviour --
  # so mapping 404 here would also rewrite a genuine 404 from FastAPI into
  # index.html with a 200, and the frontend would report a malformed response
  # instead of the error the API actually sent.
  #
  # 403 alone is enough, because the bucket policy grants s3:GetObject and not
  # s3:ListBucket: S3 answers a missing key with AccessDenied rather than
  # NoSuchKey, so every SPA route arrives here as a 403 and none as a 404.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # The certificate for *.cloudfront.net, supplied by AWS at no cost. A custom
  # domain would replace this with an ACM certificate in us-east-1.
  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }
}
