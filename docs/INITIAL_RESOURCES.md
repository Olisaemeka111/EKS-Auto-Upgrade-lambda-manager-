# Bootstrap Infrastructure

The bootstrap CloudFormation stack (`cfn/initial-resources.yaml`) creates the prerequisite infrastructure that must exist **before** deploying the main EKS Upgrade Automation stack.

## What It Creates

### Deployment Infrastructure

| Resource | Purpose |
|----------|---------|
| **S3 Bucket** | Stores Lambda code packages and CloudFormation templates |
| **GitHub OIDC Provider** | Enables GitHub Actions to authenticate via short-lived tokens |
| **Deployer IAM Role** | Assumed by GitHub Actions workflows to deploy resources |
| **Deployer Managed Policy** | Least-privilege permissions for CloudFormation, Lambda, IAM, SNS, Scheduler, S3 |

### EKS Development Cluster

| Resource | Purpose |
|----------|---------|
| **VPC + 2 Public Subnets** | Networking for the EKS cluster across 2 AZs |
| **Internet Gateway + Route Table** | Outbound internet access for nodes |
| **EKS Cluster** | Development cluster tagged with `Environment: dev` for automation discovery |
| **Managed Node Group** | Worker nodes (default: 2x t3.medium) managed by the automation |
| **EKS Cluster IAM Role** | Service role for the EKS control plane |
| **Node Group IAM Role** | Instance role with EKS worker node policies |

## Parameters

### Deployment Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `Environment` | No | `dev` | Environment name (`dev`, `staging`, `prod`) |
| `S3BucketName` | No | auto-generated | Explicit bucket name; blank = `eks-upgrade-automation-{AccountId}-{Region}` |
| `GitHubOrg` | Yes | - | GitHub organization or username |
| `GitHubRepo` | No | `automate-eks-upgrades` | GitHub repository name |
| `CreateOIDCProvider` | No | `true` | Set `false` if your account already has a GitHub OIDC provider |

### EKS Cluster Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `EKSClusterVersion` | No | `1.31` | Kubernetes version for the dev cluster |
| `VpcCidr` | No | `10.0.0.0/16` | CIDR block for the VPC |
| `NodeInstanceType` | No | `t3.medium` | EC2 instance type for worker nodes |
| `NodeDesiredSize` | No | `2` | Desired number of worker nodes |
| `NodeMinSize` | No | `1` | Minimum number of worker nodes |
| `NodeMaxSize` | No | `4` | Maximum number of worker nodes |

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
- **EKSClusterName** — the dev cluster the automation will manage
- **EKSClusterEndpoint** — API endpoint for kubectl access
- **NodeGroupName** — the managed node group the automation will update

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

## Verify the EKS Cluster

After bootstrap deployment, verify the cluster is running and tagged correctly:

```bash
# Check cluster status
aws eks describe-cluster \
  --name dev-dev-cluster \
  --query '{Status: cluster.status, Version: cluster.version, Tags: cluster.tags}'

# Configure kubectl
aws eks update-kubeconfig --name dev-dev-cluster --region us-east-1

# Verify nodes are ready
kubectl get nodes
```

The cluster is named `{Environment}-dev-cluster` and tagged with `Environment: {Environment}`, so the automation Lambda functions will discover and manage it automatically.

## Security Notes

- The S3 bucket enforces HTTPS-only access and has versioning enabled
- The OIDC provider eliminates the need for long-lived AWS credentials in the deploy job
- The deployer policy uses scoped resource ARNs (not wildcards) wherever possible
- The `iam/deployer-policy.json` file is a standalone copy for manual use; the authoritative version is in the CloudFormation template
- The EKS cluster has both public and private API endpoints enabled

## Cost Estimates

| Resource | Approximate Monthly Cost |
|----------|-------------------------|
| EKS Control Plane | ~$73.00 |
| EC2 Nodes (2x t3.medium) | ~$60.00 |
| VPC / Networking | Free |
| S3 (artifacts) | ~$0.03 |
| IAM / OIDC | Free |
| **Total** | **~$133/month** |

To reduce costs, scale the node group down when not testing:
```bash
aws eks update-nodegroup-config \
  --cluster-name dev-dev-cluster \
  --nodegroup-name dev-dev-nodegroup \
  --scaling-config desiredSize=1,minSize=1,maxSize=4
```

## Cleanup

To delete the bootstrap stack and all its resources:

```bash
# Delete the application stack first (if deployed)
aws cloudformation delete-stack --stack-name eks-addon-management

# Empty the S3 bucket (required before deletion)
aws s3 rm s3://BUCKET-NAME --recursive

# Delete the bootstrap stack (EKS cluster, VPC, IAM, etc.)
aws cloudformation delete-stack --stack-name eks-upgrade-bootstrap

# Wait for deletion
aws cloudformation wait stack-delete-complete --stack-name eks-upgrade-bootstrap
```

Note: The S3 bucket has `DeletionPolicy: Retain` so it won't be deleted with the stack. Delete it manually if no longer needed:
```bash
aws s3 rb s3://BUCKET-NAME --force
```
