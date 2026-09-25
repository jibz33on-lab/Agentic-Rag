# The public deployment is live.
#
# CloudFront serves the frontend from S3 and routes /query and /health to the
# ALB, so the browser sees one origin and api.py needs no CORS middleware.
# AWS removed the account-level CloudFront hold on 2026-09-25 (support case
# 179007379100349); before that, cloudfront_enabled had to be false because
# CreateDistribution was refused outright. See var.cloudfront_enabled.
#
# The ALB stays up because a distribution needs a stable public origin. That is
# the deliberate exception to the ephemeral-ALB argument in variables.tf, which
# still holds for the case it describes: an ALB serving only a laptop.
#
# Cost: the ALB is ~$16.20/month. CloudFront has no hourly charge and this
# traffic sits inside the free tier; the bucket holds ~415 KB.
#
# To tear the public surface down again:
#   terraform apply -var="alb_enabled=false" -var="cloudfront_enabled=false"
# The ALB teardown is two applies -- see var.keep_alb_sg.
alb_enabled        = true
cloudfront_enabled = true
