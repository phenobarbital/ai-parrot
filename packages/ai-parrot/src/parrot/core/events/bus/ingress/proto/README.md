# parrot.events.v1 proto (FEAT-310 gRPC ingress)

`events.proto` defines the `parrot.events.v1.EventBusIngress` service used
by `GrpcIngress` (`parrot/core/events/bus/ingress/grpc.py`).

The generated modules (`events_pb2.py`, `events_pb2_grpc.py`) are committed
alongside the source `.proto`. They are **generated code** — do not edit
them by hand and keep them excluded from linting.

## Regenerating

Requires the optional extra (`pip install ai-parrot[grpc]`, which brings
`grpcio-tools`). From the repository root:

```bash
source .venv/bin/activate
python -m grpc_tools.protoc -I packages/ai-parrot/src \
  --python_out=packages/ai-parrot/src \
  --grpc_python_out=packages/ai-parrot/src \
  packages/ai-parrot/src/parrot/core/events/bus/ingress/proto/events.proto
```

Regenerate whenever `events.proto` changes and commit the updated pb2
modules in the same commit. Keep `grpcio` / `grpcio-tools` versions in sync
(same minor) to avoid runtime descriptor incompatibilities.
