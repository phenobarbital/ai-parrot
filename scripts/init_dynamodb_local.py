"""Create parrot-conversations and parrot-artifacts in DynamoDB Local.

Idempotent: if a table already exists the script just reports it and
skips creation. TTL is enabled on the `ttl` attribute for both tables.

Usage:
    source .venv/bin/activate
    python scripts/init_dynamodb_local.py

Reads configuration from env/.env via the project's navconfig layer
(`parrot.conf`), so it picks up whatever DYNAMODB_ENDPOINT_URL /
DYNAMODB_REGION / DYNAMODB_CONVERSATIONS_TABLE / DYNAMODB_ARTIFACTS_TABLE
are set there.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Dict

import aioboto3
from botocore.exceptions import ClientError

from parrot.conf import (
    AWS_ACCESS_KEY,
    AWS_SECRET_KEY,
    DYNAMODB_ARTIFACTS_TABLE,
    DYNAMODB_CONVERSATIONS_TABLE,
    DYNAMODB_ENDPOINT_URL,
    DYNAMODB_REGION,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("init_dynamodb_local")


TABLE_DEFINITIONS = [
    DYNAMODB_CONVERSATIONS_TABLE,
    DYNAMODB_ARTIFACTS_TABLE,
]


def _client_kwargs() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"region_name": DYNAMODB_REGION or "us-east-1"}
    if DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = DYNAMODB_ENDPOINT_URL
    if AWS_ACCESS_KEY:
        kwargs["aws_access_key_id"] = AWS_ACCESS_KEY
    if AWS_SECRET_KEY:
        kwargs["aws_secret_access_key"] = AWS_SECRET_KEY
    return kwargs


async def _ensure_table(client, table_name: str) -> None:
    try:
        await client.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        logger.info("Created table %s", table_name)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"ResourceInUseException", "TableAlreadyExistsException"}:
            logger.info("Table %s already exists — skipping", table_name)
        else:
            raise

    waiter = client.get_waiter("table_exists")
    await waiter.wait(TableName=table_name)

    try:
        await client.update_time_to_live(
            TableName=table_name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
        logger.info("TTL enabled on %s (attribute: ttl)", table_name)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        # DynamoDB Local + some AWS states raise when TTL is already on.
        if code in {"ValidationException", "TimeToLiveAlreadyEnabledException"}:
            logger.info("TTL already enabled on %s", table_name)
        else:
            raise


async def main() -> int:
    if not DYNAMODB_ENDPOINT_URL:
        logger.warning(
            "DYNAMODB_ENDPOINT_URL is not set — this script would "
            "operate against real AWS DynamoDB. Refusing to run."
        )
        logger.warning(
            "Set DYNAMODB_ENDPOINT_URL=http://localhost:8000 in env/.env "
            "(see [dynamodb] section) and re-run."
        )
        return 1

    logger.info("Target endpoint: %s (region=%s)", DYNAMODB_ENDPOINT_URL, DYNAMODB_REGION)
    session = aioboto3.Session()
    async with session.client("dynamodb", **_client_kwargs()) as client:
        for table in TABLE_DEFINITIONS:
            await _ensure_table(client, table)
    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
