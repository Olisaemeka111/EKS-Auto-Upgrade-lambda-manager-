# EKS Upgrade Automation - Deployment Guide

## Prerequisites

1. AWS CLI installed and configured with appropriate credentials
2. An AWS account with permissions to create CloudFormation stacks, Lambda functions, IAM roles, SNS topics, EventBridge schedules, and S3 buckets
3. At least one EKS cluster in your account (tagged as a development cluster)

## Step 1: Deploy Bootstrap Infrastructure

The bootstrap stack must be deployed **before** the application stack. It creates the S3 bucket, GitHub OIDC provider, and deployer IAM role.

See [INITIAL_RESOURCES.md](./INITIAL_RESOURCES.md) for full details.

### Quick Bootstrap (CLI)

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

### Read Bootstrap Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name eks-upgrade-bootstrap \
  --query 'Stacks[0].Outputs'
```

Save these values:
- **ArtifactBucketName** — your S3 bucket
- **DeployerRoleArn** — your GitHub Actions role

## Step 2: Deploy the Application Stack

### Option A: GitHub Actions (Recommended)

See the [README](../README.md#quick-start) for GitHub Actions setup.

### Option B: Using the Deployment Script

```bash
# Make script executable (if not already)
chmod +x deploy.sh

# Deploy with default settings (no auto-upgrade)
./deploy.sh YOUR-BUCKET-NAME us-east-1 your-email@example.com false

# Deploy with auto-upgrade enabled
./deploy.sh YOUR-BUCKET-NAME us-east-1 your-email@example.com true

# Non-interactive mode (for CI/CD pipelines)
./deploy.sh YOUR-BUCKET-NAME us-east-1 your-email@example.com false --non-interactive
```

The script will:
- Package Lambda functions from `scripts/` into zip files
- Upload Lambda packages to S3
- Upload the CloudFormation template to S3
- Create or update the CloudFormation stack
- Wait for completion
- Display next steps

### Option C: Manual Deployment

```bash
# 1. Set your configuration (use values from bootstrap outputs)
export S3_BUCKET=YOUR-BUCKET-NAME
export AWS_REGION=us-east-1
export NOTIFICATION_EMAIL=your-email@example.com
export LAMBDA_CODE_PREFIX=eks-addon-management/lambda

# 2. Package and upload Lambda functions
cd scripts
zip -j ../code.zip code.py
zip -j ../nodegroup_code.zip nodegroup_code.py
cd ..

aws s3 cp code.zip s3://${S3_BUCKET}/${LAMBDA_CODE_PREFIX}/code.zip --region ${AWS_REGION}
aws s3 cp nodegroup_code.zip s3://${S3_BUCKET}/${LAMBDA_CODE_PREFIX}/nodegroup_code.zip --region ${AWS_REGION}

# 3. Upload template to S3
aws s3 cp template.yaml s3://${S3_BUCKET}/eks-addon-management/template.yaml --region ${AWS_REGION}

# 4. Deploy stack
aws cloudformation create-stack \
  --stack-name eks-addon-management \
  --template-url https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/eks-addon-management/template.yaml \
  --parameters \
    ParameterKey=NotificationEmail,ParameterValue=${NOTIFICATION_EMAIL} \
    ParameterKey=EnableAutoUpgrade,ParameterValue=false \
    ParameterKey=LambdaCodeBucket,ParameterValue=${S3_BUCKET} \
    ParameterKey=LambdaCodePrefix,ParameterValue=${LAMBDA_CODE_PREFIX} \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}

# 5. Wait for stack creation to complete
aws cloudformation wait stack-create-complete \
  --stack-name eks-addon-management \
  --region ${AWS_REGION}

# 6. Clean up local zip files
rm -f code.zip nodegroup_code.zip

echo "Stack created successfully! Check your email to confirm SNS subscription."
```

## Application Parameter Details

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `NotificationEmail` | Yes | - | Email address to receive SNS notifications |
| `EnableAutoUpgrade` | No | `false` | Set to `true` to enable automatic cluster upgrades for dev clusters |
| `LambdaCodeBucket` | Yes | - | S3 bucket containing Lambda code packages |
| `LambdaCodePrefix` | No | `eks-addon-management/lambda` | S3 key prefix for Lambda code packages |

## Post-Deployment Steps

### 1. Confirm SNS Email Subscription

After deployment, you'll receive an email from AWS SNS. Click the confirmation link to start receiving notifications.

### 2. Verify Stack Creation

```bash
aws cloudformation describe-stacks \
  --stack-name eks-addon-management \
  --region ${AWS_REGION} \
  --query 'Stacks[0].StackStatus'

aws cloudformation describe-stacks \
  --stack-name eks-addon-management \
  --region ${AWS_REGION} \
  --query 'Stacks[0].Outputs'
```

### 3. Test Lambda Functions

```bash
# Test addon management Lambda
aws lambda invoke \
  --function-name eks-version-checker \
  --region ${AWS_REGION} \
  response.json && cat response.json | jq '.'

# Test node group management Lambda
aws lambda invoke \
  --function-name eks-nodegroup-version-manager \
  --region ${AWS_REGION} \
  response-nodegroup.json && cat response-nodegroup.json | jq '.'
```

### 4. Check Lambda Logs

```bash
aws logs tail /aws/lambda/eks-version-checker --region ${AWS_REGION} --follow
aws logs tail /aws/lambda/eks-nodegroup-version-manager --region ${AWS_REGION} --follow
```

## Update Existing Stack

```bash
# 1. Package and upload Lambda functions
cd scripts
zip -j ../code.zip code.py
zip -j ../nodegroup_code.zip nodegroup_code.py
cd ..

aws s3 cp code.zip s3://${S3_BUCKET}/${LAMBDA_CODE_PREFIX}/code.zip --region ${AWS_REGION}
aws s3 cp nodegroup_code.zip s3://${S3_BUCKET}/${LAMBDA_CODE_PREFIX}/nodegroup_code.zip --region ${AWS_REGION}
aws s3 cp template.yaml s3://${S3_BUCKET}/eks-addon-management/template.yaml --region ${AWS_REGION}

# 2. Update stack
aws cloudformation update-stack \
  --stack-name eks-addon-management \
  --template-url https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/eks-addon-management/template.yaml \
  --parameters \
    ParameterKey=NotificationEmail,ParameterValue=${NOTIFICATION_EMAIL} \
    ParameterKey=EnableAutoUpgrade,ParameterValue=false \
    ParameterKey=LambdaCodeBucket,ParameterValue=${S3_BUCKET} \
    ParameterKey=LambdaCodePrefix,ParameterValue=${LAMBDA_CODE_PREFIX} \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}

# 3. Clean up
rm -f code.zip nodegroup_code.zip
```

## Execution Schedule

- **Addon Lambda**: Runs Fridays at 5 PM UTC (17:00)
- **Node Group Lambda**: Runs Fridays at 6 PM UTC (18:00) — 1 hour delay

This delay ensures addons are updated before node groups are replaced.

## Development Cluster Identification

The Lambda functions identify development clusters using:
- Tag `Environment` or `environment` or `Env` containing "dev" or "development"
- Cluster name containing "dev" or "development"

## Cost Estimates

### Monthly Costs (Approximate)
- **Lambda Execution**: ~$0.20/month
- **CloudWatch Logs**: ~$0.50/month
- **SNS**: ~$0.50/month
- **EventBridge Scheduler**: Free tier
- **S3 (artifacts)**: ~$0.03/month
- **Total**: ~$1.23/month

Actual costs may vary based on number of clusters, addons, node groups, and log retention.
