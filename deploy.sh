#!/bin/bash

# EKS Upgrade Automation - Deployment Script
# Packages Lambda code, uploads to S3, and deploys the CloudFormation stack.
#
# Usage:
#   ./deploy.sh <S3_BUCKET> <AWS_REGION> <NOTIFICATION_EMAIL> [ENABLE_AUTO_UPGRADE] [--non-interactive]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# Parse arguments
NON_INTERACTIVE=false
POSITIONAL_ARGS=()
for arg in "$@"; do
    case $arg in
        --non-interactive) NON_INTERACTIVE=true ;;
        *) POSITIONAL_ARGS+=("$arg") ;;
    esac
done

if [ ${#POSITIONAL_ARGS[@]} -lt 3 ]; then
    print_error "Usage: $0 <S3_BUCKET> <AWS_REGION> <NOTIFICATION_EMAIL> [ENABLE_AUTO_UPGRADE] [--non-interactive]"
    echo ""
    echo "Parameters:"
    echo "  S3_BUCKET           - S3 bucket name for template and Lambda code upload"
    echo "  AWS_REGION          - AWS region (e.g., us-east-1, eu-west-1)"
    echo "  NOTIFICATION_EMAIL  - Email address for SNS notifications"
    echo "  ENABLE_AUTO_UPGRADE - Enable auto-upgrade (true/false, default: false)"
    echo ""
    echo "Flags:"
    echo "  --non-interactive   - Skip confirmation prompts (for CI/CD)"
    exit 1
fi

S3_BUCKET="${POSITIONAL_ARGS[0]}"
AWS_REGION="${POSITIONAL_ARGS[1]}"
NOTIFICATION_EMAIL="${POSITIONAL_ARGS[2]}"
ENABLE_AUTO_UPGRADE="${POSITIONAL_ARGS[3]:-false}"

STACK_NAME="eks-addon-management"
TEMPLATE_FILE="template.yaml"
S3_TEMPLATE_KEY="eks-addon-management/template.yaml"
LAMBDA_CODE_PREFIX="eks-addon-management/lambda"

print_info "Starting deployment of EKS Upgrade Automation"
print_info "Configuration:"
echo "  S3 Bucket:          ${S3_BUCKET}"
echo "  AWS Region:         ${AWS_REGION}"
echo "  Notification Email: ${NOTIFICATION_EMAIL}"
echo "  Auto-Upgrade:       ${ENABLE_AUTO_UPGRADE}"
echo ""

# Verify required files exist
for file in "${TEMPLATE_FILE}" "scripts/code.py" "scripts/nodegroup_code.py"; do
    if [ ! -f "${file}" ]; then
        print_error "Required file '${file}' not found!"
        exit 1
    fi
done

# Package Lambda functions
print_info "Packaging Lambda functions..."
cd scripts
zip -j ../code.zip code.py
zip -j ../nodegroup_code.zip nodegroup_code.py
cd ..
print_info "Lambda packages created"

# Upload Lambda packages to S3
print_info "Uploading Lambda packages to S3..."
aws s3 cp code.zip "s3://${S3_BUCKET}/${LAMBDA_CODE_PREFIX}/code.zip" --region "${AWS_REGION}"
aws s3 cp nodegroup_code.zip "s3://${S3_BUCKET}/${LAMBDA_CODE_PREFIX}/nodegroup_code.zip" --region "${AWS_REGION}"
print_info "Lambda packages uploaded"

# Upload CloudFormation template to S3
print_info "Uploading CloudFormation template to S3..."
aws s3 cp "${TEMPLATE_FILE}" "s3://${S3_BUCKET}/${S3_TEMPLATE_KEY}" --region "${AWS_REGION}"

TEMPLATE_URL="https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/${S3_TEMPLATE_KEY}"
print_info "Template URL: ${TEMPLATE_URL}"
echo ""

# Clean up local zip files
rm -f code.zip nodegroup_code.zip

# Check if stack already exists
print_info "Checking if stack '${STACK_NAME}' exists..."
STACK_EXISTS=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query 'Stacks[0].StackName' \
    --output text 2>/dev/null || echo "")

CFN_PARAMS=(
    "ParameterKey=NotificationEmail,ParameterValue=${NOTIFICATION_EMAIL}"
    "ParameterKey=EnableAutoUpgrade,ParameterValue=${ENABLE_AUTO_UPGRADE}"
    "ParameterKey=LambdaCodeBucket,ParameterValue=${S3_BUCKET}"
    "ParameterKey=LambdaCodePrefix,ParameterValue=${LAMBDA_CODE_PREFIX}"
)

if [ -n "${STACK_EXISTS}" ]; then
    print_warning "Stack '${STACK_NAME}' already exists"

    if [ "${NON_INTERACTIVE}" = false ]; then
        read -p "Do you want to update the existing stack? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Deployment cancelled"
            exit 0
        fi
    fi

    print_info "Updating stack '${STACK_NAME}'..."
    aws cloudformation update-stack \
        --stack-name "${STACK_NAME}" \
        --template-url "${TEMPLATE_URL}" \
        --parameters "${CFN_PARAMS[@]}" \
        --capabilities CAPABILITY_IAM \
        --region "${AWS_REGION}" || {
        echo "No stack updates needed"
        exit 0
    }

    print_info "Waiting for stack update to complete..."
    aws cloudformation wait stack-update-complete \
        --stack-name "${STACK_NAME}" \
        --region "${AWS_REGION}"

    print_info "Stack updated successfully!"
else
    print_info "Creating new stack '${STACK_NAME}'..."
    aws cloudformation create-stack \
        --stack-name "${STACK_NAME}" \
        --template-url "${TEMPLATE_URL}" \
        --parameters "${CFN_PARAMS[@]}" \
        --capabilities CAPABILITY_IAM \
        --region "${AWS_REGION}"

    print_info "Waiting for stack creation to complete..."
    aws cloudformation wait stack-create-complete \
        --stack-name "${STACK_NAME}" \
        --region "${AWS_REGION}"

    print_info "Stack created successfully!"
fi

echo ""
print_info "Deployment completed!"
print_info "Next steps:"
echo "  1. Check your email (${NOTIFICATION_EMAIL}) and confirm the SNS subscription"
echo "  2. Verify stack outputs:"
echo "     aws cloudformation describe-stacks --stack-name ${STACK_NAME} --region ${AWS_REGION} --query 'Stacks[0].Outputs'"
echo "  3. Test the addon Lambda function:"
echo "     aws lambda invoke --function-name eks-version-checker --region ${AWS_REGION} response.json"
echo "  4. Test the node group Lambda function:"
echo "     aws lambda invoke --function-name eks-nodegroup-version-manager --region ${AWS_REGION} response-nodegroup.json"
