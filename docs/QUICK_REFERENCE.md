# EKS Upgrade Automation - Quick Reference

Current State

| Component | Status |
|-----------|--------|
| Cluster (`dev-dev-cluster`) | ACTIVE, K8s v1.31 |
| Nodes (2x t3.medium) | Ready, v1.31.13 |
| Cluster Autoscaler | Running, v1.31.1 |
| Auto-Upgrade | Enabled |
| Notifications | olisa.arinze@aol.com (Confirmed) |
| S3 Bucket | eks-upgrade-automation-156041437006-us-east-1 |
| Region | us-east-1 |

Bootstrap (One-Time)

#Deploy Bootstrap Stack
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

#Get Bootstrap Outputs
```bash
aws cloudformation describe-stacks \
  --stack-name eks-upgrade-bootstrap \
  --query 'Stacks[0].Outputs'
```

Application Deployment

#Using GitHub Actions
Push to `main` or trigger manually via Actions > Deploy EKS Upgrade Automation > Run workflow.

#Using Deployment Script
```bash
./deploy.sh eks-upgrade-automation-156041437006-us-east-1 us-east-1 olisa.arinze@aol.com true
```

#Manual Deployment
```bash
# 1. Set variables
export S3_BUCKET=eks-upgrade-automation-156041437006-us-east-1
export AWS_REGION=us-east-1
export NOTIFICATION_EMAIL=olisa.arinze@aol.com
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
    ParameterKey=EnableAutoUpgrade,ParameterValue=true \
    ParameterKey=LambdaCodeBucket,ParameterValue=${S3_BUCKET} \
    ParameterKey=LambdaCodePrefix,ParameterValue=${LAMBDA_CODE_PREFIX} \
  --capabilities CAPABILITY_IAM \
  --region ${AWS_REGION}

# 5. Clean up
rm -f code.zip nodegroup_code.zip
```

Cluster Autoscaler

#Deploy
```bash
aws eks update-kubeconfig --name dev-dev-cluster --region us-east-1
kubectl apply -f k8s/cluster-autoscaler.yaml
```

#Check Status
```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=cluster-autoscaler
kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler --tail=20
```

#Restart
```bash
kubectl delete pod -n kube-system -l app.kubernetes.io/name=cluster-autoscaler
```

Testing

#Test Addon Lambda
```bash
aws lambda invoke \
  --function-name eks-version-checker \
  --region us-east-1 \
  response.json && cat response.json | jq '.'
```

#Test Node Group Lambda
```bash
aws lambda invoke \
  --function-name eks-nodegroup-version-manager \
  --region us-east-1 \
  response-nodegroup.json && cat response-nodegroup.json | jq '.'
```

#View Logs
```bash
aws logs tail /aws/lambda/eks-version-checker --region us-east-1 --follow
aws logs tail /aws/lambda/eks-nodegroup-version-manager --region us-east-1 --follow
```

Stack Management

#Check Stack Status
```bash
# Bootstrap stack
aws cloudformation describe-stacks --stack-name eks-upgrade-bootstrap --query 'Stacks[0].StackStatus'

# Application stack
aws cloudformation describe-stacks --stack-name eks-addon-management --query 'Stacks[0].StackStatus'
```

#List All Resources
```bash
# Bootstrap resources (19)
aws cloudformation describe-stack-resources --stack-name eks-upgrade-bootstrap \
  --query "StackResources[].{Resource:LogicalResourceId,Type:ResourceType,Status:ResourceStatus}" --output table

# Application resources (10)
aws cloudformation describe-stack-resources --stack-name eks-addon-management \
  --query "StackResources[].{Resource:LogicalResourceId,Type:ResourceType,Status:ResourceStatus}" --output table
```

#Check Cluster and Nodes
```bash
aws eks describe-cluster --name dev-dev-cluster --query "cluster.{Status:status,Version:version}"
kubectl get nodes -o wide
```

#Delete Stacks
```bash
# Remove Cluster Autoscaler first
kubectl delete -f k8s/cluster-autoscaler.yaml

# Delete application stack
aws cloudformation delete-stack --stack-name eks-addon-management --region us-east-1

# Empty S3 bucket then delete bootstrap
aws s3 rm s3://eks-upgrade-automation-156041437006-us-east-1 --recursive
aws cloudformation delete-stack --stack-name eks-upgrade-bootstrap --region us-east-1
```

Cluster Tagging

Tag development clusters with:
```yaml
Environment: dev
# or
Env: development
```

Or include "dev" in cluster name: `my-dev-cluster`

Schedule

- Addon Lambda: Fridays at 5 PM UTC (17:00)
- Node Group Lambda: Fridays at 6 PM UTC (18:00)
- Cluster Autoscaler: Continuous (evaluates every ~10 seconds)

Scale Node Group

```bash
# Scale down to save costs
aws eks update-nodegroup-config \
  --cluster-name dev-dev-cluster \
  --nodegroup-name dev-dev-nodegroup \
  --scaling-config desiredSize=1,minSize=1,maxSize=4

# Scale up for testing
aws eks update-nodegroup-config \
  --cluster-name dev-dev-cluster \
  --nodegroup-name dev-dev-nodegroup \
  --scaling-config desiredSize=2,minSize=1,maxSize=4
```

Force Node Group Update

If PDB blocks update:
```bash
aws eks update-nodegroup-version \
  --cluster-name dev-dev-cluster \
  --nodegroup-name dev-dev-nodegroup \
  --force
```

Troubleshooting

#Bootstrap Stack Fails
- Check IAM permissions for CloudFormation, IAM, S3
- If OIDC provider exists, re-deploy with `CreateOIDCProvider=false`
- Check: `aws cloudformation describe-stack-events --stack-name eks-upgrade-bootstrap`

#No Notifications
1. Confirm SNS subscription (check email)
2. Check Lambda permissions
3. Check CloudWatch logs
4. Verify cluster tags

#Lambda Timeout
- Addon Lambda: 120 seconds
- Node Group Lambda: 300 seconds
- Check CloudWatch logs for bottlenecks

#Autoscaler Not Scaling
1. Check logs: `kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler`
2. Verify ASG tags: `k8s.io/cluster-autoscaler/enabled`, `k8s.io/cluster-autoscaler/dev-dev-cluster`
3. Check node group role has autoscaling permissions

Files

| File | Description |
|------|-------------|
| `cfn/initial-resources.yaml` | Bootstrap stack (S3, VPC, EKS, OIDC, deployer role, autoscaler IAM) |
| `template.yaml` | Application CloudFormation template |
| `scripts/code.py` | Cluster + addon management Lambda |
| `scripts/nodegroup_code.py` | Node group management Lambda |
| `k8s/cluster-autoscaler.yaml` | Cluster Autoscaler manifest |
| `iam/deployer-policy.json` | Standalone deployer policy |
| `deploy.sh` | CLI deployment script |
| `.github/workflows/deploy.yml` | Main CI/CD pipeline |
| `.github/workflows/predeploy.yml` | Bootstrap reusable workflow |
