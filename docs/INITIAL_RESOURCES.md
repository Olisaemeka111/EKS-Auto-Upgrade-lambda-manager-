# Bootstrap Infrastructure

The bootstrap CloudFormation stack (`cfn/initial-resources.yaml`) creates the prerequisite infrastructure that must exist **before** deploying the main EKS Upgrade Automation stack.

## What It Creates

| Resource | Purpose |
|----------|---------|
| **S3 Bucket** | Stores Lambda code packages and CloudFormation templates |
| **GitHub OIDC Provider** | Enables GitHub Actions to authenticate via short-lived tokens |
| **Deployer IAM Role** | Assumed by GitHub Actions workflows to deploy resources |
| **Deployer Managed Policy** | Least-privilege permissions for CloudFormation, Lambda, IAM, SNS, Scheduler, S3 |

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `Environment` | No | `dev` | Environment name (`dev`, `staging`, `prod`) |
| `S3BucketName` | No | auto-generated | Explicit bucket name; blank = `eks-upgrade-automation-{AccountId}-{Region}` |
| `GitHubOrg` | Yes | - | GitHub organization or username |
| `GitHubRepo` | No | `automate-eks-upgrades` | GitHub repository name |
| `CreateOIDCProvider` | No | `true` | Set `false` if your account already has a GitHub OIDC provider |

## Deploy via CLI (One-Time Setup)

```bash
aws cloudformation deploy \
  --template-file cfn/initial-resources.yaml \
  --stack-name eks-upgrade-bootstrap \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOrg=YOUR-GITHUB-ORG \
    GitHubRepo=automate-eks-upgrades \
    Environment=dev
```

## Deploy via GitHub Actions

Run the **Bootstrap Base Infrastructure** workflow manually:

**Actions > Bootstrap Base Infrastructure > Run workflow**

Or it runs automatically as the first step of the **Deploy EKS Upgrade Automation** workflow.

## Read Stack Outputs

After deployment, retrieve the outputs you need for GitHub configuration:

```bash
aws cloudformation describe-stacks \
  --stack-name eks-upgrade-bootstrap \
  --query 'Stacks[0].Outputs'
```

Key outputs:
- **ArtifactBucketName** — set as GitHub variable `S3_BUCKET`
- **DeployerRoleArn** — set as GitHub secret `AWS_ROLE_ARN`

## Configure GitHub Repository

After deploying the bootstrap stack, configure these in your GitHub repository:

**Secrets** (Settings > Secrets and variables > Actions > Secrets):

| Secret | Value |
|--------|-------|
| `AWS_ROLE_ARN` | `DeployerRoleArn` output from bootstrap stack |
| `AWS_ACCESS_KEY_ID` | IAM access key (for bootstrap job only) |
| `AWS_SECRET_ACCESS_KEY` | IAM secret key (for bootstrap job only) |
| `AWS_REGION` | AWS region (e.g., `us-east-1`) |

**Variables** (Settings > Secrets and variables > Actions > Variables):

| Variable | Value |
|----------|-------|
| `AWS_REGION` | AWS region (e.g., `us-east-1`) |
| `S3_BUCKET` | `ArtifactBucketName` output from bootstrap stack |
| `NOTIFICATION_EMAIL` | Email for SNS notifications |

## Security Notes

- The S3 bucket enforces HTTPS-only access and has versioning enabled
- The OIDC provider eliminates the need for long-lived AWS credentials in the deploy job
- The deployer policy uses scoped resource ARNs (not wildcards) wherever possible
- The `iam/deployer-policy.json` file is a standalone copy for manual use; the authoritative version is in the CloudFormation template

## Cleanup

To delete the bootstrap stack and all its resources:

```bash
# Empty the S3 bucket first (required before deletion)
aws s3 rm s3://BUCKET-NAME --recursive

aws cloudformation delete-stack \
  --stack-name eks-upgrade-bootstrap
```

Note: The S3 bucket has `DeletionPolicy: Retain` so it won't be deleted with the stack. Delete it manually if no longer needed.
