# infra/terraform — 청년 생활법률 상담 AI MVP 인프라(IaC)

EC2 · S3 · RDS · IAM · 비용 알림(Budgets)을 코드로 정의한다.
콘솔 수작업 없이 재현하고, 발표 후 `terraform destroy`로 비용을 정리한다.

## 생성되는 리소스

- EC2 (기본 `t3.large`) + IAM Role/Instance Profile(S3 read/write, Bedrock invoke)
- 보안 그룹 2개: 앱(22/8000/8501/8080 = 내 IP, 80/443 = 공개), RDS(5432 = 앱 SG만)
- S3 버킷(퍼블릭 전면 차단) — 산출물 백업
- RDS PostgreSQL(`db.t3.micro`, 비공개) — 상담/비용/평가 로그 + pgvector 확장 대상
- AWS Budgets 월 예산 알림(선택, `enable_budgets=true`일 때만) — DE-AI 프로젝트 계정은 budgets 권한이 없어 기본 비활성. 그 외엔 콘솔/관리자가 예산 알림 설정.

> EC2 사양: 임베딩(ko-sroberta) + Chroma + Airflow를 동시에 돌리면 RAM이 빠듯해
> `t3.large`(8GB)를 기본값으로 둔다. 비용을 아끼려면 `instance_type = "t3.medium"`(4GB)
> + 스왑 + Airflow on-demand(cron) 조합도 가능하다. vCPU는 두 타입 모두 2개로 동일하다.

## 사전 준비

- Terraform >= 1.5, AWS CLI 자격증명(`aws sts get-caller-identity` 동작)
- 내 공인 IP (`allowed_ip_cidr`, 예: `1.2.3.4/32`)

### us-west-2 준비물 (이 계정 점검 결과 — 둘 다 없어서 생성 필요)

apply 전에 한 번만 실행한다. (그룹 정책상 ec2:* 허용되어 가능)

```bash
# 1) 기본 VPC 생성 (us-west-2에 VPC가 없으면 main.tf의 default VPC data source가 실패)
aws ec2 create-default-vpc --region us-west-2

# 2) EC2 key pair 생성 → .pem 저장 (ec2_key_name 에 사용할 이름)
aws ec2 create-key-pair --region us-west-2 --key-name youth-law-key \
  --query KeyMaterial --output text > youth-law-key.pem
chmod 400 youth-law-key.pem
```

- Bedrock 모델 액세스: us-west-2에서 `us.anthropic.claude-sonnet-4-6` / `us.anthropic.claude-haiku-4-5-20251001-v1:0` **호출 확인 완료**(활성화됨).
- AWS Budgets: 계정 격리 정책에 budgets 권한이 없어 `enable_budgets=false` 유지.

## 실행

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars 편집 (allowed_ip_cidr, ec2_key_name, db_password, budget_email)

terraform init
terraform fmt
terraform validate
terraform plan      # 생성될 리소스 검토
terraform apply
```

출력으로 `ec2_public_ip`, `fastapi_url`, `s3_bucket`, `rds_endpoint` 등을 확인하고
이후 단계는 `docs/INFRA_IMPLEMENTATION_GUIDE.md`(EC2 셋업 → 데이터 구축 → 앱 → DuckDNS/HTTPS)를 따른다.

## 정리(비용 0으로)

```bash
terraform destroy
```

⚠️ 발표·데모가 끝나면 반드시 `destroy` 하거나 EC2/RDS를 stop 한다. `t3.large`를 한 달
방치하면 ~$61/월이 든다. 비용의 가장 큰 변수는 인스턴스 크기가 아니라 "끄는 걸 잊는 것"이다.

## 커밋 금지 파일

`terraform.tfvars`, `*.tfstate*`, `.terraform/` 는 비밀값/상태를 담으므로 커밋하지 않는다
(레포 `.gitignore`에 등록됨).
