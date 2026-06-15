"""Manifest-driven downloader for compliance corpus sources.

Downloads each source defined in ``manifest.yaml``, verifies the SHA-256
checksum, and writes the file to ``raw/`` relative to this script.

Usage::

    # Download all sources (skip existing and verified files):
    python -m corpus.compliance_soc2_hipaa.fetch

    # Compute and print SHA-256 for all downloaded files:
    python -m corpus.compliance_soc2_hipaa.fetch --compute-sha

    # Override output directory:
    python -m corpus.compliance_soc2_hipaa.fetch --output-dir /tmp/corpus/raw

    # Use a custom manifest:
    python -m corpus.compliance_soc2_hipaa.fetch --manifest /path/to/manifest.yaml

Note:
    Sources marked ``redistributable: false`` (e.g., AICPA TSC) cannot be
    downloaded automatically — the script will emit a warning and skip them.
    Place those files manually per the ``placement_note`` in the manifest.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("corpus.compliance_soc2_hipaa.fetch")

_MANIFEST_PATH = Path(__file__).parent / "manifest.yaml"
_DEFAULT_OUTPUT_DIR = Path(__file__).parent / "raw"


def _compute_sha256(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of a file.

    Args:
        path: Path to the file to hash.

    Returns:
        40-character hexadecimal SHA-256 digest (lowercase).
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(manifest_path: Path) -> dict:
    """Load and parse the YAML manifest.

    Args:
        manifest_path: Path to the manifest YAML file.

    Returns:
        Parsed manifest dict.

    Raises:
        FileNotFoundError: When the manifest file does not exist.
        ValueError: When the manifest is malformed.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to load the manifest: pip install pyyaml"
        ) from exc
    with manifest_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "sources" not in data:
        raise ValueError(f"Invalid manifest: expected dict with 'sources' key at {manifest_path}")
    return data


async def _download_file(url: str, dest: Path) -> None:
    """Asynchronously download a URL to a destination path.

    Uses ``aiohttp`` as required by the project's no-requests/no-httpx rule.

    Args:
        url: The URL to download.
        dest: Destination file path.

    Raises:
        RuntimeError: When the HTTP response status is not 200.
    """
    try:
        import aiohttp
    except ImportError as exc:
        raise ImportError(
            "aiohttp is required for downloads: pip install aiohttp"
        ) from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"HTTP {resp.status} downloading {url}"
                )
            with dest.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(65536):
                    fh.write(chunk)


async def fetch_all(
    manifest_path: Path = _MANIFEST_PATH,
    output_dir: Path = _DEFAULT_OUTPUT_DIR,
    compute_sha: bool = False,
) -> dict[str, str]:
    """Download all redistributable sources defined in the manifest.

    Idempotent: skips files that already exist and whose SHA-256 matches
    the manifest entry (when a checksum is specified).

    Args:
        manifest_path: Path to the manifest YAML.
        output_dir: Directory to write downloaded files into.
        compute_sha: When ``True``, print SHA-256 digests for all present
            files (useful for filling in manifest placeholders).

    Returns:
        Mapping of source name → absolute file path for each downloaded file.
    """
    manifest = _load_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}

    for source in manifest.get("sources", []):
        name: str = source.get("name", "<unknown>")
        url: Optional[str] = source.get("url")
        filename: Optional[str] = source.get("filename")
        sha256_expected: Optional[str] = source.get("sha256")
        redistributable: bool = source.get("redistributable", True)
        placement_note: Optional[str] = source.get("placement_note")

        if not redistributable:
            dest = output_dir / (filename or "unknown")
            if dest.exists():
                logger.info("[%s] Found at %s (non-redistributable, manual placement)", name, dest)
                if compute_sha:
                    print(f"  sha256 ({name}): {_compute_sha256(dest)}")
                results[name] = str(dest)
            else:
                logger.warning(
                    "[%s] SKIP — non-redistributable source. Manual placement required.\n"
                    "       %s",
                    name,
                    placement_note or f"Place file at {dest}",
                )
            continue

        if not url:
            logger.warning("[%s] SKIP — no URL in manifest", name)
            continue

        if not filename:
            filename = url.split("/")[-1] or "download"
        dest = output_dir / filename

        if dest.exists():
            if sha256_expected:
                actual = _compute_sha256(dest)
                if actual == sha256_expected:
                    logger.info("[%s] Already present and verified — skip", name)
                    if compute_sha:
                        print(f"  sha256 ({name}): {actual}")
                    results[name] = str(dest)
                    continue
                else:
                    logger.warning(
                        "[%s] Checksum mismatch — re-downloading "
                        "(expected=%s actual=%s)",
                        name, sha256_expected, actual,
                    )
            else:
                logger.info("[%s] Already present (no SHA to verify) — skip", name)
                if compute_sha:
                    print(f"  sha256 ({name}): {_compute_sha256(dest)}")
                results[name] = str(dest)
                continue

        logger.info("[%s] Downloading %s → %s", name, url, dest)
        try:
            await _download_file(url, dest)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Download failed: %s", name, exc)
            continue

        actual = _compute_sha256(dest)
        if sha256_expected and actual != sha256_expected:
            logger.error(
                "[%s] SHA-256 mismatch after download (expected=%s actual=%s) — removing file",
                name, sha256_expected, actual,
            )
            dest.unlink(missing_ok=True)
            continue

        if compute_sha:
            print(f"  sha256 ({name}): {actual}")
        logger.info("[%s] Downloaded and verified (%s)", name, dest)
        results[name] = str(dest)

    return results


def main() -> None:
    """Entry point for ``python -m corpus.compliance_soc2_hipaa.fetch``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        description="Download compliance corpus sources from manifest.yaml"
    )
    parser.add_argument(
        "--manifest",
        default=str(_MANIFEST_PATH),
        help="Path to manifest YAML (default: manifest.yaml next to this script)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_DEFAULT_OUTPUT_DIR),
        help="Directory to write downloads into (default: raw/ next to this script)",
    )
    parser.add_argument(
        "--compute-sha",
        action="store_true",
        help="Print SHA-256 digests for all files (use to fill manifest placeholders)",
    )
    args = parser.parse_args()
    results = asyncio.run(
        fetch_all(
            manifest_path=Path(args.manifest),
            output_dir=Path(args.output_dir),
            compute_sha=args.compute_sha,
        )
    )
    print(f"\nDownloaded {len(results)} source(s):")
    for name, path in results.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
