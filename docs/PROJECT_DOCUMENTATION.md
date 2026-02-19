# EKS Upgrade Automation — Project Documentation

## Overview

Automates safe upgrades of Amazon EKS development clusters, including cluster versions, addon versions, and managed node group versions. The project uses a two-stack CloudFormation architecture with GitHub Actions CI/CD.

## Architecture

### Two-Stack Design

| Stack | Template | Purpose |
|-------|----------|---------|
| `eks-upgrade-bootstrap` | `cfn/initial-resources.yaml` | Base infrastructure: S3 bucket, OIDC provider, deployer IAM role |
| `eks-addon-management` | `template.yaml` | Application stack: Lambda functions, IAM roles, SNS, EventBridge schedules |

**Deployment order:** Bootstrap stack first, then application stack.

### Lambda Functions

| Function | Schedule | Timeout | Purpose |
|----------|----------|---------|---------|
| `eks-version-checker` | Fridays 5 PM UTC | 120s | Cluster version checks, addon updates, notifications |
| `eks-nodegroup-version-manager` | Fridays 6 PM UTC | 300s | Node group version updates, PDB-aware, notifications |

The 1-hour gap ensures addons are updated before node groups are replaced.

### CI/CD Pipeline (GitHub Actions)

```
deploy.yml
  ├── bootstrap (predeploy.yml)     → Deploys cfn/initial-resources.yaml
  ├── validate                      → CFN validate + pyflakes lint
  └── deploy (needs: bootstrap + validate)
      ├── Package Lambda zips
      ├── Upload to S3
      └── Deploy template.yaml via CloudFormation
```

## File Inventory

### Infrastructure as Code

| File | Description |
|------|-------------|
| `cfn/initial-resources.yaml` | Bootstrap stack: S3 bucket, OIDC provider, deployer role + policy |
| `template.yaml` | Application stack: Lambda functions, IAM roles, SNS topic, EventBridge schedules |
| `iam/deployer-policy.json` | Standalone JSON copy of deployer policy (for manual IAM setup) |

### Lambda Source Code

| File | Description |
|------|-------------|
| `scripts/code.py` | Cluster version monitoring + addon management Lambda |
| `scripts/nodegroup_code.py` | Managed node group version management Lambda |

### CI/CD Workflows

| File | Description |
|------|-------------|
| `.github/workflows/deploy.yml` | Main deployment pipeline (bootstrap → validate → deploy) |
| `.github/workflows/predeploy.yml` | Reusable workflow: deploys bootstrap CloudFormation stack |

### Deployment Tools

| File | Description |
|------|-------------|
| `deploy.sh` | CLI deployment script (packages Lambda, uploads to S3, deploys CFN) |

### Documentation

| File | Description |
|------|-------------|
| `README.md` | Project overview, quick start, configuration |
| `docs/INITIAL_RESOURCES.md` | Bootstrap stack guide: parameters, outputs, GitHub config |
| `docs/DEPLOYMENT.md` | Full deployment guide with all options |
| `docs/QUICK_REFERENCE.md` | Quick reference card for common operations |
| `docs/PROJECT_DOCUMENTATION.md` | This file — full project technical documentation |

## Prerequisites and Secrets

### For CLI Deployment

- AWS CLI installed and configured
- IAM permissions to create CloudFormation stacks, Lambda, IAM roles, SNS, Scheduler, S3

### For GitHub Actions

**Secrets** (repository settings):

| Secret | Description |
|--------|-------------|
| `AWS_ROLE_ARN` | Deployer role ARN from bootstrap stack |
| `AWS_ACCESS_KEY_ID` | IAM access key (used by bootstrap job only) |
| `AWS_SECRET_ACCESS_KEY` | IAM secret key (used by bootstrap job only) |
| `AWS_REGION` | AWS region |

**Variables** (repository settings):

| Variable | Description |
|----------|-------------|
| `AWS_REGION` | AWS region (e.g., `us-east-1`) |
| `S3_BUCKET` | Artifact bucket name from bootstrap stack (optional — auto-detected from bootstrap) |
| `NOTIFICATION_EMAIL` | Email for SNS notifications |

## Development Cluster Discovery

The Lambda functions identify development clusters using (case-insensitive):

1. **Tag-based:** Key `Environment`, `environment`, or `Env` with value containing `dev` or `development`
2. **Name-based:** Cluster name containing `dev` or `development`

Production clusters are automatically skipped.

## Deployment Sequence

### First-Time Setup

1. Deploy bootstrap stack (CLI or GitHub Actions manual trigger)
2. Read bootstrap stack outputs
3. Configure GitHub repository secrets and variables with the outputs
4. Push to `main` or trigger deploy workflow manually

### Subsequent Deployments

Push to `main` triggers the full pipeline automatically:
1. Bootstrap stack is idempotent (no-op if unchanged)
2. Templates and code are validated
3. Lambda code is packaged and uploaded
4. Application stack is created or updated

## Security Design

- **OIDC authentication**: Deploy job uses short-lived tokens (no long-lived credentials)
- **Scoped IAM permissions**: Deployer policy targets specific resource ARNs, not wildcards
- **S3 security**: Bucket enforces HTTPS-only, versioning enabled, public access blocked
- **Partition-agnostic**: Main template uses `${AWS::Partition}` for GovCloud/China compatibility
- **SNS scoping**: Lambda publish permissions target the specific SNS topic, not `*`

## Cost Estimates

### Application Stack (~$1.20/month)

| Service | Estimate |
|---------|----------|
| Lambda | ~$0.20 |
| CloudWatch Logs | ~$0.50 |
| SNS | ~$0.50 |
| EventBridge Scheduler | Free tier |

### Bootstrap Stack

| Service | Estimate |
|---------|----------|
| S3 (artifact storage) | ~$0.03 |
| IAM | Free |
| OIDC Provider | Free |

## Troubleshooting

### Bootstrap stack fails

- Check IAM permissions of the deploying principal
- If OIDC provider already exists, set `CreateOIDCProvider=false`
- Check CloudFormation events: `aws cloudformation describe-stack-events --stack-name eks-upgrade-bootstrap`

### Deploy job fails with "No S3 bucket available"

- Ensure bootstrap job completed successfully
- Check that `vars.S3_BUCKET` is set in GitHub repository variables

### Lambda timeout

- Addon Lambda: 120s timeout — check CloudWatch logs for slow API calls
- Node group Lambda: 300s timeout — large clusters may need increased timeout

### No notifications received

1. Confirm SNS email subscription
2. Check Lambda CloudWatch logs
3. Verify clusters are tagged as development
4. Check Lambda IAM permissions for `sns:Publish`
