# The ALB stays up.
#
# variables.tf defaults alb_enabled to false and argues for ephemeral
# infrastructure: ~$16.20/month forever is a poor trade for a project that is
# usually not being looked at. That argument holds for an ALB serving a laptop.
#
# It does not hold once CloudFront is in front of it. A distribution needs a
# stable public origin, and the ALB is it -- so the application having a public
# HTTPS URL at all depends on this being true. The default is left alone
# because the reasoning behind it is still correct in the case it describes;
# this file records the deliberate exception.
#
# Tearing the whole thing down is still one flag:
#   terraform apply -var="alb_enabled=false"
alb_enabled = true
