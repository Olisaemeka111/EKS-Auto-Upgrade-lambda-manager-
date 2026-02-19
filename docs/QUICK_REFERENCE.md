# EKS Upgrade Automation - Quick Reference

## Bootstrap (One-Time)

### Deploy Bootstrap Stack
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

### Get Bootstrap Outputs
```bash
aws cloudformation describe-stacks \
  --stack-name eks-upgrade-bootstrap \
  --query 'Stacks[0].Outputs'
```

## Application Deployment

### Using GitHub Actions
Push to `main` or trigger manually via **Actions > Deploy EKS Upgrade Automation > Run workflow**.

### Using Deployment Script
```bash
./deploy.sh YOUR-BUCKET-NAME us-east-1 your-email@example.com false
```

### Manual Deployment
```bash
# 1. Set variables (use bootstrap output for S3_BUCKET)
export S3_BUCKET=YOUR-BUCKET-NAME
export AWS_REGION=us-east-1
export NOTIFICATION_EMAIL=your-email@example.com
export LAMBDA_CODE_PREFIX=eks-addon-management/lambda

# 2. Package and upload Lambda code
cd scripts && zip -j ../code.zip code.py && zip -j ../nodegroup_code.zip nodegroup_code.py && cd ..
aws s3 cp code.zip s3://${S3_BUCKET}/${LAMBDA_CODE_PREFIX}/code.zip --region ${AWS_REGION}
aws s3 cp nodegroup_code.zip s3://${S3_BUCKET}/${LAMBDA_CODE_PREFIX}/nodegroup_code.zip --region ${AWS_REGION}

# 3. Upload template
aws s3 cp template.yaml s3://${S3_BUCKET}/eks-addon-management/template.yaml --region ${AWS_REGION}

# 4. Deploy
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

# 5. Clean up
rm -f code.zip nodegroup_code.zip
```

## Testing

### Test Addon Lambda
```bash
aws lambda invoke \
  --function-name eks-version-checker \
  --region ${AWS_REGION} \
  response.json && cat response.json | jq '.'
```

### Test Node Group Lambda
```bash
aws lambda invoke \
  --function-name eks-nodegroup-version-manager \
  --region ${AWS_REGION} \
  response-nodegroup.json && cat response-nodegroup.json | jq '.'
```

### View Logs
```bash
aws logs tail /aws/lambda/eks-version-checker --region ${AWS_REGION} --follow
aws logs tail /aws/lambda/eks-nodegroup-version-manager --region ${AWS_REGION} --follow
```

## Stack Management

### Check Stack Status
```bash
# Bootstrap stack
aws cloudformation describe-stacks --stack-name eks-upgrade-bootstrap --query 'Stacks[0].StackStatus'

# Application stack
aws cloudformation describe-stacks --stack-name eks-addon-management --query 'Stacks[0].StackStatus'
```

### Delete Stacks
```bash
# Delete application stack first
aws cloudformation delete-stack --stack-name eks-addon-management --region ${AWS_REGION}

# Then bootstrap (bucket has DeletionPolicy: Retain)
aws cloudformation delete-stack --stack-name eks-upgrade-bootstrap --region ${AWS_REGION}
```

## Cluster Tagging

Tag development clusters with:
```yaml
Environment: dev
# or
Env: development
```

Or include "dev" in cluster name: `my-dev-cluster`

## Schedule

- **Addon Lambda**: Fridays at 5 PM UTC (17:00)
- **Node Group Lambda**: Fridays at 6 PM UTC (18:00)

## Force Node Group Update

If PDB blocks update:
```bash
aws eks update-nodegroup-version \
  --cluster-name CLUSTER-NAME \
  --nodegroup-name NODEGROUP-NAME \
  --force
```

## Troubleshooting

### Bootstrap Stack Fails
- Check IAM permissions for CloudFormation, IAM, S3
- If OIDC provider exists, re-deploy with `CreateOIDCProvider=false`
- Check: `aws cloudformation describe-stack-events --stack-name eks-upgrade-bootstrap`

### No Notifications
1. Confirm SNS subscription (check email)
2. Check Lambda permissions
3. Check CloudWatch logs
4. Verify cluster tags

### Lambda Timeout
- Addon Lambda: 120 seconds
- Node Group Lambda: 300 seconds
- Check CloudWatch logs for bottlenecks

## Files

| File | Description |
|------|-------------|
| `cfn/initial-resources.yaml` | Bootstrap stack (S3, OIDC, deployer role) |
| `template.yaml` | Application CloudFormation template |
| `scripts/code.py` | Cluster + addon management Lambda |
| `scripts/nodegroup_code.py` | Node group management Lambda |
| `iam/deployer-policy.json` | Standalone deployer policy |
| `deploy.sh` | CLI deployment script |
| `.github/workflows/deploy.yml` | Main CI/CD pipeline |
| `.github/workflows/predeploy.yml` | Bootstrap reusable workflow |
