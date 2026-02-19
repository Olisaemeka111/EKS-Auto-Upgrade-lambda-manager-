# Automate Kubernetes Version Monitoring for Amazon EKS Clusters

This project provides automated management of Amazon EKS clusters, including:
- Cluster version monitoring and automatic upgrades
- EKS addon version management (vpc-cni, kube-proxy, coredns, aws-ebs-csi-driver, etc.)
- Managed node group version updates with Pod Disruption Budget (PDB) respect
- Cluster Autoscaler for automatic node scaling based on pod demand

Current Infrastructure Status

| Component | Status | Details |
|-----------|--------|---------|
| EKS Cluster (`dev-dev-cluster`) | ACTIVE | Kubernetes v1.31, Platform eks.51 |
| Node Group (`dev-dev-nodegroup`) | ACTIVE | 2x t3.medium, v1.31.13, scaling 1-4 |
| Cluster Autoscaler | Running | v1.31.1, auto-discovers ASGs via tags |
| Auto-Upgrade | Enabled | Lambda functions upgrade dev clusters automatically |
| SNS Notifications | Confirmed | olisa.arinze@aol.com |
| S3 Bucket | Active | eks-upgrade-automation-156041437006-us-east-1 |
| Region | us-east-1 | All resources deployed here |

Features

#1. Cluster Version Management
- Monitors EKS cluster versions against latest available versions
- Checks upgrade readiness insights before upgrading
- Automatically upgrades development clusters (auto-upgrade is enabled)
- Sends email notifications for all cluster status changes

#2. Addon Management
- Discovers all EKS addons in each cluster
- Checks for available addon updates
- Preserves authentication configuration (Pod Identity, IRSA)
- Updates addons automatically while maintaining compatibility
- Sends consolidated notifications per cluster

#3. Node Group Management
- Discovers all managed node groups in each cluster
- Compares node group versions with cluster versions
- Updates node groups to match cluster version with latest AMI
- Respects Pod Disruption Budgets (never uses force flag)
- Provides manual force update instructions when PDB blocks updates
- Sends consolidated notifications per cluster

#4. Cluster Autoscaler
- Automatically scales node group between 1 and 4 nodes based on pod demand
- Uses ASG tag-based auto-discovery for `dev-dev-cluster`
- Runs as a deployment in `kube-system` namespace
- IAM permissions attached to node group role for AWS API access
- Manifest located at `k8s/cluster-autoscaler.yaml`

Architecture

![Architecture Diagram](./images/Amazon-EKS-Upgrade.png)

#Two-Stack Design

| Stack | Template | Status | Resources |
|-------|----------|--------|-----------|
| `eks-upgrade-bootstrap` | `cfn/initial-resources.yaml` | UPDATE_COMPLETE | 19 resources |
| `eks-addon-management` | `template.yaml` | UPDATE_COMPLETE | 10 resources |

#Bootstrap Stack Resources (19)

| Resource | Type |
|----------|------|
| ArtifactBucket | S3 Bucket |
| ArtifactBucketPolicy | S3 Bucket Policy |
| VPC | EC2 VPC (10.0.0.0/16) |
| PublicSubnetA | EC2 Subnet (AZ us-east-1a) |
| PublicSubnetB | EC2 Subnet (AZ us-east-1b) |
| InternetGateway | EC2 Internet Gateway |
| VPCGatewayAttachment | VPC-IGW Attachment |
| PublicRouteTable | EC2 Route Table |
| PublicRoute | EC2 Route (0.0.0.0/0 to IGW) |
| SubnetARouteTableAssoc | Subnet-RT Association |
| SubnetBRouteTableAssoc | Subnet-RT Association |
| EKSClusterRole | IAM Role (EKS service) |
| EKSClusterSecurityGroup | EC2 Security Group |
| EKSDevCluster | EKS Cluster (v1.31) |
| NodeGroupRole | IAM Role (EC2 + Autoscaler) |
| DevNodeGroup | EKS Managed Node Group |
| ClusterAutoscalerRole | IAM Role (Autoscaler) |
| DeployerRole | IAM Role (GitHub Actions) |
| DeployerManagedPolicy | IAM Managed Policy |

#Application Stack Resources (10)

| Resource | Type |
|----------|------|
| EKSVersionCheckerFunction | Lambda Function |
| NodeGroupManagementFunction | Lambda Function |
| LambdaExecutionRole | IAM Role |
| NodeGroupLambdaExecutionRole | IAM Role |
| SchedulerRole | IAM Role |
| NodeGroupSchedulerRole | IAM Role |
| WeeklySchedule | EventBridge Schedule (Fridays 5 PM UTC) |
| NodeGroupDelayedSchedule | EventBridge Schedule (Fridays 6 PM UTC) |
| EKSUpgradeNotificationTopic | SNS Topic |
| EmailSubscription | SNS Subscription (olisa.arinze@aol.com) |

#Kubernetes Resources (Cluster Autoscaler)

| Resource | Namespace |
|----------|-----------|
| ServiceAccount/cluster-autoscaler | kube-system |
| ClusterRole/cluster-autoscaler | cluster-scoped |
| ClusterRoleBinding/cluster-autoscaler | cluster-scoped |
| Role/cluster-autoscaler | kube-system |
| RoleBinding/cluster-autoscaler | kube-system |
| Deployment/cluster-autoscaler | kube-system |

#Lambda Functions

1. eks-version-checker (Runs Fridays at 5 PM UTC)
   - Checks cluster versions and upgrade readiness
   - Manages addon updates
   - Sends notifications

2. eks-nodegroup-version-manager (Runs Fridays at 6 PM UTC)
   - Updates node group versions
   - Respects Pod Disruption Budgets
   - Sends notifications

The 1-hour delay ensures addons are updated before node groups are replaced.

Cluster Filtering

The solution processes only development clusters by checking:
- Cluster tags: `Environment` or `Env` containing "dev" or "development"
- Cluster name: Contains "dev" or "development"

Production clusters are automatically skipped.

Prerequisites

1. AWS CLI installed and configured
2. IAM permissions to create CloudFormation stacks, Lambda, IAM roles, SNS, Scheduler, S3
3. At least one EKS cluster tagged as development
4. kubectl configured for cluster access (for Cluster Autoscaler deployment)

Quick Start

#Step 1: Deploy Bootstrap Infrastructure

The bootstrap stack creates the S3 bucket, GitHub OIDC provider, deployer IAM role, VPC, EKS cluster, and node group. This must be deployed first.

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

Retrieve the outputs:
```bash
aws cloudformation describe-stacks \
  --stack-name eks-upgrade-bootstrap \
  --query 'Stacks[0].Outputs'
```

See [docs/INITIAL_RESOURCES.md](./docs/INITIAL_RESOURCES.md) for full details.

#Step 2: Deploy the Application

Option A: GitHub Actions (Recommended)

1. Fork/clone this repository
2. Configure GitHub repository settings with the bootstrap stack outputs:

   Secrets:

   | Secret | Description |
   |--------|-------------|
   | `AWS_ROLE_ARN` | `DeployerRoleArn` from bootstrap stack |
   | `AWS_ACCESS_KEY_ID` | IAM access key (for bootstrap job) |
   | `AWS_SECRET_ACCESS_KEY` | IAM secret key (for bootstrap job) |
   | `AWS_REGION` | AWS region (e.g., `us-east-1`) |

   Variables:

   | Variable | Description |
   |----------|-------------|
   | `AWS_REGION` | AWS region (e.g., `us-east-1`) |
   | `S3_BUCKET` | `ArtifactBucketName` from bootstrap stack |
   | `NOTIFICATION_EMAIL` | Email for SNS notifications |

3. Push to `main` or trigger manually via Actions > Deploy EKS Upgrade Automation > Run workflow

Option B: Deploy Script

```bash
./deploy.sh YOUR-BUCKET-NAME us-east-1 your-email@example.com true
```

Option C: Manual Deployment

See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) for detailed manual deployment instructions.

#Step 3: Deploy Cluster Autoscaler

```bash
aws eks update-kubeconfig --name dev-dev-cluster --region us-east-1
kubectl apply -f k8s/cluster-autoscaler.yaml
kubectl get pods -n kube-system -l app.kubernetes.io/name=cluster-autoscaler
```

Configuration

#Application Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `NotificationEmail` | Yes | - | Email address for SNS notifications |
| `EnableAutoUpgrade` | No | `true` | Enable automatic upgrades for development clusters |
| `LambdaCodeBucket` | Yes | - | S3 bucket containing Lambda code packages |
| `LambdaCodePrefix` | No | `eks-addon-management/lambda` | S3 key prefix for Lambda code |

#Bootstrap Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `GitHubOrg` | Yes | - | GitHub organization or username |
| `GitHubRepo` | No | `automate-eks-upgrades` | GitHub repository name |
| `Environment` | No | `dev` | Environment name |
| `S3BucketName` | No | auto-generated | Explicit S3 bucket name |
| `CreateOIDCProvider` | No | `true` | Set `false` if OIDC provider already exists |
| `EKSClusterVersion` | No | `1.31` | Kubernetes version for the dev cluster |
| `NodeInstanceType` | No | `t3.medium` | EC2 instance type for worker nodes |
| `NodeDesiredSize` | No | `2` | Desired number of worker nodes |
| `NodeMinSize` | No | `1` | Minimum number of worker nodes |
| `NodeMaxSize` | No | `4` | Maximum number of worker nodes |

#Tagging Development Clusters

Tag your development clusters with one of:

```yaml
Environment: dev
Environment: development
Env: dev-us-east-1
```

Or include "dev" in the cluster name:
- `my-dev-cluster`
- `development-cluster`

Notifications

You'll receive consolidated email notifications at olisa.arinze@aol.com for:

#Cluster Updates
- Up-to-date clusters
- Available upgrades
- Blocked upgrades (with insights)
- Initiated upgrades

#Addon Updates
- Up-to-date addons
- Successfully updated addons
- Failed addon updates with error details

#Node Group Updates
- Up-to-date node groups
- Updating node groups with update IDs
- Failed updates with PDB guidance

Troubleshooting

#Node Group Updates Failing

If node group updates fail due to Pod Disruption Budgets:
1. Review your PDB configurations
2. Consider temporarily relaxing PDB constraints
3. Use the force flag manually if needed (see notification email for command)

#No Notifications Received

1. Check SNS subscription is confirmed (check your email)
2. Verify Lambda has permission to publish to SNS topic
3. Check CloudWatch logs for errors
4. Ensure clusters are properly tagged as development

#Cluster Autoscaler Not Scaling

1. Check autoscaler logs: `kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler`
2. Verify node group role has autoscaling permissions
3. Ensure ASG has tags: `k8s.io/cluster-autoscaler/enabled` and `k8s.io/cluster-autoscaler/dev-dev-cluster`

Cost Estimates

Approximate monthly costs:
- EKS Control Plane: ~$73.00/month
- EC2 Nodes (2x t3.medium): ~$60.00/month
- Lambda Execution: ~$0.20/month
- CloudWatch Logs: ~$0.50/month
- SNS: ~$0.50/month
- EventBridge Scheduler: Free tier
- S3 (artifacts): ~$0.03/month
- Total: ~$134.23/month

To reduce costs, scale the node group down when not testing:
```bash
aws eks update-nodegroup-config \
  --cluster-name dev-dev-cluster \
  --nodegroup-name dev-dev-nodegroup \
  --scaling-config desiredSize=1,minSize=1,maxSize=4
```

Project Structure

```
automate-eks-upgrades/
  cfn/
    initial-resources.yaml          # Bootstrap stack (S3, VPC, EKS, OIDC, deployer role, autoscaler IAM)
  iam/
    deployer-policy.json            # Standalone deployer policy (for manual use)
  scripts/
    code.py                         # Cluster + addon management Lambda
    nodegroup_code.py               # Node group management Lambda
  k8s/
    cluster-autoscaler.yaml         # Cluster Autoscaler Kubernetes manifest
  docs/
    INITIAL_RESOURCES.md            # Bootstrap infrastructure guide
    DEPLOYMENT.md                   # Full deployment guide
    QUICK_REFERENCE.md              # Quick reference card
    PROJECT_DOCUMENTATION.md        # Full project technical docs
  .github/workflows/
    deploy.yml                      # Main CI/CD pipeline
    predeploy.yml                   # Bootstrap reusable workflow
  template.yaml                     # Application CloudFormation template
  deploy.sh                         # CLI deployment script
```

License

This project is licensed under the MIT License - see the LICENSE file for details.
