output "cluster_name" {
  description = "The ECS cluster both services run on."
  value       = aws_ecs_cluster.main.name
}

output "api_security_group_id" {
  description = "The API task security group. Step 4 adds the ALB's ingress rule here."
  value       = aws_security_group.api.id
}

output "vpc_id" {
  value = data.aws_vpc.default.id
}

output "subnet_ids" {
  description = "The six default subnets, one per AZ."
  value       = data.aws_subnets.default.ids
}

output "alb_dns_name" {
  description = "The stable hostname the ALB exists to provide. Null while alb_enabled is false."
  value       = var.alb_enabled ? aws_lb.main[0].dns_name : null
}

output "alb_url" {
  description = "Ready to curl. HTTP only until step 15."
  value       = var.alb_enabled ? "http://${aws_lb.main[0].dns_name}" : null
}

output "frontend_bucket" {
  description = "The bucket holding the built frontend. Deploy with `aws s3 sync`."
  value       = aws_s3_bucket.frontend.bucket
}

output "cloudfront_distribution_id" {
  description = "Needed to invalidate the cache after deploying a new build. Null while cloudfront_enabled is false."
  value       = var.cloudfront_enabled ? aws_cloudfront_distribution.main[0].id : null
}

output "public_url" {
  description = "The application. HTTPS, on CloudFront's own certificate. Null until the account is verified for CloudFront."
  value       = var.cloudfront_enabled ? "https://${aws_cloudfront_distribution.main[0].domain_name}" : null
}
