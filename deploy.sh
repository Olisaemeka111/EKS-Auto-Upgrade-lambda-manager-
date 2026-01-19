#!/bin/bash

# EKS Addon Management - Deployment Script
# This script uploads the CloudFormation template to S3 and deploys the stack

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if required parameters are provided
if [ $# -lt 3 ]; then
    print_error "Usage: $0 <S3_BUCKET> <AWS_REGION> <NOTIFICATION_EMAIL> [ENABLE_AUTO_UPGRADE]"
    echo ""
    echo "Example:"
    echo "  $0 my-bucket us-east-1 admin@example.com false"
    echo ""
    echo "Parameters:"
    echo "  S3_BUCKET           - S3 bucket name for template upload"
    echo "  AWS_REGION          - AWS region (e.g., us-east-1, eu-west-1)"
    echo "  NOTIFICATION_EMAIL  - Email address for SNS notifications"
    echo "  ENABLE_AUTO_UPGRADE - Enable auto-upgrade (true/false, default: false)"
    exit 1
fi

S3_BUCKET=$1
AWS_REGION=$2
NOTIFICATION_EMAIL=$3
ENABLE_AUTO_UPGRADE=${4:-false}

STACK_NAME="eks-addon-management"
TEMPLATE_FILE="template.yaml"
S3_KEY="eks-addon-management/template.yaml"

print_info "Starting deployment of EKS Addon Management"
print_info "Configuration:"
echo "  S3 Bucket:          ${S3_BUCKET}"
echo "  AWS Region:         ${AWS_REGION}"
echo "  Notification Email: ${NOTIFICATION_EMAIL}"
echo "  Auto-Upgrade:       ${ENABLE_AUTO_UPGRADE}"
echo ""

# Check if template file exists
if [ ! -f "${TEMPLATE_FILE}" ]; then
    print_error "Template file '${TEMPLATE_FILE}' not found!"
    exit 1
fi

# Check template size
TEMPLATE_SIZE=$(wc -c < "${TEMPLATE_FILE}")
print_info "Template size: ${TEMPLATE_SIZE} bytes"

if [ ${TEMPLATE_SIZE} -gt 51200 ]; then
    print_warning "Template exceeds 51,200 byte limit (CloudFormation inline limit)"
    print_info "Will upload to S3 and use --template-url"
fi

# Upload template to S3
print_info "Uploading template to S3..."
aws s3 cp "${TEMPLATE_FILE}" "s3://${S3_BUCKET}/${S3_KEY}" --region "${AWS_REGION}"

if [ $? -ne 0 ]; then
    print_error "Failed to upload template to S3"
    exit 1
fi

TEMPLATE_URL="https://${S3_BUCKET}.s3.${AWS_REGION}.amazonaws.com/${S3_KEY}"
print_info "Template uploaded successfully"
print_info "Template URL: ${TEMPLATE_URL}"
echo ""

# Check if stack already exists
print_info "Checking if stack '${STACK_NAME}' exists..."
STACK_EXISTS=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query 'Stacks[0].StackName' \
    --output text 2>/dev/null || echo "")

if [ -n "${STACK_EXISTS}" ]; then
    print_warning "Stack '${STACK_NAME}' already exists"
    read -p "Do you want to update the existing stack? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Deployment cancelled"
        exit 0
    fi
    
    print_info "Updating stack '${STACK_NAME}'..."
    aws cloudformation update-stack \
        --stack-name "${STACK_NAME}" \
        --template-url "${TEMPLATE_URL}" \
        --parameters \
            ParameterKey=NotificationEmail,ParameterValue="${NOTIFICATION_EMAIL}" \
            ParameterKey=EnableAutoUpgrade,ParameterValue="${ENABLE_AUTO_UPGRADE}" \
        --capabilities CAPABILITY_IAM \
        --region "${AWS_REGION}"
    
    if [ $? -ne 0 ]; then
        print_error "Failed to update stack"
        exit 1
    fi
    
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
        --parameters \
            ParameterKey=NotificationEmail,ParameterValue="${NOTIFICATION_EMAIL}" \
            ParameterKey=EnableAutoUpgrade,ParameterValue="${ENABLE_AUTO_UPGRADE}" \
        --capabilities CAPABILITY_IAM \
        --region "${AWS_REGION}"
    
    if [ $? -ne 0 ]; then
        print_error "Failed to create stack"
        exit 1
    fi
    
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
