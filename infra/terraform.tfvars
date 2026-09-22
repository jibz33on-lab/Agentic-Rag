# Both halves of the public URL are off while the account waits on AWS.
#
# CloudFront is off because AWS refuses to create it: the account is not yet
# verified for CloudFront resources, and only AWS Support can change that. See
# var.cloudfront_enabled.
#
# The ALB is off because CloudFront is. An ALB is ~$16.20/month and exists here
# only to be a CDN origin -- with no distribution to serve traffic, an ALB is a
# bill with nothing on the other end. variables.tf already argues for ephemeral
# infrastructure; this is exactly the case it describes.
#
# To finish the deployment once support confirms verification:
#
#   terraform apply -var="alb_enabled=true" -var="cloudfront_enabled=true"
#
# and then set both to true here so the setting persists.
alb_enabled        = false
cloudfront_enabled = false
