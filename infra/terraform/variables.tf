variable "aws_region" {
  type    = string
  default = "us-west-2" # .env.example 기본값과 일치 (Bedrock inference profile 기준)
}

variable "project_name" {
  type    = string
  default = "youth-law"
}

variable "instance_type" {
  type        = string
  default     = "t3.large"
  description = "EC2 인스턴스 타입. 임베딩+Chroma+Airflow 동시 실행 여유를 위해 t3.large 권장(8GB). 비용 절감 시 t3.medium(4GB)+스왑+Airflow on-demand도 가능."
}

variable "allowed_ip_cidr" {
  type        = string
  description = "SSH/FastAPI/Streamlit/Airflow 접근 허용 CIDR. 예: 1.2.3.4/32 (내 공인 IP)"
}

variable "ec2_key_name" {
  type        = string
  description = "기존 EC2 key pair 이름"
}

variable "db_username" {
  type    = string
  default = "youthlaw"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "RDS 마스터 비밀번호. terraform.tfvars에만 넣고 절대 커밋하지 않는다."
}

variable "enable_budgets" {
  type        = bool
  default     = false
  description = "AWS Budgets 알림 생성 여부. DE-AI 프로젝트 계정은 budgets 권한이 없어 false 유지. budgets 권한 있는 계정에서만 true."
}

variable "budget_limit_usd" {
  type        = string
  default     = "50"
  description = "월 예산 한도(USD). enable_budgets=true일 때 80%(실제)·100%(예측)에서 이메일 알림."
}

variable "budget_email" {
  type        = string
  default     = ""
  description = "비용 알림 수신 이메일. enable_budgets=true일 때만 필요."
}
