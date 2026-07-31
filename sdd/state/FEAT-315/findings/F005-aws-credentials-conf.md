# F005 — AWS_CREDENTIALS in parrot.conf: profile dict keyed by aws_id

**Query**: Q008 · **Type**: grep + read · `packages/ai-parrot/src/parrot/conf.py:490-531`

`AWS_CREDENTIALS` is a dict of named profiles: `default`, `monitoring`,
`cloudwatch`, `backend`, `security`, `security_bucket`. Each profile has keys:
`use_credentials`, `aws_key`, `aws_secret`, `region_name` (+ optional
`bucket_name`). Consumers pass an `aws_id` (profile name) to select one.

Existing consumers: `clients/bedrock.py` (aws_id kwarg — but with wrong key
names, see F004), `interfaces/aws.py` (correct canonical resolver with
'default' fallback), `storage/backends/__init__.py` (DYNAMODB_AWS_PROFILE),
S3/blob storage in parrot-formdesigner.

Related conf vars: `BEDROCK_AWS_REGION`, `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`,
`AWS_SESSION_TOKEN`, `AWS_REGION_NAME`.

## Citations
- packages/ai-parrot/src/parrot/conf.py:490-531
- packages/ai-parrot/src/parrot/interfaces/aws.py:46-56
