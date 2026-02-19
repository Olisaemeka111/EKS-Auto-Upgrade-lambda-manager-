"""
EKS Managed Node Group Version Management Lambda Function

This Lambda function automatically updates EKS managed node groups to match
the cluster's Kubernetes version and latest AMI release, while respecting
Pod Disruption Budgets (PDBs).
"""

import json
import os
import time
from typing import Dict, List, Optional
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
eks_client = boto3.client('eks')
sns_client = boto3.client('sns')

# Environment variables
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
ENABLE_AUTO_UPGRADE = os.environ.get('ENABLE_AUTO_UPGRADE', 'true').lower() == 'true'


def retry_with_backoff(func, *args, max_retries=3, **kwargs):
    """
    Retry a function with exponential backoff for API throttling.
    
    Args:
        func: Function to retry
        max_retries: Maximum number of retry attempts (default: 3)
        *args, **kwargs: Arguments to pass to the function
        
    Returns:
        Result from the function call
        
    Raises:
        Last exception if all retries fail
    """
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['Throttling', 'TooManyRequestsException', 'RequestLimitExceeded']:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    print(f"API throttled, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"Max retries reached for throttling")
                    raise
            else:
                raise


def get_cluster_nodegroups(cluster_name: str) -> List[Dict]:
    """
    Retrieve all managed node groups for a cluster with their configurations.
    
    Args:
        cluster_name: Name of the EKS cluster
        
    Returns:
        List of node group dictionaries with configuration details
    """
    try:
        # List all node groups
        response = retry_with_backoff(
            eks_client.list_nodegroups,
            clusterName=cluster_name
        )
        nodegroup_names = response.get('nodegroups', [])
        
        if not nodegroup_names:
            print(f"No managed node groups found in cluster {cluster_name}")
            return []
        
        # Get detailed information for each node group
        nodegroups = []
        for ng_name in nodegroup_names:
            try:
                ng_response = retry_with_backoff(
                    eks_client.describe_nodegroup,
                    clusterName=cluster_name,
                    nodegroupName=ng_name
                )
                ng_details = ng_response.get('nodegroup', {})
                
                nodegroups.append({
                    'nodegroup_name': ng_details.get('nodegroupName'),
                    'kubernetes_version': ng_details.get('version'),
                    'release_version': ng_details.get('releaseVersion'),
                    'status': ng_details.get('status'),
                    'launch_template': ng_details.get('launchTemplate')
                })
            except ClientError as e:
                print(f"Error describing node group {ng_name}: {e}")
                continue
        
        return nodegroups
        
    except ClientError as e:
        print(f"Error listing node groups for cluster {cluster_name}: {e}")
        return []


def check_nodegroup_update_available(
    cluster_name: str,
    nodegroup_name: str,
    current_k8s_version: str,
    cluster_k8s_version: str
) -> tuple:
    """
    Determine if a node group needs updating by comparing versions.
    
    Args:
        cluster_name: Name of the EKS cluster
        nodegroup_name: Name of the node group
        current_k8s_version: Current Kubernetes version of the node group
        cluster_k8s_version: Kubernetes version of the cluster
        
    Returns:
        Tuple of (needs_update: bool, version_mismatch: bool)
        - needs_update: True if update should be attempted
        - version_mismatch: True if K8s versions differ, False if only AMI might differ
    """
    # Compare Kubernetes versions
    if current_k8s_version != cluster_k8s_version:
        print(f"Node group {nodegroup_name} version {current_k8s_version} differs from cluster version {cluster_k8s_version}")
        return (True, True)
    
    # Versions match, but there might be a newer AMI for the same K8s version
    # Always attempt update to get latest AMI - EKS API will handle if already up-to-date
    print(f"Node group {nodegroup_name} K8s version matches cluster ({cluster_k8s_version}), checking for AMI updates")
    return (True, False)


def update_nodegroup_version(
    cluster_name: str,
    nodegroup_name: str,
    target_k8s_version: str
) -> Dict:
    """
    Update a node group to the target Kubernetes version with latest AMI.
    
    Args:
        cluster_name: Name of the EKS cluster
        nodegroup_name: Name of the node group
        target_k8s_version: Target Kubernetes version
        
    Returns:
        Dictionary with success status, update_id, and error message
    """
    try:
        response = retry_with_backoff(
            eks_client.update_nodegroup_version,
            clusterName=cluster_name,
            nodegroupName=nodegroup_name,
            version=target_k8s_version,
            force=False  # Never force to respect PDBs
        )
        
        update_id = response.get('update', {}).get('id')
        print(f"Successfully initiated update for node group {nodegroup_name}, update ID: {update_id}")
        
        return {
            'success': True,
            'update_id': update_id,
            'error': None
        }
        
    except ClientError as e:
        error_message = str(e)
        error_code = e.response.get('Error', {}).get('Code', '')
        
        print(f"Failed to update node group {nodegroup_name}: {error_message}")
        
        return {
            'success': False,
            'update_id': None,
            'error': error_message
        }



def send_nodegroup_summary(
    cluster_name: str,
    nodegroup_results: List[Dict],
    sns_topic_arn: str
) -> None:
    """
    Send consolidated SNS notification for all node groups in a cluster.
    
    Args:
        cluster_name: Name of the EKS cluster
        nodegroup_results: List of node group processing results
        sns_topic_arn: ARN of the SNS topic
    """
    # Count results by status
    updating = [r for r in nodegroup_results if r['status'] == 'updating']
    failed = [r for r in nodegroup_results if r['status'] == 'failed']
    up_to_date = [r for r in nodegroup_results if r['status'] == 'up_to_date']
    
    # Determine overall status
    if failed:
        overall_status = f"{len(failed)} Failed"
    elif updating:
        overall_status = f"{len(updating)} Updating"
    else:
        overall_status = "All Up-to-Date"
    
    # Build email subject
    subject = f"EKS Node Group Summary - {cluster_name} - {overall_status}"
    
    # Build email body
    message_lines = [
        f"Cluster: {cluster_name}",
        f"Total Node Groups: {len(nodegroup_results)}",
        f"Up-to-Date: {len(up_to_date)}",
        f"Updating: {len(updating)}",
        f"Failed: {len(failed)}",
        "",
        "=" * 60,
        ""
    ]
    
    # Add updating node groups section
    if updating:
        message_lines.append("UPDATING NODE GROUPS:")
        message_lines.append("-" * 60)
        for result in updating:
            message_lines.append(f"  Node Group: {result['nodegroup_name']}")
            message_lines.append(f"  Kubernetes Version: {result['current_version']} → {result['target_version']}")
            message_lines.append(f"  AMI Release: {result['current_ami']} → Latest")
            message_lines.append(f"  Update ID: {result['update_id']}")
            message_lines.append("")
    
    # Add failed node groups section
    if failed:
        message_lines.append("FAILED NODE GROUPS:")
        message_lines.append("-" * 60)
        for result in failed:
            message_lines.append(f"  Node Group: {result['nodegroup_name']}")
            message_lines.append(f"  Current Version: {result['current_version']}")
            message_lines.append(f"  Target Version: {result['target_version']}")
            message_lines.append(f"  Error: {result['error']}")
            
            # Check if error is PDB-related
            if 'PodEvictionFailure' in result['error'] or 'PDB' in result['error']:
                message_lines.append("")
                message_lines.append("  ACTION REQUIRED: If you want to force this update, run:")
                message_lines.append(f"  aws eks update-nodegroup-version \\")
                message_lines.append(f"    --cluster-name {cluster_name} \\")
                message_lines.append(f"    --nodegroup-name {result['nodegroup_name']} \\")
                message_lines.append(f"    --force")
            
            message_lines.append("")
    
    # Add up-to-date node groups section
    if up_to_date:
        message_lines.append("UP-TO-DATE NODE GROUPS:")
        message_lines.append("-" * 60)
        for result in up_to_date:
            message_lines.append(f"  {result['nodegroup_name']} ({result['current_version']}, AMI: {result['current_ami']})")
        message_lines.append("")
    
    message = "\n".join(message_lines)
    
    # Send SNS notification
    try:
        sns_client.publish(
            TopicArn=sns_topic_arn,
            Subject=subject,
            Message=message
        )
        print(f"Sent node group summary notification for cluster {cluster_name}")
    except ClientError as e:
        print(f"Error sending SNS notification: {e}")


def process_cluster_nodegroups(
    cluster_name: str,
    cluster_k8s_version: str,
    sns_topic_arn: str
) -> List[Dict]:
    """
    Main processing function that orchestrates node group updates for a cluster.
    
    Args:
        cluster_name: Name of the EKS cluster
        cluster_k8s_version: Kubernetes version of the cluster
        sns_topic_arn: ARN of the SNS topic
        
    Returns:
        List of node group processing results
    """
    print(f"Processing node groups for cluster {cluster_name} (K8s version: {cluster_k8s_version})")
    
    # Get all node groups
    nodegroups = get_cluster_nodegroups(cluster_name)
    
    if not nodegroups:
        print(f"No node groups to process for cluster {cluster_name}")
        return []
    
    results = []
    
    # Process each node group
    for ng in nodegroups:
        ng_name = ng['nodegroup_name']
        current_version = ng['kubernetes_version']
        current_ami = ng['release_version']
        
        print(f"Processing node group {ng_name} (current version: {current_version})")
        
        try:
            # Check if update is needed
            needs_update, version_mismatch = check_nodegroup_update_available(
                cluster_name,
                ng_name,
                current_version,
                cluster_k8s_version
            )
            
            if not needs_update:
                results.append({
                    'nodegroup_name': ng_name,
                    'status': 'up_to_date',
                    'current_version': current_version,
                    'target_version': None,
                    'current_ami': current_ami,
                    'update_id': None,
                    'error': None
                })
                continue
            
            # Attempt update if auto-upgrade is enabled
            if ENABLE_AUTO_UPGRADE:
                update_result = update_nodegroup_version(
                    cluster_name,
                    ng_name,
                    cluster_k8s_version
                )
                
                if update_result['success']:
                    results.append({
                        'nodegroup_name': ng_name,
                        'status': 'updating',
                        'current_version': current_version,
                        'target_version': cluster_k8s_version,
                        'current_ami': current_ami,
                        'update_id': update_result['update_id'],
                        'error': None
                    })
                else:
                    results.append({
                        'nodegroup_name': ng_name,
                        'status': 'failed',
                        'current_version': current_version,
                        'target_version': cluster_k8s_version,
                        'current_ami': current_ami,
                        'update_id': None,
                        'error': update_result['error']
                    })
            else:
                print(f"Auto-upgrade disabled, skipping update for {ng_name}")
                results.append({
                    'nodegroup_name': ng_name,
                    'status': 'up_to_date',
                    'current_version': current_version,
                    'target_version': None,
                    'current_ami': current_ami,
                    'update_id': None,
                    'error': None
                })
        
        except Exception as e:
            # Error isolation - continue processing other node groups
            print(f"Unexpected error processing node group {ng_name}: {e}")
            results.append({
                'nodegroup_name': ng_name,
                'status': 'failed',
                'current_version': current_version,
                'target_version': cluster_k8s_version,
                'current_ami': current_ami,
                'update_id': None,
                'error': str(e)
            })
    
    # Send consolidated notification
    send_nodegroup_summary(cluster_name, results, sns_topic_arn)
    
    return results



def is_development_cluster(cluster_name: str, cluster_tags: Dict[str, str]) -> bool:
    """
    Determine if a cluster is a development cluster based on tags and name.
    
    Args:
        cluster_name: Name of the cluster
        cluster_tags: Dictionary of cluster tags
        
    Returns:
        True if cluster is a development cluster, False otherwise
    """
    # Check cluster name
    name_lower = cluster_name.lower()
    if 'dev' in name_lower or 'development' in name_lower:
        return True
    
    # Check tags
    for key, value in cluster_tags.items():
        key_lower = key.lower()
        value_lower = value.lower() if value else ''
        
        if key_lower in ['environment', 'env']:
            if 'dev' in value_lower:
                return True
    
    return False


def lambda_handler(event, context):
    """
    Lambda handler for EKS node group version management.
    
    Args:
        event: Lambda event (can contain cluster_name for testing)
        context: Lambda context
        
    Returns:
        Dictionary with processing results
    """
    print("Starting EKS node group version management")
    print(f"Event: {json.dumps(event)}")
    
    if not SNS_TOPIC_ARN:
        print("ERROR: SNS_TOPIC_ARN environment variable not set")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'SNS_TOPIC_ARN not configured'})
        }
    
    try:
        # Get all EKS clusters
        clusters_response = eks_client.list_clusters()
        cluster_names = clusters_response.get('clusters', [])
        
        print(f"Found {len(cluster_names)} clusters")
        
        all_results = []
        
        for cluster_name in cluster_names:
            try:
                # Get cluster details
                cluster_response = eks_client.describe_cluster(name=cluster_name)
                cluster = cluster_response.get('cluster', {})
                cluster_tags = cluster.get('tags', {})
                cluster_k8s_version = cluster.get('version')
                
                # Filter for development clusters only
                if not is_development_cluster(cluster_name, cluster_tags):
                    print(f"Skipping non-development cluster: {cluster_name}")
                    continue
                
                print(f"Processing development cluster: {cluster_name}")
                
                # Process node groups for this cluster
                results = process_cluster_nodegroups(
                    cluster_name,
                    cluster_k8s_version,
                    SNS_TOPIC_ARN
                )
                
                all_results.append({
                    'cluster': cluster_name,
                    'status': 'processed',
                    'nodegroups': results
                })
                
            except ClientError as e:
                print(f"Error processing cluster {cluster_name}: {e}")
                all_results.append({
                    'cluster': cluster_name,
                    'status': 'error',
                    'error': str(e)
                })
                continue
        
        print(f"Completed processing {len(all_results)} development clusters")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Node group processing completed',
                'clusters_processed': len(all_results),
                'results': all_results
            })
        }
        
    except Exception as e:
        print(f"Fatal error in lambda_handler: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
