"""G2 Arrow IPC over Cap'n Proto RPC mTLS transport spike (FEAT-746)."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import ssl
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

import capnp
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.ipc
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

SCHEMA = capnp.load(str(Path(__file__).with_name("spike.capnp")))
MAX_FRAME = 4 * 1024 * 1024
DEFAULT_FRAME = MAX_FRAME // 4
CLIENT_SAN = "squawk://external/caller"
HELLO_TOKEN = b"g2-hello-token"


def _write_pem(path: Path, value: bytes) -> None:
    """Write a PEM artifact with owner-only permissions."""
    path.write_bytes(value)
    path.chmod(0o600)


def _issue_certificate(
    subject: x509.Name,
    issuer: x509.Name,
    public_key: rsa.RSAPublicKey,
    issuer_key: rsa.RSAPrivateKey,
    *,
    is_ca: bool,
    san: x509.SubjectAlternativeName | None = None,
) -> x509.Certificate:
    """Issue one short-lived certificate for the local spike PKI."""
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=not is_ca,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=is_ca,
                crl_sign=is_ca,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    )
    if san is not None:
        builder = builder.add_extension(san, critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


def make_certs(tmp: Path) -> tuple[ssl.SSLContext, ssl.SSLContext]:
    """Create loopback mTLS contexts with the client Squawk URI SAN."""
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "G2 spike CA")])
    ca_cert = _issue_certificate(ca_name, ca_name, ca_key.public_key(), ca_key, is_ca=True)

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    server_cert = _issue_certificate(
        server_name,
        ca_name,
        server_key.public_key(),
        ca_key,
        is_ca=False,
        san=x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
    )

    client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "G2 spike caller")])
    client_cert = _issue_certificate(
        client_name,
        ca_name,
        client_key.public_key(),
        ca_key,
        is_ca=False,
        san=x509.SubjectAlternativeName([x509.UniformResourceIdentifier(CLIENT_SAN)]),
    )

    ca_path = tmp / "ca.pem"
    server_cert_path = tmp / "server-cert.pem"
    server_key_path = tmp / "server-key.pem"
    client_cert_path = tmp / "client-cert.pem"
    client_key_path = tmp / "client-key.pem"
    _write_pem(ca_path, ca_cert.public_bytes(serialization.Encoding.PEM))
    _write_pem(server_cert_path, server_cert.public_bytes(serialization.Encoding.PEM))
    _write_pem(
        server_key_path,
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    _write_pem(client_cert_path, client_cert.public_bytes(serialization.Encoding.PEM))
    _write_pem(
        client_key_path,
        client_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )

    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(server_cert_path, server_key_path)
    server_context.load_verify_locations(cafile=ca_path)
    server_context.verify_mode = ssl.CERT_REQUIRED
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_path))
    client_context.load_cert_chain(client_cert_path, client_key_path)
    return server_context, client_context


def _serialize_table(table: pa.Table) -> bytes:
    """Encode one table slice as a standalone Arrow IPC stream."""
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def frames_from_df(df: pd.DataFrame, max_bytes: int) -> Iterator[bytes]:
    """Yield self-contained Arrow IPC streams no larger than ``max_bytes``."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    table = pa.Table.from_pandas(df, preserve_index=False)
    offset = 0
    rows_per_frame = max(1, min(table.num_rows, 16_384))
    while offset < table.num_rows:
        remaining = table.num_rows - offset
        rows = min(rows_per_frame, remaining)
        while True:
            payload = _serialize_table(table.slice(offset, rows))
            if len(payload) <= max_bytes:
                break
            if rows == 1:
                raise ValueError("one Arrow row exceeds max_bytes")
            rows = max(1, rows // 2)
        yield payload
        offset += rows
        if rows and len(payload):
            rows_per_frame = max(1, min(remaining - rows, max_bytes * rows // len(payload)))


class OpImpl(SCHEMA.Op.Server):
    """Cancellation capability for one active producer."""

    def __init__(self, cancel: asyncio.Event) -> None:
        self._cancel = cancel

    async def cancel(self, **kwargs: object) -> None:
        """Request that the producer stop after its current complete frame."""
        self._cancel.set()


class SpikeImpl(SCHEMA.Spike.Server):
    """Local server implementation that records handshake identity evidence."""

    def __init__(self, peer_san: str, observations: dict[str, object]) -> None:
        self._peer_san = peer_san
        self._observations = observations

    async def hello(self, agentId: str, token: bytes, **kwargs: object) -> tuple[str, str]:
        """Record the Hello authentication material observed server-side."""
        self._observations["hello_agent_id"] = agentId
        self._observations["hello_token"] = bytes(token)
        return "sess-1", self._peer_san

    async def stream(self, rows: int, maxFrameBytes: int, sink: object, **kwargs: object) -> OpImpl:
        """Start a cancellable Arrow frame producer and return its operation."""
        cancel = asyncio.Event()
        df = build_frame(rows)

        async def produce() -> None:
            status = "OK"
            for index, frame in enumerate(frames_from_df(df, maxFrameBytes)):
                if cancel.is_set():
                    status = "PARTIAL"
                    break
                await sink.frame(data=frame, index=index)
                await asyncio.sleep(0)
            if cancel.is_set():
                status = "PARTIAL"
            await sink.done(status=status)

        asyncio.create_task(produce())
        return OpImpl(cancel)


def build_frame(rows: int) -> pd.DataFrame:
    """Build deterministic numeric/string data for the throughput measurement."""
    rng = np.random.default_rng(746)
    return pd.DataFrame({f"c{i}": rng.random(rows) for i in range(8)} | {"label": rng.choice(["a", "b", "c"], rows)})


def _peer_san(stream: capnp.AsyncIoStream) -> str:
    """Extract the client URI SAN from the server-side TLS transport."""
    ssl_object = stream.protocol.transport.get_extra_info("ssl_object")
    if ssl_object is None:
        raise RuntimeError("mTLS transport has no SSL object")
    certificate = ssl_object.getpeercert(binary_form=True)
    if certificate is None:
        raise RuntimeError("mTLS transport has no peer certificate")
    extensions = x509.load_der_x509_certificate(certificate).extensions
    san = extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    for value in san.get_values_for_type(x509.UniformResourceIdentifier):
        if value.startswith("squawk://"):
            return value
    raise RuntimeError("mTLS peer certificate has no Squawk URI SAN")


async def run(rows: int, cancel_at_frame: int | None) -> dict[str, object]:
    """Run loopback mTLS RPC and return frame, cancellation, and identity evidence."""
    received: list[bytes] = []
    done = asyncio.Event()
    observations: dict[str, object] = {}
    client_op: object | None = None

    class SinkImpl(SCHEMA.Sink.Server):
        """Client callback capability that validates frame order and requests cancellation."""

        def __init__(self) -> None:
            self.status = ""

        async def frame(self, data: bytes, index: int, **kwargs: object) -> None:
            """Collect one complete Arrow IPC frame and cancel at the requested index."""
            nonlocal client_op
            if index != len(received):
                raise AssertionError(f"received frame {index} after {len(received)} frames")
            received.append(bytes(data))
            if cancel_at_frame is not None and index == cancel_at_frame:
                while client_op is None:
                    await asyncio.sleep(0)
                await client_op.cancel()

        async def done(self, status: str, **kwargs: object) -> None:
            """Capture the terminal producer status."""
            self.status = status
            done.set()

    sink = SinkImpl()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="g2-capnp-arrow-") as temp_dir:
        server_context, client_context = make_certs(Path(temp_dir))
        server_instances: list[capnp.TwoPartyServer] = []

        async def on_connection(stream: capnp.AsyncIoStream) -> None:
            """Bootstrap one authenticated Cap'n Proto RPC connection."""
            peer_san = _peer_san(stream)
            observations["peer_san"] = peer_san
            server = capnp.TwoPartyServer(stream, bootstrap=SpikeImpl(peer_san, observations))
            server_instances.append(server)
            await server.on_disconnect()

        async with capnp.kj_loop():
            listener = await capnp.AsyncIoStream.create_server(
                on_connection,
                "127.0.0.1",
                0,
                ssl=server_context,
            )
            if not listener.sockets:
                listener.close()
                await listener.wait_closed()
                raise PermissionError(1, "loopback listener unavailable in this execution environment")
            port = listener.sockets[0].getsockname()[1]
            stream = await capnp.AsyncIoStream.create_connection(
                "127.0.0.1",
                port,
                ssl=client_context,
                server_hostname="127.0.0.1",
            )
            client = capnp.TwoPartyClient(stream)
            remote = client.bootstrap().cast_as(SCHEMA.Spike)
            hello = await remote.hello(agentId="external/caller", token=HELLO_TOKEN)
            operation = await remote.stream(rows=rows, maxFrameBytes=DEFAULT_FRAME, sink=sink)
            client_op = operation.op
            await asyncio.wait_for(done.wait(), timeout=30)
            listener.close()
            await listener.wait_closed()
            stream.close()
            client.close()
    elapsed = time.perf_counter() - started
    frame_sizes = [len(frame) for frame in received]
    frames_valid = all(pa.ipc.open_stream(frame).read_all().num_rows > 0 for frame in received)
    result = {
        "status": sink.status,
        "frames": len(received),
        "frames_valid": frames_valid,
        "max_frame_bytes": max(frame_sizes, default=0),
        "bytes_received": sum(frame_sizes),
        "throughput_mib_s": sum(frame_sizes) / max(elapsed, 0.001) / (1024 * 1024),
        "peer_san": observations.get("peer_san", ""),
        "hello_peer_san": str(hello.peerSan),
        "hello_token_observed": observations.get("hello_token") == HELLO_TOKEN,
        "hello_agent_id": observations.get("hello_agent_id", ""),
    }
    expected_status = "PARTIAL" if cancel_at_frame is not None else "OK"
    if result["status"] != expected_status or not frames_valid:
        raise AssertionError(f"unexpected stream outcome: {result}")
    if result["max_frame_bytes"] > DEFAULT_FRAME:
        raise AssertionError(f"frame exceeded ceiling: {result}")
    if result["peer_san"] != CLIENT_SAN or not result["hello_token_observed"]:
        raise AssertionError(f"identity evidence missing: {result}")
    return result


def main() -> int:
    """Run full and cancelled G2 measurements and emit a JSON summary."""
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 1_500_000
    out = {
        "full": capnp.run(run(rows, None)),
        "cancelled": capnp.run(run(rows, 10)),
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
