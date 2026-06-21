output "ec2_public_ip" {
  value = aws_instance.app.public_ip
}

output "fastapi_url" {
  value = "http://${aws_instance.app.public_ip}:8000"
}

output "streamlit_url" {
  value = "http://${aws_instance.app.public_ip}:8501"
}

output "airflow_url" {
  value = "http://${aws_instance.app.public_ip}:8080"
}

output "s3_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "rds_endpoint" {
  value = var.enable_rds ? aws_db_instance.postgres[0].address : "(RDS disabled — enable_rds=false)"
}

output "ec2_iam_role" {
  value = aws_iam_role.ec2.name
}

output "instance_type" {
  value = aws_instance.app.instance_type
}
