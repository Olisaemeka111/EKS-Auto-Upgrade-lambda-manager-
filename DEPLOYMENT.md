# EKS Addon Management - Deployment Guide

> **Important**: This CloudFormation template is 55,594 bytes and exceeds the 51,200 byte inline limit. You must upload it to S3 before deployment. See the Quick Start section below.

## Prerequisites

1. AWS CLI installed and configured with appropriate credentials
2. An AWS account with permissions to create CloudFormation stacks, Lambda functions, IAM roles, SNS topics, and EventBridge schedules
3. At least one EKS cluster in your account (preferably tagged as a development cluster)

## Deployment Commands

### Option A: Using the Deployment Script (Recommended)

The easiest way to deploy is using the provided `deploy.sh` script:

```bash
# Make script executable (if not already)
chmod +x deploy.sh

# Deploy with default settings (no auto-upgrade)
./deploy.sh YOUR-BUCKET-NAME us-east-1 your-email@example.com false

# Deploy with auto-upgrade enabled
./deploy.sh YOUR-BUCKET-NAME us-east-1 your-email@example.com true
```

The script will:
- Upload the template to S3
- Create or update the CloudFormation stack
- Wait for completion
- Display next steps

### Option B: Manual Deployment

### Quick Start

```bash
# 1. Set your configuration
export S3_BUCKET=YOUR-BUCKET-NAME
export AWS_REGION=us-east-1
export NOTIFICATION_EMAIL=your-email@example.com

# 2. Upload template to S3
aws s3 cp template.yaml s3://${S3_BUCKET}/eks-addon-management/template.yaml --region ${AWS_REGION}

# 3. Deploy stack (with auto-upgrade disabled by default)
aws cloudformation create-stack \
  --stack-name eks-addon-management \
  --template-url https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/eks-addon-management/template.yaml \
  --parameters \
    ParameterKey=NotificationEmail,ParameterValue=${NOTIFICATION_EMAIL} \
    ParameterKey=EnableAutoUpgrade,ParameterValue=false \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}

# 4. Wait for stack creation to complete
aws cloudformation wait stack-create-complete \
  --stack-name eks-addon-management \
  --region ${AWS_REGION}

echo "Stack created successfully! Check your email to confirm SNS subscription."
```

### Prerequisites for Deployment

The CloudFormation template is larger than 51,200 bytes and must be uploaded to S3 before deployment. You'll need:
- An S3 bucket in the same region where you're deploying
- Permissions to upload to S3 and create CloudFormation stacks

If you don't have an S3 bucket, create one:

```bash
# Create S3 bucket (bucket names must be globally unique)
export S3_BUCKET=eks-addon-management-$(date +%s)
export AWS_REGION=us-east-1

aws s3 mb s3://${S3_BUCKET} --region ${AWS_REGION}
```

### Step 1: Upload Template to S3

Replace `YOUR-BUCKET-NAME` with your S3 bucket name:

```bash
# Set your S3 bucket name and region
export S3_BUCKET=YOUR-BUCKET-NAME
export AWS_REGION=us-east-1

# Upload template to S3
aws s3 cp template.yaml s3://${S3_BUCKET}/eks-addon-management/template.yaml --region ${AWS_REGION}
```

### Step 2: Deploy Stack

#### Option 1: Deploy with Default Settings (No Auto-Upgrade)

```bash
aws cloudformation create-stack \
  --stack-name eks-addon-management \
  --template-url https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/eks-addon-management/template.yaml \
  --parameters \
    ParameterKey=NotificationEmail,ParameterValue=your-email@example.com \
    ParameterKey=EnableAutoUpgrade,ParameterValue=false \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}
```

#### Option 2: Deploy with Auto-Upgrade Enabled

```bash
aws cloudformation create-stack \
  --stack-name eks-addon-management \
  --template-url https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/eks-addon-management/template.yaml \
  --parameters \
    ParameterKey=NotificationEmail,ParameterValue=your-email@example.com \
    ParameterKey=EnableAutoUpgrade,ParameterValue=true \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}
```

#### Option 3: Update Existing Stack

When updating, you must re-upload the template to S3 first:

```bash
# Upload updated template
aws s3 cp template.yaml s3://${S3_BUCKET}/eks-addon-management/template.yaml --region ${AWS_REGION}

# Update stack
aws cloudformation update-stack \
  --stack-name eks-addon-management \
  --template-url https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/eks-addon-management/template.yaml \
  --parameters \
    ParameterKey=NotificationEmail,ParameterValue=your-email@example.com \
    ParameterKey=EnableAutoUpgrade,ParameterValue=false \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}
```

## Parameter Details

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `NotificationEmail` | Yes | - | Email address to receive SNS notifications about cluster and addon updates |
| `EnableAutoUpgrade` | No | `false` | Set to `true` to enable automatic cluster upgrades for development clusters |

## Post-Deployment Steps

### 1. Confirm SNS Email Subscription

After deployment, you'll receive an email from AWS SNS. Click the confirmation link to start receiving notifications.

### 2. Verify Stack Creation

```bash
# Check stack status
aws cloudformation describe-stacks \
  --stack-name eks-addon-management \
  --region ${AWS_REGION} \
  --query 'Stacks[0].StackStatus'

# Get stack outputs
aws cloudformation describe-stacks \
  --stack-name eks-addon-management \
  --region ${AWS_REGION} \
  --query 'Stacks[0].Outputs'
```

### 3. Test Lambda Function Manually

```bash
# Get Lambda function name
FUNCTION_ARN=$(aws cloudformation describe-stacks \
  --stack-name eks-addon-management \
  --region ${AWS_REGION} \
  --query 'Stacks[0].Outputs[?OutputKey==`LambdaFunctionArn`].OutputValue' \
  --output text)

# Invoke Lambda function
aws lambda invoke \
  --function-name eks-version-checker \
  --region ${AWS_REGION} \
  --log-type Tail \
  response.json

# View response
cat response.json | jq '.'
```

### 4. Check Lambda Logs

```bash
# Get recent logs
aws logs tail /aws/lambda/eks-version-checker \
  --region ${AWS_REGION} \
  --follow
```

## What the Lambda Function Does

### Cluster Processing
1. Lists all EKS clusters in the account
2. Filters for development clusters (based on tags or name)
3. Checks cluster version against latest available version
4. Checks upgrade readiness insights
5. Sends SNS notifications about cluster status

### Addon Processing (NEW)
For each development cluster, the function:
1. **Discovers all addons** (vpc-cni, kube-proxy, coredns, aws-ebs-csi-driver, etc.)
2. **Extracts authentication configuration** (Pod Identity, IRSA, or none)
3. **Checks for addon updates** by comparing current version with latest compatible version
4. **Updates addons automatically** while preserving authentication settings
5. **Sends SNS notifications** for each addon:
   - Up-to-date: Addon is already at latest version
   - Updated: Addon update initiated successfully
   - Failed: Addon update failed with error details

### Scheduled Execution
- Runs daily at midnight UTC (configurable via EventBridge Schedule)
- Can be triggered manually using the Lambda invoke command above

## Development Cluster Identification

The Lambda function identifies development clusters using:
- Tag `Environment` or `environment` or `Env` containing "dev" or "development"
- Cluster name containing "dev" or "development"

Example tags:
```yaml
Environment: dev
Environment: development
Env: dev-us-east-1
```

## Notification Examples

### Cluster Notifications
- **Up-to-date**: "EKS Cluster is up to date - my-dev-cluster"
- **Upgrade Available**: "EKS Cluster Upgrade Available for my-dev-cluster"
- **Upgrade Blocked**: "EKS Cluster Upgrade Blocked due to Potential Issue - my-dev-cluster"
- **Upgrade Initiated**: "EKS Cluster Upgrade Initiated - my-dev-cluster"

### Addon Notifications (NEW)
- **Up-to-date**: "EKS Addon Summary - golden - All Up-to-Date"


- **Updated**: "EKS Addon Summary - golden - 2 Updated"
- **Failed**: "EKS Addon Summary - golden - 1 Failed"

### Node Group Notifications (NEW)
- **Up-to-date**: "EKS Node Group Summary - golden - All Up-to-Date"
- **Updating**: "EKS Node Group Summary - golden - 2 Updating"
- **Failed**: "EKS Node Group Summary - golden - 1 Failed"

## Node Group Management (NEW)

### Overview
The solution now includes a separate Lambda function that manages EKS managed node group versions. This function runs 1 hour after the addon management Lambda to ensure addons are updated before node groups are replaced.

### What the Node Group Lambda Does
For each development cluster, the function:
1. **Discovers all managed node groups** in the cluster
2. **Checks node group versions** against the cluster's Kubernetes version
3. **Updates node groups** to match cluster version with latest AMI release
4. **Respects Pod Disruption Budgets (PDBs)** by never using the force flag
5. **Sends consolidated notifications** with all node group results

### Execution Schedule
- **Addon Lambda**: Runs Fridays at 5 PM UTC (17:00)
- **Node Group Lambda**: Runs Fridays at 6 PM UTC (18:00) - 1 hour after addon Lambda

This delay ensures that:
- Cluster addons are updated first
- Addons are compatible before nodes are replaced
- Node updates don't interfere with addon updates

### Testing Node Group Lambda Manually

```bash
# Get Node Group Lambda function ARN
NODEGROUP_FUNCTION_ARN=$(aws cloudformation describe-stacks \
  --stack-name eks-addon-management \
  --region ${AWS_REGION} \
  --query 'Stacks[0].Outputs[?OutputKey==`NodeGroupLambdaFunctionArn`].OutputValue' \
  --output text)

# Invoke Node Group Lambda function
aws lambda invoke \
  --function-name eks-nodegroup-version-manager \
  --region ${AWS_REGION} \
  --log-type Tail \
  response-nodegroup.json

# View response
cat response-nodegroup.json | jq '.'
```

### Node Group Update Behavior

#### Successful Update
When a node group update is initiated successfully:
- Status: "updating"
- Email includes update ID for tracking
- Node group will gradually replace nodes with new version

#### Failed Update (PDB Blocking)
When a node group update fails due to Pod Disruption Budget:
- Status: "failed"
- Email includes error message
- Email provides command to force update manually:

```bash
aws eks update-nodegroup-version \
  --cluster-name golden \
  --nodegroup-name my-nodegroup \
  --force
```

**Important**: Only use `--force` if you understand the impact on your workloads. Forcing an update bypasses PDB protection and may cause service disruptions.

#### Up-to-Date Node Groups
When a node group is already at the cluster version with latest AMI:
- Status: "up_to_date"
- No action taken
- Listed in "UP-TO-DATE NODE GROUPS" section of email

### Node Group Notification Example

```
Subject: EKS Node Group Summary - golden - 1 Failed

Cluster: golden
Total Node Groups: 3
Up-to-Date: 1
Updating: 1
Failed: 1

============================================================

UPDATING NODE GROUPS:
------------------------------------------------------------
  Node Group: bottlerocket-ng
  Kubernetes Version: 1.33 → 1.34
  AMI Release: 1.52.0-abc123 → Latest
  Update ID: 0cd46031-ea0c-393d-955a-47a44871a583

FAILED NODE GROUPS:
------------------------------------------------------------
  Node Group: dolphins-az-a
  Current Version: 1.33
  Target Version: 1.34
  Error: PodEvictionFailure - Cannot evict pod due to PDB
  
  ACTION REQUIRED: If you want to force this update, run:
  aws eks update-nodegroup-version \
    --cluster-name golden \
    --nodegroup-name dolphins-az-a \
    --force

UP-TO-DATE NODE GROUPS:
------------------------------------------------------------
  dolphins-az-b (1.34, AMI: 1.53.0-def456)
```

## Architecture

### Lambda Functions
1. **eks-version-checker**: Manages cluster versions and addons
   - Timeout: 120 seconds
   - Runs: Fridays at 5 PM UTC
   
2. **eks-nodegroup-version-manager**: Manages node group versions
   - Timeout: 300 seconds (5 minutes)
   - Runs: Fridays at 6 PM UTC (1 hour after addon Lambda)

### IAM Permissions

#### Addon Management Lambda
- `eks:DescribeCluster`, `eks:ListClusters`
- `eks:DescribeClusterVersions`, `eks:UpdateClusterVersion`
- `eks:ListInsights`
- `eks:ListAddons`, `eks:DescribeAddon`, `eks:DescribeAddonVersions`, `eks:UpdateAddon`
- `eks:DescribePodIdentityAssociation`, `eks:UpdatePodIdentityAssociation`
- `iam:PassRole`, `iam:GetRole`
- `sns:Publish`

#### Node Group Management Lambda
- `eks:DescribeCluster`, `eks:ListClusters`
- `eks:ListNodegroups`, `eks:DescribeNodegroup`
- `eks:UpdateNodegroupVersion`
- `sns:Publish`

## Troubleshooting

### Template Size Error
If you see an error like "Member must have length less than or equal to 51200":
- This means you're trying to use `--template-body file://template.yaml` directly
- CloudFormation has a 51,200 byte limit for inline templates
- Solution: Upload the template to S3 first and use `--template-url` (see deployment commands above)

### Node Group Updates Failing with PDB Errors
If node group updates consistently fail due to Pod Disruption Budgets:
1. Review your PDB configurations to ensure they're not too restrictive
2. Consider temporarily relaxing PDB constraints during maintenance windows
3. Use the force flag manually if you need to proceed with the update:
   ```bash
   aws eks update-nodegroup-version \
     --cluster-name <cluster-name> \
     --nodegroup-name <nodegroup-name> \
     --force
   ```

### Lambda Timeout Issues
If the node group Lambda times out:
- Check CloudWatch logs for which operation is taking too long
- Consider increasing the timeout (currently 300 seconds)
- Verify network connectivity to EKS API endpoints

### No Notifications Received
1. Check SNS subscription is confirmed
2. Verify Lambda has permission to publish to SNS topic
3. Check CloudWatch logs for errors
4. Ensure development clusters are properly tagged

## Cost Estimates

### Monthly Costs (Approximate)
- **Lambda Execution**: ~$0.20/month (assuming weekly execution)
- **CloudWatch Logs**: ~$0.50/month (1 GB logs)
- **SNS**: ~$0.50/month (email notifications)
- **EventBridge Scheduler**: Free tier
- **Total**: ~$1.20/month

Actual costs may vary based on:
- Number of clusters
- Number of addons per cluster
- Number of node groups per cluster
- Lambda execution time
- Log retention settings
