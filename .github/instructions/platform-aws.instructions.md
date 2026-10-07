---
description: "Use when editing AWS data platform code or IaC: Glue jobs, Step Functions, Airflow/MWAA DAGs, Lambda, Redshift/Athena SQL, Lake Formation, Terraform, CDK, CloudFormation."
applyTo: "**/*.asl.json,**/glue/**,**/dags/**/*.py"
---
# AWS Data Platform Rules

- Change code and its IaC definition together (job script + job resource, state machine + resource).
- No hardcoded account IDs, regions, bucket names, or ARNs; use IaC variables/parameters.
- Secrets in Secrets Manager or SSM Parameter Store only.
- IAM/Lake Formation changes must be least-privilege and called out for review.
- `terraform validate/plan`, `cdk synth`, `cfn-lint` are allowed; `apply`/`deploy` and mutating `aws` CLI calls require explicit approval.
