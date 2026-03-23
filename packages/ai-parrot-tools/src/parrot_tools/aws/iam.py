"""AWS IAM Toolkit for AI-Parrot.

Provides inspection of IAM roles, users, policies, and access keys.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from ...interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------
class ListRolesInput(BaseModel):
    """Input for listing IAM roles."""

    max_items: int = Field(
        100, description="Maximum number of roles to return"
    )
    path_prefix: Optional[str] = Field(
        None, description="Filter roles by path prefix"
    )


class GetRoleInput(BaseModel):
    """Input for getting IAM role details."""

    role_name: str = Field(
        ..., description="Name of the IAM role"
    )


class ListUsersInput(BaseModel):
    """Input for listing IAM users."""

    max_items: int = Field(
        100, description="Maximum number of users to return"
    )
    path_prefix: Optional[str] = Field(
        None, description="Filter users by path prefix"
    )


class GetUserInput(BaseModel):
    """Input for getting IAM user details."""

    user_name: str = Field(
        ..., description="Name of the IAM user"
    )


class GetPolicyDetailsInput(BaseModel):
    """Input for getting IAM policy details."""

    policy_arn: str = Field(
        ..., description="ARN of the IAM policy"
    )
    include_versions: bool = Field(
        False,
        description="Whether to include all policy versions",
    )


class FindAccessKeyInput(BaseModel):
    """Input for finding the owner of an access key."""

    access_key_id: str = Field(
        ..., description="The access key ID to search for"
    )


class ListActiveAccessKeysInput(BaseModel):
    """Input for listing all active access keys."""


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class IAMToolkit(AbstractToolkit):
    """Toolkit for inspecting AWS IAM roles, users, policies, and access keys.

    Available Operations:
    - aws_iam_list_roles: List IAM roles
    - aws_iam_get_role: Get detailed role information
    - aws_iam_list_users: List IAM users
    - aws_iam_get_user: Get detailed user information
    - aws_iam_get_policy_details: Get policy details by ARN
    - aws_iam_find_access_key: Find which user owns an access key
    - aws_iam_list_active_access_keys: List all active access keys
    """
    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.aws = AWSInterface(
            aws_id=aws_id,
            region_name=region_name,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # List Roles
    # ------------------------------------------------------------------
    @tool_schema(ListRolesInput)
    async def aws_iam_list_roles(
        self,
        max_items: int = 100,
        path_prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List IAM roles in the AWS account."""
        try:
            params: Dict[str, Any] = {
                "MaxItems": max_items
            }
            if path_prefix:
                params["PathPrefix"] = path_prefix

            async with self.aws.client("iam") as iam:
                response = await iam.list_roles(**params)
                roles = [
                    {
                        "role_name": r.get("RoleName"),
                        "role_id": r.get("RoleId"),
                        "arn": r.get("Arn"),
                        "path": r.get("Path"),
                        "created_date": (
                            r.get("CreateDate").isoformat()
                            if r.get("CreateDate")
                            else None
                        ),
                        "description": r.get("Description"),
                        "max_session_duration": r.get(
                            "MaxSessionDuration"
                        ),
                    }
                    for r in response.get("Roles", [])
                ]
                return {
                    "roles": roles,
                    "count": len(roles),
                    "is_truncated": response.get(
                        "IsTruncated", False
                    ),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS IAM error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Role
    # ------------------------------------------------------------------

    @tool_schema(GetRoleInput)
    async def aws_iam_get_role(
        self, role_name: str
    ) -> Dict[str, Any]:
        """Get detailed information about an IAM role including trust policy."""
        try:
            async with self.aws.client("iam") as iam:
                # Get role details
                resp = await iam.get_role(RoleName=role_name)
                role = resp.get("Role", {})

                # Get attached policies
                pol_resp = await iam.list_attached_role_policies(
                    RoleName=role_name
                )
                attached = [
                    {
                        "policy_name": p.get("PolicyName"),
                        "policy_arn": p.get("PolicyArn"),
                    }
                    for p in pol_resp.get(
                        "AttachedPolicies", []
                    )
                ]

                # Get inline policies
                inline_resp = await iam.list_role_policies(
                    RoleName=role_name
                )
                inline_names = inline_resp.get(
                    "PolicyNames", []
                )

                return {
                    "role_name": role.get("RoleName"),
                    "role_id": role.get("RoleId"),
                    "arn": role.get("Arn"),
                    "path": role.get("Path"),
                    "created_date": (
                        role.get("CreateDate").isoformat()
                        if role.get("CreateDate")
                        else None
                    ),
                    "description": role.get("Description"),
                    "max_session_duration": role.get(
                        "MaxSessionDuration"
                    ),
                    "trust_policy": role.get(
                        "AssumeRolePolicyDocument"
                    ),
                    "attached_policies": attached,
                    "inline_policy_names": inline_names,
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS IAM error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Users
    # ------------------------------------------------------------------

    @tool_schema(ListUsersInput)
    async def aws_iam_list_users(
        self,
        max_items: int = 100,
        path_prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List IAM users in the AWS account."""
        try:
            params: Dict[str, Any] = {
                "MaxItems": max_items
            }
            if path_prefix:
                params["PathPrefix"] = path_prefix

            async with self.aws.client("iam") as iam:
                response = await iam.list_users(**params)
                users = [
                    {
                        "user_name": u.get("UserName"),
                        "user_id": u.get("UserId"),
                        "arn": u.get("Arn"),
                        "path": u.get("Path"),
                        "created_date": (
                            u.get("CreateDate").isoformat()
                            if u.get("CreateDate")
                            else None
                        ),
                        "password_last_used": (
                            u.get(
                                "PasswordLastUsed"
                            ).isoformat()
                            if u.get("PasswordLastUsed")
                            else None
                        ),
                    }
                    for u in response.get("Users", [])
                ]
                return {
                    "users": users,
                    "count": len(users),
                    "is_truncated": response.get(
                        "IsTruncated", False
                    ),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS IAM error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get User
    # ------------------------------------------------------------------

    @tool_schema(GetUserInput)
    async def aws_iam_get_user(
        self, user_name: str
    ) -> Dict[str, Any]:
        """Get detailed information about an IAM user."""
        try:
            async with self.aws.client("iam") as iam:
                resp = await iam.get_user(UserName=user_name)
                user = resp.get("User", {})

                # Access keys
                keys_resp = await iam.list_access_keys(
                    UserName=user_name
                )
                access_keys = [
                    {
                        "access_key_id": k.get("AccessKeyId"),
                        "status": k.get("Status"),
                        "created_date": (
                            k.get("CreateDate").isoformat()
                            if k.get("CreateDate")
                            else None
                        ),
                    }
                    for k in keys_resp.get(
                        "AccessKeyMetadata", []
                    )
                ]

                # MFA devices
                mfa_resp = await iam.list_mfa_devices(
                    UserName=user_name
                )
                mfa_devices = [
                    {
                        "serial_number": m.get(
                            "SerialNumber"
                        ),
                        "enable_date": (
                            m.get("EnableDate").isoformat()
                            if m.get("EnableDate")
                            else None
                        ),
                    }
                    for m in mfa_resp.get("MFADevices", [])
                ]

                # Attached policies
                pol_resp = await iam.list_attached_user_policies(
                    UserName=user_name
                )
                attached = [
                    {
                        "policy_name": p.get("PolicyName"),
                        "policy_arn": p.get("PolicyArn"),
                    }
                    for p in pol_resp.get(
                        "AttachedPolicies", []
                    )
                ]

                # Groups
                grp_resp = await iam.list_groups_for_user(
                    UserName=user_name
                )
                groups = [
                    g.get("GroupName")
                    for g in grp_resp.get("Groups", [])
                ]

                return {
                    "user_name": user.get("UserName"),
                    "user_id": user.get("UserId"),
                    "arn": user.get("Arn"),
                    "created_date": (
                        user.get("CreateDate").isoformat()
                        if user.get("CreateDate")
                        else None
                    ),
                    "password_last_used": (
                        user.get(
                            "PasswordLastUsed"
                        ).isoformat()
                        if user.get("PasswordLastUsed")
                        else None
                    ),
                    "access_keys": access_keys,
                    "mfa_devices": mfa_devices,
                    "mfa_enabled": len(mfa_devices) > 0,
                    "attached_policies": attached,
                    "groups": groups,
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS IAM error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Policy Details
    # ------------------------------------------------------------------

    @tool_schema(GetPolicyDetailsInput)
    async def aws_iam_get_policy_details(
        self,
        policy_arn: str,
        include_versions: bool = False,
    ) -> Dict[str, Any]:
        """Get detailed information about an IAM policy."""
        try:
            async with self.aws.client("iam") as iam:
                resp = await iam.get_policy(PolicyArn=policy_arn)
                policy = resp.get("Policy", {})

                result: Dict[str, Any] = {
                    "policy_name": policy.get("PolicyName"),
                    "policy_id": policy.get("PolicyId"),
                    "arn": policy.get("Arn"),
                    "path": policy.get("Path"),
                    "default_version_id": policy.get(
                        "DefaultVersionId"
                    ),
                    "attachment_count": policy.get(
                        "AttachmentCount"
                    ),
                    "is_attachable": policy.get(
                        "IsAttachable"
                    ),
                    "created_date": (
                        policy.get("CreateDate").isoformat()
                        if policy.get("CreateDate")
                        else None
                    ),
                    "updated_date": (
                        policy.get("UpdateDate").isoformat()
                        if policy.get("UpdateDate")
                        else None
                    ),
                }

                # Get default version document
                version_id = policy.get("DefaultVersionId")
                if version_id:
                    ver_resp = await iam.get_policy_version(
                        PolicyArn=policy_arn,
                        VersionId=version_id,
                    )
                    version = ver_resp.get(
                        "PolicyVersion", {}
                    )
                    result["policy_document"] = version.get(
                        "Document"
                    )

                if include_versions:
                    vers_resp = await iam.list_policy_versions(
                        PolicyArn=policy_arn
                    )
                    result["versions"] = [
                        {
                            "version_id": v.get("VersionId"),
                            "is_default": v.get(
                                "IsDefaultVersion"
                            ),
                            "created_date": (
                                v.get(
                                    "CreateDate"
                                ).isoformat()
                                if v.get("CreateDate")
                                else None
                            ),
                        }
                        for v in vers_resp.get("Versions", [])
                    ]

                return result
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS IAM error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Find Access Key
    # ------------------------------------------------------------------

    @tool_schema(FindAccessKeyInput)
    async def aws_iam_find_access_key(
        self, access_key_id: str
    ) -> Dict[str, Any]:
        """Find which IAM user owns a specific access key."""
        try:
            async with self.aws.client("iam") as iam:
                # Must iterate users since there's no direct lookup
                paginator = iam.get_paginator("list_users")
                async for page in paginator.paginate():
                    for user in page.get("Users", []):
                        user_name = user.get("UserName")
                        keys_resp = await iam.list_access_keys(
                            UserName=user_name
                        )
                        for key in keys_resp.get(
                            "AccessKeyMetadata", []
                        ):
                            if (
                                key.get("AccessKeyId")
                                == access_key_id
                            ):
                                # Get last used info
                                try:
                                    used_resp = await iam.get_access_key_last_used(
                                        AccessKeyId=access_key_id
                                    )
                                    last_used = used_resp.get(
                                        "AccessKeyLastUsed", {}
                                    )
                                except ClientError:
                                    last_used = {}

                                return {
                                    "access_key_id": access_key_id,
                                    "user_name": user_name,
                                    "user_arn": user.get("Arn"),
                                    "status": key.get("Status"),
                                    "created_date": (
                                        key.get(
                                            "CreateDate"
                                        ).isoformat()
                                        if key.get("CreateDate")
                                        else None
                                    ),
                                    "last_used_date": (
                                        last_used.get(
                                            "LastUsedDate"
                                        ).isoformat()
                                        if last_used.get(
                                            "LastUsedDate"
                                        )
                                        else None
                                    ),
                                    "last_used_service": last_used.get(
                                        "ServiceName"
                                    ),
                                    "last_used_region": last_used.get(
                                        "Region"
                                    ),
                                }

                return {
                    "access_key_id": access_key_id,
                    "found": False,
                    "message": "Access key not found for any user",
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS IAM error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Active Access Keys
    # ------------------------------------------------------------------

    @tool_schema(ListActiveAccessKeysInput)
    async def aws_iam_list_active_access_keys(
        self,
    ) -> Dict[str, Any]:
        """List all active IAM access keys across all users."""
        try:
            active_keys: List[Dict[str, Any]] = []

            async with self.aws.client("iam") as iam:
                paginator = iam.get_paginator("list_users")
                async for page in paginator.paginate():
                    for user in page.get("Users", []):
                        user_name = user.get("UserName")
                        keys_resp = await iam.list_access_keys(
                            UserName=user_name
                        )
                        for key in keys_resp.get(
                            "AccessKeyMetadata", []
                        ):
                            if key.get("Status") == "Active":
                                active_keys.append(
                                    {
                                        "access_key_id": key.get(
                                            "AccessKeyId"
                                        ),
                                        "user_name": user_name,
                                        "status": key.get(
                                            "Status"
                                        ),
                                        "created_date": (
                                            key.get(
                                                "CreateDate"
                                            ).isoformat()
                                            if key.get(
                                                "CreateDate"
                                            )
                                            else None
                                        ),
                                    }
                                )

            return {
                "active_keys": active_keys,
                "count": len(active_keys),
            }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS IAM error ({error_code}): {e}"
            ) from e
