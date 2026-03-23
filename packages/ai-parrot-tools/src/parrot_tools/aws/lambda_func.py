"""AWS Lambda Toolkit for AI-Parrot.

Provides management and invocation of AWS Lambda functions.
"""
from __future__ import annotations
import base64
from typing import Any, Dict, Optional
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from ...interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------


class ListFunctionsInput(BaseModel):
    """Input for listing Lambda functions."""

    limit: int = Field(
        50, description="Maximum number of functions to return per call"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token from a previous response"
    )


class GetFunctionInput(BaseModel):
    """Input for getting Lambda function details."""

    function_name: str = Field(
        ...,
        description="Name of the Lambda function, version, or alias.",
    )
    qualifier: Optional[str] = Field(
        None,
        description="Version or alias to get details for.",
    )


class InvokeFunctionInput(BaseModel):
    """Input for invoking a Lambda function."""

    function_name: str = Field(
        ...,
        description="Name of the Lambda function, version, or alias.",
    )
    payload: Optional[str] = Field(
        None,
        description="JSON payload to send to the function (string format).",
    )
    invocation_type: str = Field(
        "RequestResponse",
        description=(
            "Invocation type: 'RequestResponse' (synchronous), "
            "'Event' (asynchronous), or 'DryRun'."
        ),
    )
    log_type: str = Field(
        "None",
        description="Set to 'Tail' to include the execution log in the response.",
    )
    qualifier: Optional[str] = Field(
        None,
        description="Version or alias to invoke.",
    )


class CreateFunctionInput(BaseModel):
    """Input for creating a new Lambda function."""

    function_name: str = Field(
        ...,
        description="The name of the Lambda function.",
    )
    runtime: str = Field(
        ...,
        description="The identifier of the function's runtime (e.g., 'python3.9').",
    )
    role: str = Field(
        ...,
        description="The Amazon Resource Name (ARN) of the function's execution role.",
    )
    handler: str = Field(
        ...,
        description="The name of the method within your code that Lambda calls to execute your function.",
    )
    description: Optional[str] = Field(
        None,
        description="A description of the function.",
    )
    timeout: int = Field(
        3,
        description="The amount of time (in seconds) that Lambda allows a function to run before stopping it.",
    )
    memory_size: int = Field(
        128,
        description="The amount of memory available to the function at runtime.",
    )
    publish: bool = Field(
        False,
        description="Set to true to publish the first version of the function during creation.",
    )
    zip_file: Optional[str] = Field(
        None,
        description="The base64-encoded contents of the .zip file containing your deployment package.",
    )
    s3_bucket: Optional[str] = Field(
        None, description="An Amazon S3 bucket in the same AWS Region as your function."
    )
    s3_key: Optional[str] = Field(
        None, description="The Amazon S3 key of the deployment package."
    )
    s3_object_version: Optional[str] = Field(
        None, description="For versioned S3 objects, the version of the deployment package object to use."
    )
    environment: Optional[Dict[str, str]] = Field(
        None,
        description="Environment variables for the function.",
    )


class UpdateFunctionCodeInput(BaseModel):
    """Input for updating the code of a Lambda function."""

    function_name: str = Field(
        ...,
        description="The name of the Lambda function.",
    )
    zip_file: Optional[str] = Field(
        None,
        description="The base64-encoded contents of the .zip file containing your deployment package.",
    )
    s3_bucket: Optional[str] = Field(
        None, description="An Amazon S3 bucket in the same AWS Region as your function."
    )
    s3_key: Optional[str] = Field(
        None, description="The Amazon S3 key of the deployment package."
    )
    s3_object_version: Optional[str] = Field(
        None, description="For versioned S3 objects, the version of the deployment package object to use."
    )
    publish: bool = Field(
        False,
        description="Set to true to publish a new version of the function after updating the code.",
    )


class DeleteFunctionInput(BaseModel):
    """Input for deleting a Lambda function."""

    function_name: str = Field(
        ...,
        description="The name of the Lambda function, version, or alias.",
    )
    qualifier: Optional[str] = Field(
        None,
        description="Specify a version number to delete a specific version.",
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class LambdaToolkit(AbstractToolkit):
    """Toolkit for managing and invoking AWS Lambda functions.

    Each public method is exposed as a separate tool with the `aws_lambda_` prefix.

    Available Operations:
    - aws_lambda_list_functions: List Lambda functions
    - aws_lambda_get_function: Get function details
    - aws_lambda_invoke: Invoke a function
    - aws_lambda_create_function: Create a new function (deploy code)
    - aws_lambda_update_function_code: Update function code
    - aws_lambda_delete_function: Delete a function
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
    # List Functions
    # ------------------------------------------------------------------

    @tool_schema(ListFunctionsInput)
    async def aws_lambda_list_functions(
        self,
        limit: int = 50,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Lambda functions with pagination."""
        try:
            async with self.aws.client("lambda") as client:
                params: Dict[str, Any] = {"MaxItems": limit}
                if next_token:
                    params["Marker"] = next_token

                response = await client.list_functions(**params)

                functions = response.get("Functions", [])
                next_marker = response.get("NextMarker")

                # Simplify output
                simplified_functions = []
                for func in functions:
                    simplified_functions.append({
                        "FunctionName": func.get("FunctionName"),
                        "FunctionArn": func.get("FunctionArn"),
                        "Runtime": func.get("Runtime"),
                        "Role": func.get("Role"),
                        "Handler": func.get("Handler"),
                        "LastModified": func.get("LastModified"),
                        "Description": func.get("Description"),
                    })

                return {
                    "functions": simplified_functions,
                    "count": len(functions),
                    "next_token": next_marker,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Lambda error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Function Details
    # ------------------------------------------------------------------

    @tool_schema(GetFunctionInput)
    async def aws_lambda_get_function(
        self,
        function_name: str,
        qualifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get detailed information about a Lambda function."""
        try:
            async with self.aws.client("lambda") as client:
                params: Dict[str, Any] = {"FunctionName": function_name}
                if qualifier:
                    params["Qualifier"] = qualifier

                response = await client.get_function(**params)

                return {
                    "configuration": response.get("Configuration"),
                    "code": response.get("Code"),
                    "tags": response.get("Tags"),
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Lambda error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Invoke Function
    # ------------------------------------------------------------------

    @tool_schema(InvokeFunctionInput)
    async def aws_lambda_invoke(
        self,
        function_name: str,
        payload: Optional[str] = None,
        invocation_type: str = "RequestResponse",
        log_type: str = "None",
        qualifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Invoke a Lambda function."""
        try:
            async with self.aws.client("lambda") as client:
                params: Dict[str, Any] = {
                    "FunctionName": function_name,
                    "InvocationType": invocation_type,
                    "LogType": log_type,
                }
                if payload:
                    # Payload must be bytes or file-like object
                    params["Payload"] = payload.encode("utf-8")
                if qualifier:
                    params["Qualifier"] = qualifier

                response = await client.invoke(**params)

                result_payload = response.get("Payload")
                decoded_payload = None
                if result_payload:
                    decoded_payload = result_payload.read().decode("utf-8")

                log_result = response.get("LogResult")
                if log_result:
                    log_result = base64.b64decode(log_result).decode("utf-8")

                return {
                    "status_code": response.get("StatusCode"),
                    "function_error": response.get("FunctionError"),
                    "payload": decoded_payload,
                    "log_result": log_result,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Lambda error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Create Function
    # ------------------------------------------------------------------

    @tool_schema(CreateFunctionInput)
    async def aws_lambda_create_function(
        self,
        function_name: str,
        runtime: str,
        role: str,
        handler: str,
        description: Optional[str] = None,
        timeout: int = 3,
        memory_size: int = 128,
        publish: bool = False,
        zip_file: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        s3_key: Optional[str] = None,
        s3_object_version: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create a new Lambda function.

        You must provide code via `zip_file` (base64 encoded string) OR
        `s3_bucket` and `s3_key`.
        """
        try:
            async with self.aws.client("lambda") as client:
                code_params: Dict[str, Any] = {}
                if zip_file:
                    code_params["ZipFile"] = base64.b64decode(zip_file)
                elif s3_bucket and s3_key:
                    code_params["S3Bucket"] = s3_bucket
                    code_params["S3Key"] = s3_key
                    if s3_object_version:
                        code_params["S3ObjectVersion"] = s3_object_version
                else:
                    raise ValueError(
                        "Must provide either zip_file or s3_bucket and s3_key."
                    )

                params: Dict[str, Any] = {
                    "FunctionName": function_name,
                    "Runtime": runtime,
                    "Role": role,
                    "Handler": handler,
                    "Code": code_params,
                    "Timeout": timeout,
                    "MemorySize": memory_size,
                    "Publish": publish,
                }

                if description:
                    params["Description"] = description
                if environment:
                    params["Environment"] = {"Variables": environment}

                response = await client.create_function(**params)

                return response
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Lambda error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Update Function Code
    # ------------------------------------------------------------------

    @tool_schema(UpdateFunctionCodeInput)
    async def aws_lambda_update_function_code(
        self,
        function_name: str,
        zip_file: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        s3_key: Optional[str] = None,
        s3_object_version: Optional[str] = None,
        publish: bool = False,
    ) -> Dict[str, Any]:
        """Update the code of an existing Lambda function.

        You must provide code via `zip_file` (base64 encoded string) OR
        `s3_bucket` and `s3_key`.
        """
        try:
            async with self.aws.client("lambda") as client:
                params: Dict[str, Any] = {
                    "FunctionName": function_name,
                    "Publish": publish,
                }

                if zip_file:
                    params["ZipFile"] = base64.b64decode(zip_file)
                elif s3_bucket and s3_key:
                    params["S3Bucket"] = s3_bucket
                    params["S3Key"] = s3_key
                    if s3_object_version:
                        params["S3ObjectVersion"] = s3_object_version
                else:
                    raise ValueError(
                        "Must provide either zip_file or s3_bucket and s3_key."
                    )

                response = await client.update_function_code(**params)

                return response
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Lambda error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Delete Function
    # ------------------------------------------------------------------

    @tool_schema(DeleteFunctionInput)
    async def aws_lambda_delete_function(
        self,
        function_name: str,
        qualifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete a Lambda function."""
        try:
            async with self.aws.client("lambda") as client:
                params: Dict[str, Any] = {"FunctionName": function_name}
                if qualifier:
                    params["Qualifier"] = qualifier

                await client.delete_function(**params)

                return {
                    "status": "deleted",
                    "function_name": function_name,
                }
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(
                f"AWS Lambda error ({error_code}): {e}"
            ) from e
