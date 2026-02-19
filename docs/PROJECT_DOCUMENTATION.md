# EKS Upgrade Automation — Project Documentation

Overview

Automates safe upgrades of Amazon EKS development clusters, including cluster versions, addon versions, and managed node group versions. The project uses a two-stack CloudFormation architecture with GitHub Actions CI/CD. Includes Cluster Autoscaler for automatic node scaling and automatic upgrades enabled by default.

Current Infrastructure Status

| Component | Status | Details |
|-----------|--------|---------|
| Bootstrap Stack | UPDATE_COMPLETE | 19 resources in us-east-1 |
| Application Stack | UPDATE_COMPLETE | 10 resources in us-east-1 |
| EKS Cluster | ACTIVE | dev-dev-cluster, K8s v1.31 |
| Node Group | ACTIVE | 2x t3.medium, v1.31.13, scaling 1-4 |
| Cluster Autoscaler | Running | v1.31.1 in kube-system |
| Auto-Upgrade | Enabled | Lambda functions upgrade dev clusters automatically |
| SNS Notifications | Confirmed | olisa.arinze@aol.com |
| S3 Bucket | Active | eks-upgrade-automation-156041437006-us-east-1 |

Architecture

#Two-Stack Design

| Stack | Template | Status | Resources |
|-------|----------|--------|-----------|
| `eks-upgrade-bootstrap` | `cfn/initial-resources.yaml` | UPDATE_COMPLETE | 19 resources: S3, VPC, EKS cluster, node group, IAM roles, autoscaler |
| `eks-addon-management` | `template.yaml` | UPDATE_COMPLETE | 10 resources: Lambda functions, IAM roles, SNS, EventBridge schedules |

Deployment order: Bootstrap stack first, then application stack, then Cluster Autoscaler via kubectl.

#Lambda Functions

| Function | Schedule | Timeout | Purpose |
|----------|----------|---------|---------|
| `eks-version-checker` | Fridays 5 PM UTC | 120s | Cluster version checks, addon updates, notifications |
| `eks-nodegroup-version-manager` | Fridays 6 PM UTC | 300s | Node group version updates, PDB-aware, notifications |

The 1-hour gap ensures addons are updated before node groups are replaced.

#Cluster Autoscaler

| Setting | Value |
|---------|-------|
| Image | registry.k8s.io/autoscaling/cluster-autoscaler:v1.31.1 |
| Namespace | kube-system |
| Discovery | ASG tags: `k8s.io/cluster-autoscaler/enabled`, `k8s.io/cluster-autoscaler/dev-dev-cluster` |
| Scaling Range | Min: 1, Max: 4 nodes |
| Expander | least-waste |
| IAM | Permissions on node group role (dev-eks-nodegroup-role) |

#CI/CD Pipeline (GitHub Actions)

```
deploy.yml
  ├── bootstrap (predeploy.yml)     → Deploys cfn/initial-resources.yaml
  ├── validate                      → CFN validate + pyflakes lint
  └── deploy (needs: bootstrap + validate)
      ├── Package Lambda zips
      ├── Upload to S3
      └── Deploy template.yaml via CloudFormation
```

Pipeline features:
- Queries bootstrap stack directly for S3 bucket (avoids GitHub secret masking)
- Handles ROLLBACK_COMPLETE stacks by deleting and re-creating
- Auto-upgrade defaults to `true`

File Inventory

#Infrastructure as Code

| File | Description |
|------|-------------|
| `cfn/initial-resources.yaml` | Bootstrap stack: S3, VPC, EKS cluster, node group, OIDC, deployer role, autoscaler IAM |
| `template.yaml` | Application stack: Lambda functions, IAM roles, SNS topic, EventBridge schedules |
| `iam/deployer-policy.json` | Standalone JSON copy of deployer policy (for manual IAM setup) |

#Lambda Source Code

| File | Description |
|------|-------------|
| `scripts/code.py` | Cluster version monitoring + addon management Lambda |
| `scripts/nodegroup_code.py` | Managed node group version management Lambda |

#Kubernetes Manifests

| File | Description |
|------|-------------|
| `k8s/cluster-autoscaler.yaml` | Cluster Autoscaler: ServiceAccount, RBAC, Deployment |

#CI/CD Workflows

| File | Description |
|------|-------------|
| `.github/workflows/deploy.yml` | Main deployment pipeline (bootstrap → validate → deploy) |
| `.github/workflows/predeploy.yml` | Reusable workflow: deploys bootstrap CloudFormation stack |

#Deployment Tools

| File | Description |
|------|-------------|
| `deploy.sh` | CLI deployment script (packages Lambda, uploads to S3, deploys CFN) |

#Documentation

| File | Description |
|------|-------------|
| `README.md` | Project overview, quick start, configuration, full resource inventory |
| `docs/INITIAL_RESOURCES.md` | Bootstrap stack guide: all 19 resources, parameters, outputs, GitHub config |
| `docs/DEPLOYMENT.md` | Full deployment guide with all options |
| `docs/QUICK_REFERENCE.md` | Quick reference card for common operations |
| `docs/PROJECT_DOCUMENTATION.md` | This file — full project technical documentation |

Prerequisites and Secrets

#For CLI Deployment

- AWS CLI installed and configured
- kubectl installed and configured
- IAM permissions to create CloudFormation stacks, Lambda, IAM roles, SNS, Scheduler, S3

#For GitHub Actions

Secrets (repository settings):

| Secret | Description |
|--------|-------------|
| `AWS_ROLE_ARN` | Deployer role ARN from bootstrap stack |
| `AWS_ACCESS_KEY_ID` | IAM access key (used by bootstrap job only) |
| `AWS_SECRET_ACCESS_KEY` | IAM secret key (used by bootstrap job only) |
| `AWS_REGION` | AWS region (us-east-1) |

Variables (repository settings):

| Variable | Description |
|----------|-------------|
| `AWS_REGION` | AWS region (us-east-1) |
| `S3_BUCKET` | Artifact bucket name from bootstrap stack (optional — auto-detected from bootstrap) |
| `NOTIFICATION_EMAIL` | Email for SNS notifications (current: olisa.arinze@aol.com) |

Development Cluster Discovery

The Lambda functions identify development clusters using (case-insensitive):

1. Tag-based: Key `Environment`, `environment`, or `Env` with value containing `dev` or `development`
2. Name-based: Cluster name containing `dev` or `development`

Current cluster `dev-dev-cluster` is tagged `Environment: dev` and matches both criteria.

Production clusters are automatically skipped.

Deployment Sequence

#First-Time Setup

1. Deploy bootstrap stack (CLI or GitHub Actions manual trigger)
2. Read bootstrap stack outputs
3. Configure GitHub repository secrets and variables with the outputs
4. Push to `main` or trigger deploy workflow manually
5. Deploy Cluster Autoscaler: `kubectl apply -f k8s/cluster-autoscaler.yaml`

#Subsequent Deployments

Push to `main` triggers the full pipeline automatically:
1. Bootstrap stack is idempotent (no-op if unchanged)
2. Templates and code are validated
3. Lambda code is packaged and uploaded
4. Application stack is created or updated
5. Cluster Autoscaler manifest can be re-applied if changed

Security Design

- OIDC authentication: Deploy job uses short-lived tokens (no long-lived credentials)
- Scoped IAM permissions: Deployer policy targets specific resource ARNs, not wildcards
- S3 security: Bucket enforces HTTPS-only, versioning enabled, public access blocked
- Partition-agnostic: Main template uses `${AWS::Partition}` for GovCloud/China compatibility
- SNS scoping: Lambda publish permissions target the specific SNS topic, not `*`
- Autoscaler: SetDesiredCapacity and TerminateInstanceInAutoScalingGroup scoped to account ASGs
- Node group role: Includes autoscaler permissions for ASG read/write operations

Cost Estimates

#Application Stack (~$1.20/month)

| Service | Estimate |
|---------|----------|
| Lambda | ~$0.20 |
| CloudWatch Logs | ~$0.50 |
| SNS | ~$0.50 |
| EventBridge Scheduler | Free tier |

#Bootstrap Stack (~$133/month)

| Service | Estimate |
|---------|----------|
| EKS Control Plane | ~$73.00 |
| EC2 Nodes (2x t3.medium) | ~$60.00 |
| S3 (artifact storage) | ~$0.03 |
| VPC / Networking | Free |
| IAM / OIDC | Free |

#Total: ~$134.23/month

The Cluster Autoscaler may reduce costs by scaling down unused nodes to the minimum (1 node).

Troubleshooting

#Bootstrap stack fails

- Check IAM permissions of the deploying principal
- If OIDC provider already exists, set `CreateOIDCProvider=false`
- Check CloudFormation events: `aws cloudformation describe-stack-events --stack-name eks-upgrade-bootstrap`

#Deploy job fails with "No S3 bucket available"

- Ensure bootstrap job completed successfully
- The deploy job queries the bootstrap stack directly for the bucket name
- Fall back: set `vars.S3_BUCKET` in GitHub repository variables

#Lambda timeout

- Addon Lambda: 120s timeout — check CloudWatch logs for slow API calls
- Node group Lambda: 300s timeout — large clusters may need increased timeout

#No notifications received

1. Confirm SNS email subscription (current: olisa.arinze@aol.com, Confirmed)
2. Check Lambda CloudWatch logs
3. Verify clusters are tagged as development
4. Check Lambda IAM permissions for `sns:Publish`

#Cluster Autoscaler not scaling

1. Check logs: `kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler`
2. Verify node group role has autoscaling permissions
3. Ensure ASG has discovery tags: `k8s.io/cluster-autoscaler/enabled` and `k8s.io/cluster-autoscaler/dev-dev-cluster`
4. Check ASG min/max limits match expectations
