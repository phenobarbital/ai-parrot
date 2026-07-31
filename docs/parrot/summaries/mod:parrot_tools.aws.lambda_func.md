---
type: Wiki Summary
title: parrot_tools.aws.lambda_func
id: mod:parrot_tools.aws.lambda_func
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AWS Lambda Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.lambda_func.CreateFunctionInput
  rel: defines
- concept: class:parrot_tools.aws.lambda_func.DeleteFunctionInput
  rel: defines
- concept: class:parrot_tools.aws.lambda_func.GetFunctionInput
  rel: defines
- concept: class:parrot_tools.aws.lambda_func.InvokeFunctionInput
  rel: defines
- concept: class:parrot_tools.aws.lambda_func.LambdaToolkit
  rel: defines
- concept: class:parrot_tools.aws.lambda_func.ListFunctionsInput
  rel: defines
- concept: class:parrot_tools.aws.lambda_func.UpdateFunctionCodeInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.lambda_func`

AWS Lambda Toolkit for AI-Parrot.

Provides management and invocation of AWS Lambda functions.

## Classes

- **`ListFunctionsInput(BaseModel)`** — Input for listing Lambda functions.
- **`GetFunctionInput(BaseModel)`** — Input for getting Lambda function details.
- **`InvokeFunctionInput(BaseModel)`** — Input for invoking a Lambda function.
- **`CreateFunctionInput(BaseModel)`** — Input for creating a new Lambda function.
- **`UpdateFunctionCodeInput(BaseModel)`** — Input for updating the code of a Lambda function.
- **`DeleteFunctionInput(BaseModel)`** — Input for deleting a Lambda function.
- **`LambdaToolkit(AbstractToolkit)`** — Toolkit for managing and invoking AWS Lambda functions.
