# EKS Addon Management - Quick Reference

## Deployment

### Using Deployment Script
```bash
./deploy.sh YOUR-BUCKET-NAME us-east-1 your-email@example.com false
```

### Manual Deployment
```bash
# 1. Set variables
export S3_BUCKET=YOUR-BUCKET-NAME
export AWS_REGION=us-east-1
export NOTIFICATION_EMAIL=your-email@example.com

# 2. Upload template
aws s3 cp template.yaml s3://${S3_BUCKET}/eks-addon-management/template.yaml --region ${AWS_REGION}

# 3. Deploy
aws cloudformation create-stack \
  --stack-name eks-addon-management \
  --template-url https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/eks-addon-management/template.yaml \
  --parameters \
    ParameterKey=NotificationEmail,ParameterValue=${NOTIFICATION_EMAIL} \
    ParameterKey=EnableAutoUpgrade,ParameterValue=false \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}
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
# Addon Lambda logs
aws logs tail /aws/lambda/eks-version-checker --region ${AWS_REGION} --follow

# Node Group Lambda logs
aws logs tail /aws/lambda/eks-nodegroup-version-manager --region ${AWS_REGION} --follow
```

## Stack Management

### Check Stack Status
```bash
aws cloudformation describe-stacks \
  --stack-name eks-addon-management \
  --region ${AWS_REGION} \
  --query 'Stacks[0].StackStatus'
```

### Get Stack Outputs
```bash
aws cloudformation describe-stacks \
  --stack-name eks-addon-management \
  --region ${AWS_REGION} \
  --query 'Stacks[0].Outputs'
```

### Update Stack
```bash
# 1. Upload updated template
aws s3 cp template.yaml s3://${S3_BUCKET}/eks-addon-management/template.yaml --region ${AWS_REGION}

# 2. Update stack
aws cloudformation update-stack \
  --stack-name eks-addon-management \
  --template-url https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/eks-addon-management/template.yaml \
  --parameters \
    ParameterKey=NotificationEmail,ParameterValue=${NOTIFICATION_EMAIL} \
    ParameterKey=EnableAutoUpgrade,ParameterValue=false \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}
```

### Delete Stack
```bash
aws cloudformation delete-stack \
  --stack-name eks-addon-management \
  --region ${AWS_REGION}
```

## Cluster Tagging

Tag development clusters with:
```yaml
Environment: dev
# or
Env: development
```

Or include "dev" in cluster name:
- `my-dev-cluster`
- `development-cluster`

## Schedule

- **Addon Lambda**: Fridays at 5 PM UTC (17:00)
- **Node Group Lambda**: Fridays at 6 PM UTC (18:00)

## Notification Types

### Cluster
- Up-to-date
- Upgrade available
- Upgrade blocked
- Upgrade initiated

### Addons
- All up-to-date
- X updated
- X failed

### Node Groups
- All up-to-date
- X updating
- X failed

## Force Node Group Update

If PDB blocks update:
```bash
aws eks update-nodegroup-version \
  --cluster-name CLUSTER-NAME \
  --nodegroup-name NODEGROUP-NAME \
  --force
```

## Troubleshooting

### Template Size Error
Upload to S3 first (template is 55,594 bytes, exceeds 51,200 limit)

### No Notifications
1. Confirm SNS subscription (check email)
2. Check Lambda permissions
3. Check CloudWatch logs
4. Verify cluster tags

### Lambda Timeout
- Addon Lambda: 120 seconds
- Node Group Lambda: 300 seconds
- Check CloudWatch logs for bottlenecks

## Cost Estimate

~$1.20/month:
- Lambda: $0.20
- CloudWatch: $0.50
- SNS: $0.50
- EventBridge: Free

## Files

- `template.yaml` - CloudFormation template
- `code.py` - Addon Lambda source
- `nodegroup_code.py` - Node Group Lambda source
- `deploy.sh` - Deployment script
- `DEPLOYMENT.md` - Full deployment guide
- `README.md` - Project overview
