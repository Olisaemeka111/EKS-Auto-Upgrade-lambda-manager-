import boto3
import os
from typing import List, Dict, Optional


def get_cluster_addons(eks_client, cluster_name: str) -> List[Dict]:
    """
    Retrieves all addons for a cluster with their configurations.
    
    Args:
        eks_client: Boto3 EKS client
        cluster_name: Name of the EKS cluster
        
    Returns:
        List of addon dictionaries containing:
        - addon_name: str
        - addon_version: str
        - service_account_role_arn: Optional[str]
        - pod_identity_associations: Optional[List[Dict]]
        - configuration_values: Optional[str]
    """
    addons = []
    
    try:
        # List all addons for the cluster
        list_response = eks_client.list_addons(clusterName=cluster_name)
        addon_names = list_response.get('addons', [])
        
        # Get detailed configuration for each addon
        for addon_name in addon_names:
            try:
                describe_response = eks_client.describe_addon(
                    clusterName=cluster_name,
                    addonName=addon_name
                )
                
                addon_info = describe_response.get('addon', {})
                
                # Get Pod Identity associations with full details
                pod_identity_arns = addon_info.get('podIdentityAssociations', [])
                pod_identity_associations = None
                
                if pod_identity_arns:
                    pod_identity_associations = []
                    for assoc_arn in pod_identity_arns:
                        try:
                            # Describe the Pod Identity association to get serviceAccount and roleArn
                            assoc_response = eks_client.describe_pod_identity_association(
                                clusterName=cluster_name,
                                associationId=assoc_arn.split('/')[-1]
                            )
                            assoc_details = assoc_response.get('association', {})
                            pod_identity_associations.append({
                                'serviceAccount': assoc_details.get('serviceAccount'),
                                'roleArn': assoc_details.get('roleArn')
                            })
                        except Exception as e:
                            print(f"Error describing Pod Identity association {assoc_arn}: {str(e)}")
                            continue
                
                addon_dict = {
                    'addon_name': addon_info.get('addonName'),
                    'addon_version': addon_info.get('addonVersion'),
                    'service_account_role_arn': addon_info.get('serviceAccountRoleArn'),
                    'pod_identity_associations': pod_identity_associations,
                    'configuration_values': addon_info.get('configurationValues')
                }
                
                addons.append(addon_dict)
                
            except Exception as e:
                # Log error but continue processing other addons
                print(f"Error describing addon {addon_name} for cluster {cluster_name}: {str(e)}")
                continue
                
    except Exception as e:
        print(f"Error listing addons for cluster {cluster_name}: {str(e)}")
        return []
    
    return addons


def extract_auth_config(addon_info: Dict) -> Dict:
    """
    Extracts authentication configuration from addon info.
    
    Args:
        addon_info: Addon description from describe_addon API
        
    Returns:
        Dictionary containing:
        - auth_type: 'pod_identity' | 'irsa' | 'none'
        - service_account_role_arn: Optional[str]
        - pod_identity_associations: Optional[List[Dict]]
    """
    auth_config = {
        'auth_type': 'none',
        'service_account_role_arn': None,
        'pod_identity_associations': None
    }
    
    # Check for Pod Identity associations
    pod_identity_associations = addon_info.get('pod_identity_associations')
    if pod_identity_associations:
        auth_config['auth_type'] = 'pod_identity'
        auth_config['pod_identity_associations'] = pod_identity_associations
        return auth_config
    
    # Check for IRSA (service account role ARN)
    service_account_role_arn = addon_info.get('service_account_role_arn')
    if service_account_role_arn:
        auth_config['auth_type'] = 'irsa'
        auth_config['service_account_role_arn'] = service_account_role_arn
        return auth_config
    
    # No authentication configured
    return auth_config


def compare_versions(version1: str, version2: str) -> str:
    """
    Compares two semantic version strings.
    
    Args:
        version1: First version string (format: v1.15.0-eksbuild.1)
        version2: Second version string (format: v1.15.0-eksbuild.1)
        
    Returns:
        'older' if version1 < version2
        'equal' if version1 == version2
        'newer' if version1 > version2
    """
    def parse_version(version_str: str) -> tuple:
        """Parse version string into comparable tuple."""
        # Remove 'v' prefix if present
        if version_str.startswith('v'):
            version_str = version_str[1:]
        
        # Split on '-' to separate version from build info
        parts = version_str.split('-')
        version_part = parts[0]
        
        # Parse major.minor.patch
        version_numbers = version_part.split('.')
        major = int(version_numbers[0]) if len(version_numbers) > 0 else 0
        minor = int(version_numbers[1]) if len(version_numbers) > 1 else 0
        patch = int(version_numbers[2]) if len(version_numbers) > 2 else 0
        
        # Parse build number if present (e.g., eksbuild.1)
        build = 0
        if len(parts) > 1:
            build_part = parts[1]
            if '.' in build_part:
                build_num = build_part.split('.')[1]
                build = int(build_num) if build_num.isdigit() else 0
        
        return (major, minor, patch, build)
    
    try:
        v1_tuple = parse_version(version1)
        v2_tuple = parse_version(version2)
        
        if v1_tuple < v2_tuple:
            return 'older'
        elif v1_tuple > v2_tuple:
            return 'newer'
        else:
            return 'equal'
    except (ValueError, IndexError) as e:
        # If parsing fails, treat as equal to avoid errors
        print(f"Error comparing versions {version1} and {version2}: {str(e)}")
        return 'equal'


def check_addon_update_available(eks_client, cluster_name: str, addon_name: str, 
                                  current_version: str, cluster_k8s_version: str) -> Optional[str]:
    """
    Checks if a newer addon version is available.
    
    Args:
        eks_client: Boto3 EKS client
        cluster_name: Name of the EKS cluster
        addon_name: Name of the addon
        current_version: Currently installed version
        cluster_k8s_version: Kubernetes version of the cluster
        
    Returns:
        Latest version string if update available, None if up-to-date or error
    """
    try:
        # Query available addon versions for the cluster's Kubernetes version
        response = eks_client.describe_addon_versions(
            addonName=addon_name,
            kubernetesVersion=cluster_k8s_version
        )
        
        # Get the list of addon versions
        addon_versions = response.get('addons', [])
        
        if not addon_versions:
            print(f"No addon versions found for {addon_name} on Kubernetes {cluster_k8s_version}")
            return None
        
        # Get the first addon entry (should be the only one for the specific addon name)
        addon_info = addon_versions[0]
        addon_version_infos = addon_info.get('addonVersions', [])
        
        if not addon_version_infos:
            print(f"No version information available for addon {addon_name}")
            return None
        
        # The first version in the list is the latest compatible version
        latest_version = addon_version_infos[0].get('addonVersion')
        
        if not latest_version:
            print(f"Could not determine latest version for addon {addon_name}")
            return None
        
        # Compare current version with latest version
        comparison = compare_versions(current_version, latest_version)
        
        if comparison == 'older':
            # Update is available
            return latest_version
        else:
            # Already up-to-date or newer
            return None
            
    except Exception as e:
        # Handle API errors gracefully
        print(f"Error checking addon version for {addon_name} in cluster {cluster_name}: {str(e)}")
        return None


def update_addon_with_auth_preservation(
    eks_client,
    cluster_name: str,
    addon_name: str,
    target_version: str,
    auth_config: Dict
) -> Dict:
    """
    Updates an addon to target version with preserved authentication.
    
    Args:
        eks_client: Boto3 EKS client
        cluster_name: Name of the EKS cluster
        addon_name: Name of the addon to update
        target_version: Target version to update to
        auth_config: Authentication configuration from extract_auth_config
        
    Returns:
        Update response dictionary containing:
        - success: bool
        - update_id: Optional[str]
        - error: Optional[str]
    """
    try:
        # Construct base update request
        update_params = {
            'clusterName': cluster_name,
            'addonName': addon_name,
            'addonVersion': target_version,
            'resolveConflicts': 'OVERWRITE'
        }
        
        # Include authentication parameters based on auth_type
        auth_type = auth_config.get('auth_type', 'none')
        
        if auth_type == 'pod_identity':
            # Include Pod Identity associations
            pod_identity_associations = auth_config.get('pod_identity_associations')
            if pod_identity_associations:
                update_params['podIdentityAssociations'] = pod_identity_associations
        
        elif auth_type == 'irsa':
            # Include IRSA service account role ARN
            service_account_role_arn = auth_config.get('service_account_role_arn')
            if service_account_role_arn:
                update_params['serviceAccountRoleArn'] = service_account_role_arn
        
        # For 'none' auth_type, no authentication parameters are included
        
        # Call update_addon API
        response = eks_client.update_addon(**update_params)
        
        # Extract update information
        update_info = response.get('update', {})
        update_id = update_info.get('id')
        
        return {
            'success': True,
            'update_id': update_id,
            'error': None
        }
        
    except Exception as e:
        # Handle update failures
        error_message = str(e)
        print(f"Error updating addon {addon_name} in cluster {cluster_name}: {error_message}")
        
        return {
            'success': False,
            'update_id': None,
            'error': error_message
        }


def send_cluster_addon_summary(
    sns_client,
    sns_topic_arn: str,
    cluster_name: str,
    addon_results: List[Dict]
) -> None:
    """
    Sends a consolidated SNS notification for all addons in a cluster.
    
    Args:
        sns_client: Boto3 SNS client
        sns_topic_arn: SNS topic ARN for notifications
        cluster_name: Name of the EKS cluster
        addon_results: List of addon processing results
    """
    if not addon_results:
        return
    
    # Count addon statuses
    up_to_date_count = sum(1 for a in addon_results if a['status'] == 'up_to_date')
    updated_count = sum(1 for a in addon_results if a['status'] == 'updated')
    failed_count = sum(1 for a in addon_results if a['status'] == 'failed')
    
    # Determine overall status and subject
    if failed_count > 0:
        subject = f"EKS Addon Summary - {cluster_name} - {failed_count} Failed"
    elif updated_count > 0:
        subject = f"EKS Addon Summary - {cluster_name} - {updated_count} Updated"
    else:
        subject = f"EKS Addon Summary - {cluster_name} - All Up-to-Date"
    
    # Format authentication type for display
    def format_auth(auth_type):
        return {
            'pod_identity': 'Pod Identity',
            'irsa': 'IRSA',
            'none': 'None'
        }.get(auth_type, auth_type)
    
    # Build message sections
    message_parts = [
        f"Cluster: {cluster_name}",
        f"Total Addons: {len(addon_results)}",
        f"Up-to-Date: {up_to_date_count}",
        f"Updated: {updated_count}",
        f"Failed: {failed_count}",
        "",
        "=" * 60,
        ""
    ]
    
    # Add updated addons section
    if updated_count > 0:
        message_parts.append("UPDATED ADDONS:")
        message_parts.append("-" * 60)
        for addon in addon_results:
            if addon['status'] == 'updated':
                message_parts.extend([
                    f"  Addon: {addon['addon_name']}",
                    f"  Version: {addon['current_version']} → {addon['target_version']}",
                    f"  Authentication: {format_auth(addon['auth_type'])}",
                    ""
                ])
        message_parts.append("")
    
    # Add failed addons section
    if failed_count > 0:
        message_parts.append("FAILED ADDONS:")
        message_parts.append("-" * 60)
        for addon in addon_results:
            if addon['status'] == 'failed':
                message_parts.extend([
                    f"  Addon: {addon['addon_name']}",
                    f"  Current Version: {addon['current_version']}",
                    f"  Target Version: {addon.get('target_version', 'N/A')}",
                    f"  Authentication: {format_auth(addon['auth_type'])}",
                    f"  Error: {addon.get('error', 'Unknown error')}",
                    ""
                ])
        message_parts.append("")
    
    # Add up-to-date addons section (condensed)
    if up_to_date_count > 0:
        message_parts.append("UP-TO-DATE ADDONS:")
        message_parts.append("-" * 60)
        for addon in addon_results:
            if addon['status'] == 'up_to_date':
                message_parts.append(
                    f"  {addon['addon_name']} ({addon['current_version']}) - {format_auth(addon['auth_type'])}"
                )
        message_parts.append("")
    
    message = "\n".join(message_parts)
    
    try:
        sns_client.publish(
            TopicArn=sns_topic_arn,
            Subject=subject,
            Message=message
        )
    except Exception as e:
        print(f"Error sending addon summary notification for cluster {cluster_name}: {str(e)}")


def process_cluster_addons(
    eks_client,
    sns_client,
    cluster_name: str,
    cluster_k8s_version: str,
    sns_topic_arn: str
) -> List[Dict]:
    """
    Processes all addons for a cluster.
    
    Args:
        eks_client: Boto3 EKS client
        sns_client: Boto3 SNS client
        cluster_name: Name of the EKS cluster
        cluster_k8s_version: Kubernetes version of the cluster
        sns_topic_arn: SNS topic ARN for notifications
        
    Returns:
        List of addon processing results containing:
        - addon_name: str
        - status: 'up_to_date' | 'updated' | 'failed'
        - current_version: str
        - target_version: Optional[str]
        - auth_type: str
        - error: Optional[str]
    """
    results = []
    
    # Retrieve all addons for the cluster
    try:
        addons = get_cluster_addons(eks_client, cluster_name)
    except Exception as e:
        print(f"Failed to retrieve addons for cluster {cluster_name}: {str(e)}")
        return results
    
    # Process each addon individually with error isolation
    for addon_info in addons:
        addon_name = addon_info.get('addon_name')
        current_version = addon_info.get('addon_version')
        
        # Initialize result for this addon
        addon_result = {
            'addon_name': addon_name,
            'status': 'failed',
            'current_version': current_version,
            'target_version': None,
            'auth_type': 'none',
            'error': None
        }
        
        try:
            # Extract authentication configuration
            auth_config = extract_auth_config(addon_info)
            auth_type = auth_config.get('auth_type', 'none')
            addon_result['auth_type'] = auth_type
            
            # Check if update is available
            latest_version = None
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    latest_version = check_addon_update_available(
                        eks_client,
                        cluster_name,
                        addon_name,
                        current_version,
                        cluster_k8s_version
                    )
                    break  # Success, exit retry loop
                    
                except Exception as e:
                    error_str = str(e)
                    # Check if it's a throttling error
                    if 'ThrottlingException' in error_str or 'TooManyRequestsException' in error_str:
                        retry_count += 1
                        if retry_count < max_retries:
                            # Exponential backoff: 1s, 2s, 4s
                            import time
                            wait_time = 2 ** (retry_count - 1)
                            print(f"Throttling error for {addon_name}, retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                            time.sleep(wait_time)
                        else:
                            # Max retries reached
                            raise
                    else:
                        # Non-throttling error, don't retry
                        raise
            
            if latest_version is None:
                # Addon is up-to-date
                addon_result['status'] = 'up_to_date'
                addon_result['target_version'] = current_version
            else:
                # Update is available, attempt to update
                addon_result['target_version'] = latest_version
                
                # Perform update with retry logic for throttling
                update_result = None
                retry_count = 0
                
                while retry_count < max_retries:
                    try:
                        update_result = update_addon_with_auth_preservation(
                            eks_client,
                            cluster_name,
                            addon_name,
                            latest_version,
                            auth_config
                        )
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        error_str = str(e)
                        # Check if it's a throttling error
                        if 'ThrottlingException' in error_str or 'TooManyRequestsException' in error_str:
                            retry_count += 1
                            if retry_count < max_retries:
                                # Exponential backoff: 1s, 2s, 4s
                                import time
                                wait_time = 2 ** (retry_count - 1)
                                print(f"Throttling error updating {addon_name}, retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                                time.sleep(wait_time)
                            else:
                                # Max retries reached
                                raise
                        else:
                            # Non-throttling error, don't retry
                            raise
                
                if update_result and update_result.get('success'):
                    # Update initiated successfully
                    addon_result['status'] = 'updated'
                else:
                    # Update failed
                    addon_result['status'] = 'failed'
                    addon_result['error'] = update_result.get('error') if update_result else 'Unknown error'
        
        except Exception as e:
            # Catch any unexpected errors and record failure
            error_message = str(e)
            print(f"Error processing addon {addon_name} in cluster {cluster_name}: {error_message}")
            
            addon_result['status'] = 'failed'
            addon_result['error'] = error_message
        
        finally:
            # Always append result, even if processing failed
            results.append(addon_result)
    
    # Send consolidated notification for all addons in this cluster
    send_cluster_addon_summary(
        sns_client,
        sns_topic_arn,
        cluster_name,
        results
    )
    
    return results


def lambda_handler(event, context):
    eks = boto3.client('eks')
    sns = boto3.client('sns')
    sns_topic_arn = os.environ['SNS_TOPIC_ARN']
    
    clusters = eks.list_clusters()['clusters']
    latest_version = eks.describe_cluster_versions()['clusterVersions'][0]['clusterVersion']
    
    results = []
    
    for cluster_name in clusters:
        cluster_info = eks.describe_cluster(name=cluster_name)['cluster']
        current_version = cluster_info['version']
        tags = cluster_info.get('tags', {})
        
        # Check if dev cluster
        env = tags.get('Environment') or tags.get('environment') or tags.get('Env')
        is_dev = (env and ('dev' in env.lower() or 'development' in env.lower())) or \
                 ('dev' in cluster_name.lower() or 'development' in cluster_name.lower())
        
        if not is_dev:
            continue
        
        # Initialize cluster result
        cluster_result = {'cluster': cluster_name}
            
        if latest_version <= current_version:
            message = f"EKS cluster '{cluster_name}' is up to date \nCurrent version: {current_version}\nLatest version: {latest_version}"
            sns.publish(
                TopicArn=sns_topic_arn,
                Subject=f"EKS Cluster is up to date - {cluster_name}",
                Message=message
            )            
            cluster_result['status'] = 'up_to_date'
            
        else:
            # Check upgrade insights
            insights = eks.list_insights(
                clusterName=cluster_name,
                filter={'categories': ['UPGRADE_READINESS']}
            )
            
            non_passing = [i for i in insights['insights'] if i['insightStatus']['status'] != 'PASSING']
            
            if non_passing:
                message = f"EKS cluster '{cluster_name}' upgrade blocked: {len(non_passing)} failing insights\nCurrent version: {current_version}\nLatest version: {latest_version}"
                sns.publish(
                    TopicArn=sns_topic_arn,
                    Subject=f"EKS Cluster Upgrade Blocked due to Potential Issue - {cluster_name}",
                    Message=message
                )
                cluster_result['status'] = 'blocked'
                cluster_result['issues'] = len(non_passing)
                
            else:
                # Upgrade if enabled
                if os.environ.get('ENABLE_AUTO_UPGRADE') == 'true':
                    eks.update_cluster_version(name=cluster_name, version=latest_version)
                    message = f"EKS cluster '{cluster_name}' upgrade initiated: {current_version} → {latest_version}"
                    sns.publish(
                        TopicArn=sns_topic_arn,
                        Subject=f"EKS Cluster Upgrade Initiated - {cluster_name}",
                        Message=message
                    )
                    cluster_result['status'] = 'upgrading'
                else:
                    message = f"EKS cluster '{cluster_name}' upgrade available: {current_version} → {latest_version}"
                    sns.publish(
                        TopicArn=sns_topic_arn,
                        Subject=f"EKS Cluster Upgrade Available for {cluster_name}",
                        Message=message
                    )
                    cluster_result['status'] = 'available'
        
        # Process addons for this cluster (after cluster version checks)
        addon_results = process_cluster_addons(
            eks,
            sns,
            cluster_name,
            current_version,
            sns_topic_arn
        )
        
        # Add addon results to cluster result
        cluster_result['addons'] = addon_results
        
        # Append cluster result to results list
        results.append(cluster_result)
    
    return {'statusCode': 200, 'body': {'processed_dev_clusters': results}}
