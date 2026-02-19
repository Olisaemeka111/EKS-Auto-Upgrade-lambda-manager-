# Bootstrap Infrastructure

The bootstrap CloudFormation stack (`cfn/initial-resources.yaml`) creates the prerequisite infrastructure that must exist before deploying the main EKS Upgrade Automation stack.

Current Status: UPDATE_COMPLETE (19 resources)

What It Creates

#Deployment Infrastructure

| Resource | Type | Status | Details |
|----------|------|--------|---------|
| ArtifactBucket | S3 Bucket | Active | eks-upgrade-automation-156041437006-us-east-1 |
| ArtifactBucketPolicy | S3 Bucket Policy | Active | HTTPS-only, versioning enabled |
| GitHubOIDCProvider | IAM OIDC Provider | Active | GitHub Actions authentication |
| DeployerRole | IAM Role | Active | eks-upgrade-bootstrap-deployer-role |
| DeployerManagedPolicy | IAM Managed Policy | Active | Scoped deployment permissions |

#VPC Networking

| Resource | Type | Status | Details |
|----------|------|--------|---------|
| VPC | EC2 VPC | Active | vpc-047be19af47bea846, CIDR 10.0.0.0/16 |
| PublicSubnetA | EC2 Subnet | Active | subnet-03fcca809dc5900cd, AZ us-east-1a |
| PublicSubnetB | EC2 Subnet | Active | subnet-0528f68f4c8ad2fe5, AZ us-east-1b |
| InternetGateway | EC2 Internet Gateway | Active | igw-080c4d65bd993e76a |
| VPCGatewayAttachment | VPC-IGW Attachment | Active | |
| PublicRouteTable | EC2 Route Table | Active | rtb-0314d7499fe39a1f5 |
| PublicRoute | EC2 Route | Active | 0.0.0.0/0 to IGW |
| SubnetARouteTableAssoc | Subnet-RT Association | Active | |
| SubnetBRouteTableAssoc | Subnet-RT Association | Active | |

#EKS Development Cluster

| Resource | Type | Status | Details |
|----------|------|--------|---------|
| EKSClusterRole | IAM Role | Active | dev-eks-cluster-role |
| EKSClusterSecurityGroup | EC2 Security Group | Active | sg-02e3d46ce53e3238e |
| EKSDevCluster | EKS Cluster | ACTIVE | dev-dev-cluster, K8s v1.31, Platform eks.51 |
| NodeGroupRole | IAM Role | Active | dev-eks-nodegroup-role (includes Autoscaler permissions) |
| DevNodeGroup | EKS Managed Node Group | ACTIVE | dev-dev-nodegroup, 2x t3.medium, v1.31.13 |

#Cluster Autoscaler IAM

| Resource | Type | Status | Details |
|----------|------|--------|---------|
| ClusterAutoscalerRole | IAM Role | Active | dev-cluster-autoscaler-role |

#Worker Nodes

| Node | Status | Version |
|------|--------|---------|
| ip-10-0-0-5.ec2.internal | Ready | v1.31.13-eks-ecaa3a6 |
| ip-10-0-1-233.ec2.internal | Ready | v1.31.13-eks-ecaa3a6 |

Parameters

#Deployment Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `Environment` | No | `dev` | Environment name (`dev`, `staging`, `prod`) |
| `S3BucketName` | No | auto-generated | Explicit bucket name; blank = `eks-upgrade-automation-{AccountId}-{Region}` |
| `GitHubOrg` | Yes | - | GitHub organization or username |
| `GitHubRepo` | No | `automate-eks-upgrades` | GitHub repository name |
| `CreateOIDCProvider` | No | `true` | Set `false` if your account already has a GitHub OIDC provider |

#EKS Cluster Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `EKSClusterVersion` | No | `1.31` | Kubernetes version for the dev cluster |
| `VpcCidr` | No | `10.0.0.0/16` | CIDR block for the VPC |
| `NodeInstanceType` | No | `t3.medium` | EC2 instance type for worker nodes |
| `NodeDesiredSize` | No | `2` | Desired number of worker nodes |
| `NodeMinSize` | No | `1` | Minimum number of worker nodes |
| `NodeMaxSize` | No | `4` | Maximum number of worker nodes |

Deploy via CLI (One-Time Setup)

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

Deploy via GitHub Actions

Run the Bootstrap Base Infrastructure workflow manually:

Actions > Bootstrap Base Infrastructure > Run workflow

Or it runs automatically as the first step of the Deploy EKS Upgrade Automation workflow.

Read Stack Outputs

After deployment, retrieve the outputs you need for GitHub configuration:

```bash
aws cloudformation describe-stacks \
  --stack-name eks-upgrade-bootstrap \
  --query 'Stacks[0].Outputs'
```

Key outputs:
- ArtifactBucketName — set as GitHub variable `S3_BUCKET` (current: eks-upgrade-automation-156041437006-us-east-1)
- DeployerRoleArn — set as GitHub secret `AWS_ROLE_ARN`
- EKSClusterName — the dev cluster the automation will manage (current: dev-dev-cluster)
- EKSClusterEndpoint — API endpoint for kubectl access
- NodeGroupName — the managed node group the automation will update (current: dev-dev-nodegroup)
- ClusterAutoscalerRoleArn — IAM role for the Cluster Autoscaler

Configure GitHub Repository

After deploying the bootstrap stack, configure these in your GitHub repository:

Secrets (Settings > Secrets and variables > Actions > Secrets):

| Secret | Value |
|--------|-------|
| `AWS_ROLE_ARN` | `DeployerRoleArn` output from bootstrap stack |
| `AWS_ACCESS_KEY_ID` | IAM access key (for bootstrap job only) |
| `AWS_SECRET_ACCESS_KEY` | IAM secret key (for bootstrap job only) |
| `AWS_REGION` | AWS region (e.g., `us-east-1`) |

Variables (Settings > Secrets and variables > Actions > Variables):

| Variable | Value |
|----------|-------|
| `AWS_REGION` | AWS region (e.g., `us-east-1`) |
| `S3_BUCKET` | `ArtifactBucketName` output from bootstrap stack |
| `NOTIFICATION_EMAIL` | Email for SNS notifications |

Verify the EKS Cluster

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

Deploy Cluster Autoscaler

After the bootstrap stack is deployed and kubectl is configured:

```bash
kubectl apply -f k8s/cluster-autoscaler.yaml
kubectl get pods -n kube-system -l app.kubernetes.io/name=cluster-autoscaler
kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler --tail=20
```

The autoscaler uses ASG tag-based auto-discovery (`k8s.io/cluster-autoscaler/enabled`, `k8s.io/cluster-autoscaler/dev-dev-cluster`) and scales the node group between 1 and 4 nodes.

Security Notes

- The S3 bucket enforces HTTPS-only access and has versioning enabled
- The OIDC provider eliminates the need for long-lived AWS credentials in the deploy job
- The deployer policy uses scoped resource ARNs (not wildcards) wherever possible
- The `iam/deployer-policy.json` file is a standalone copy for manual use; the authoritative version is in the CloudFormation template
- The EKS cluster has both public and private API endpoints enabled
- The node group role includes Cluster Autoscaler permissions for ASG management

Cost Estimates

| Resource | Approximate Monthly Cost |
|----------|-------------------------|
| EKS Control Plane | ~$73.00 |
| EC2 Nodes (2x t3.medium) | ~$60.00 |
| VPC / Networking | Free |
| S3 (artifacts) | ~$0.03 |
| IAM / OIDC | Free |
| Total | ~$133/month |

To reduce costs, scale the node group down when not testing:
```bash
aws eks update-nodegroup-config \
  --cluster-name dev-dev-cluster \
  --nodegroup-name dev-dev-nodegroup \
  --scaling-config desiredSize=1,minSize=1,maxSize=4
```

Cleanup

To delete the bootstrap stack and all its resources:

```bash
# Remove Cluster Autoscaler from the cluster first
kubectl delete -f k8s/cluster-autoscaler.yaml

# Delete the application stack first (if deployed)
aws cloudformation delete-stack --stack-name eks-addon-management

# Empty the S3 bucket (required before deletion)
aws s3 rm s3://eks-upgrade-automation-156041437006-us-east-1 --recursive

# Delete the bootstrap stack (EKS cluster, VPC, IAM, etc.)
aws cloudformation delete-stack --stack-name eks-upgrade-bootstrap

# Wait for deletion
aws cloudformation wait stack-delete-complete --stack-name eks-upgrade-bootstrap
```

Note: The S3 bucket has `DeletionPolicy: Retain` so it won't be deleted with the stack. Delete it manually if no longer needed:
```bash
aws s3 rb s3://eks-upgrade-automation-156041437006-us-east-1 --force
```
