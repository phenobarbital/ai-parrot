---
type: Wiki Entity
title: LambdaToolkit
id: class:parrot_tools.aws.lambda_func.LambdaToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for managing and invoking AWS Lambda functions.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# LambdaToolkit

Defined in [`parrot_tools.aws.lambda_func`](../summaries/mod:parrot_tools.aws.lambda_func.md).

```python
class LambdaToolkit(AbstractToolkit)
```

Toolkit for managing and invoking AWS Lambda functions.

Each public method is exposed as a separate tool with the `aws_lambda_` prefix.

Available Operations:
- aws_lambda_list_functions: List Lambda functions
- aws_lambda_get_function: Get function details
- aws_lambda_invoke: Invoke a function
- aws_lambda_create_function: Create a new function (deploy code)
- aws_lambda_update_function_code: Update function code
- aws_lambda_delete_function: Delete a function

## Methods

- `async def aws_lambda_list_functions(self, limit: int=50, next_token: Optional[str]=None) -> Dict[str, Any]` — List Lambda functions with pagination.
- `async def aws_lambda_get_function(self, function_name: str, qualifier: Optional[str]=None) -> Dict[str, Any]` — Get detailed information about a Lambda function.
- `async def aws_lambda_invoke(self, function_name: str, payload: Optional[str]=None, invocation_type: str='RequestResponse', log_type: str='None', qualifier: Optional[str]=None) -> Dict[str, Any]` — Invoke a Lambda function.
- `async def aws_lambda_create_function(self, function_name: str, runtime: str, role: str, handler: str, description: Optional[str]=None, timeout: int=3, memory_size: int=128, publish: bool=False, zip_file: Optional[str]=None, s3_bucket: Optional[str]=None, s3_key: Optional[str]=None, s3_object_version: Optional[str]=None, environment: Optional[Dict[str, str]]=None) -> Dict[str, Any]` — Create a new Lambda function.
- `async def aws_lambda_update_function_code(self, function_name: str, zip_file: Optional[str]=None, s3_bucket: Optional[str]=None, s3_key: Optional[str]=None, s3_object_version: Optional[str]=None, publish: bool=False) -> Dict[str, Any]` — Update the code of an existing Lambda function.
- `async def aws_lambda_delete_function(self, function_name: str, qualifier: Optional[str]=None) -> Dict[str, Any]` — Delete a Lambda function.
