"""Generate cryptographic API keys and HMAC secrets for AI-Parrot services."""
import base64
import secrets
from pathlib import Path

import click


DEFAULT_API_KEY_BYTES = 48
DEFAULT_HMAC_BYTES = 32


def _generate_api_key(nbytes: int = DEFAULT_API_KEY_BYTES) -> str:
    """Generate a URL-safe base64-encoded API key.

    Args:
        nbytes: Number of random bytes (default 48 → 64-char string).

    Returns:
        URL-safe base64-encoded string with no padding.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode()


def _generate_hmac_secret(nbytes: int = DEFAULT_HMAC_BYTES) -> str:
    """Generate a hex-encoded HMAC secret.

    Args:
        nbytes: Number of random bytes (default 32 → 64-char hex string).

    Returns:
        Lowercase hex string.
    """
    return secrets.token_hex(nbytes)


@click.command("generate-keys")
@click.option(
    "--prefix",
    default="CONCIERGE",
    show_default=True,
    help="Environment variable prefix (e.g. CONCIERGE → CONCIERGE_API_KEY).",
)
@click.option(
    "--api-key-bytes",
    default=DEFAULT_API_KEY_BYTES,
    show_default=True,
    type=int,
    help="Random bytes for the API key.",
)
@click.option(
    "--hmac-bytes",
    default=DEFAULT_HMAC_BYTES,
    show_default=True,
    type=int,
    help="Random bytes for the HMAC secret.",
)
@click.option(
    "--write",
    "env_file",
    default=None,
    type=click.Path(dir_okay=False),
    help="Append generated keys to this .env file.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing keys in the .env file instead of skipping.",
)
def generate_keys(
    prefix: str,
    api_key_bytes: int,
    hmac_bytes: int,
    env_file: str | None,
    force: bool,
) -> None:
    """Generate an API key and HMAC secret for a service.

    \b
    Examples:
      parrot generate-keys
      parrot generate-keys --prefix MYAPP
      parrot generate-keys --write .env
      parrot generate-keys --prefix WEBHOOK --hmac-bytes 64 --write .env
    """
    prefix = prefix.upper().rstrip("_")
    api_key_var = f"{prefix}_API_KEY"
    hmac_var = f"{prefix}_HMAC_SECRET"

    api_key = _generate_api_key(api_key_bytes)
    hmac_secret = _generate_hmac_secret(hmac_bytes)

    lines = [
        f"{api_key_var}={api_key}",
        f"{hmac_var}={hmac_secret}",
    ]

    if env_file is None:
        click.echo()
        for line in lines:
            click.echo(line)
        click.echo()
        click.secho("Copy these into your .env file, or re-run with --write .env", dim=True)
        return

    path = Path(env_file)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    written: list[str] = []
    skipped: list[str] = []

    for line in lines:
        var_name = line.split("=", 1)[0]
        if f"{var_name}=" in existing and not force:
            skipped.append(var_name)
            continue
        if force and f"{var_name}=" in existing:
            # Replace the existing line
            new_lines = []
            for existing_line in existing.splitlines():
                if existing_line.startswith(f"{var_name}="):
                    new_lines.append(line)
                else:
                    new_lines.append(existing_line)
            existing = "\n".join(new_lines) + "\n"
            written.append(var_name)
        else:
            separator = "\n" if existing and not existing.endswith("\n") else ""
            existing += f"{separator}{line}\n"
            written.append(var_name)

    path.write_text(existing, encoding="utf-8")

    if written:
        click.secho(f"Wrote to {env_file}:", fg="green", bold=True)
        for var in written:
            click.echo(f"  {var}")
    if skipped:
        click.secho(f"Skipped (already in {env_file}, use --force to overwrite):", fg="yellow")
        for var in skipped:
            click.echo(f"  {var}")
