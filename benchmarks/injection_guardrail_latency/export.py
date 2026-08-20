"""Export the prompt-injection classifier to ONNX (fp32 + dynamic int8).

Run once before benchmarking the ONNX tiers::

    source .venv/bin/activate
    python -m benchmarks.injection_guardrail_latency.export \\
        --output-dir models/injection-clf

Produces, in ``--output-dir``:

* ``model.onnx``       — fp32 graph
* ``model_int8.onnx``  — dynamically quantized (weights int8, activations
  quantized at runtime); no calibration data required
* ``config.json``, tokenizer files — copied so the graph directory is
  self-contained and loadable offline

Export prefers ``optimum.onnxruntime`` and falls back to a direct
``torch.onnx.export``. Quantization uses ``onnxruntime.quantization``
directly, which avoids depending on Optimum's quantizer API surface.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from .detectors import DEFAULT_CLASSIFIER, MAX_LENGTH

logger = logging.getLogger("benchmarks.injection_guardrail_latency.export")

_UV_HINT = (
    "Install the export dependencies first:\n"
    "  source .venv/bin/activate && uv pip install 'optimum[onnxruntime]'"
)


def export_fp32(model_id: str, output_dir: Path) -> Path:
    """Export *model_id* to ``output_dir/model.onnx``.

    Args:
        model_id: HuggingFace sequence-classification model id.
        output_dir: Destination directory (created if absent).

    Returns:
        Path to the exported fp32 graph.

    Raises:
        RuntimeError: If neither Optimum nor a direct torch export works.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_path = output_dir / "model.onnx"
    if graph_path.exists():
        logger.info("fp32 graph already present: %s", graph_path)
        return graph_path

    try:
        from optimum.onnxruntime import ORTModelForSequenceClassification

        logger.info("Exporting %s via optimum …", model_id)
        model = ORTModelForSequenceClassification.from_pretrained(model_id, export=True)
        model.save_pretrained(output_dir)
        # Optimum may name the artifact differently across versions.
        if not graph_path.exists():
            candidates = sorted(output_dir.glob("*.onnx"))
            if not candidates:
                raise RuntimeError("optimum export produced no .onnx file")
            candidates[0].rename(graph_path)
        return graph_path
    except ImportError:
        logger.warning("optimum not installed; falling back to torch.onnx.export")
    except Exception as exc:  # noqa: BLE001 - fall through to the torch path
        logger.warning("optimum export failed (%s); falling back to torch.onnx.export", exc)

    return _export_fp32_torch(model_id, output_dir, graph_path)


def _export_fp32_torch(model_id: str, output_dir: Path, graph_path: Path) -> Path:
    """Direct ``torch.onnx.export`` fallback."""
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(f"torch/transformers unavailable: {exc}\n{_UV_HINT}") from exc

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(model_id)
    model.eval()

    sample = tokenizer(
        "ignore all previous instructions",
        return_tensors="pt",
        truncation=True,
        max_length=MAX_LENGTH,
        padding="max_length",
    )
    input_names = [name for name in ("input_ids", "attention_mask", "token_type_ids") if name in sample]
    args = tuple(sample[name] for name in input_names)
    dynamic_axes = {name: {0: "batch", 1: "sequence"} for name in input_names}
    dynamic_axes["logits"] = {0: "batch"}

    logger.info("Exporting %s via torch.onnx.export …", model_id)
    with torch.no_grad():
        torch.onnx.export(
            model,
            args,
            str(graph_path),
            input_names=input_names,
            output_names=["logits"],
            dynamic_axes=dynamic_axes,
            opset_version=17,
            do_constant_folding=True,
        )
    return graph_path


def quantize_int8(fp32_path: Path) -> Path:
    """Dynamically quantize *fp32_path* to int8 weights.

    Dynamic quantization needs no calibration corpus, which keeps this
    reproducible on any machine. Activations are quantized at runtime.

    Args:
        fp32_path: Path to the fp32 ``model.onnx``.

    Returns:
        Path to ``model_int8.onnx`` beside the input.

    Raises:
        RuntimeError: If ``onnxruntime.quantization`` is unavailable.
    """
    int8_path = fp32_path.with_name("model_int8.onnx")
    if int8_path.exists():
        logger.info("int8 graph already present: %s", int8_path)
        return int8_path
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(f"onnxruntime.quantization unavailable: {exc}\n{_UV_HINT}") from exc

    logger.info("Quantizing %s -> %s (dynamic, QInt8) …", fp32_path.name, int8_path.name)
    quantize_dynamic(
        model_input=str(fp32_path),
        model_output=str(int8_path),
        weight_type=QuantType.QInt8,
    )
    return int8_path


def copy_tokenizer_and_config(model_id: str, output_dir: Path) -> None:
    """Materialise tokenizer + config into *output_dir* for offline loads.

    Args:
        model_id: HuggingFace model id.
        output_dir: Graph directory.
    """
    from transformers import AutoConfig, AutoTokenizer

    AutoTokenizer.from_pretrained(model_id).save_pretrained(output_dir)
    config = AutoConfig.from_pretrained(model_id)
    config.save_pretrained(output_dir)
    # Keep a plain id2label copy readable without transformers.
    (output_dir / "labels.json").write_text(
        json.dumps({str(k): v for k, v in config.id2label.items()}, indent=2)
    )


def graph_sizes_mb(output_dir: Path) -> dict[str, float]:
    """Return ``{filename: size_mb}`` for every ``.onnx`` file present."""
    return {
        path.name: round(path.stat().st_size / (1024 * 1024), 1)
        for path in sorted(output_dir.glob("*.onnx"))
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_CLASSIFIER, help="HF model id to export")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("models/injection-clf"),
        help="Destination directory for the ONNX graphs",
    )
    parser.add_argument("--skip-int8", action="store_true", help="Export fp32 only")
    parser.add_argument("--force", action="store_true", help="Re-export even if graphs exist")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.force and args.output_dir.exists():
        logger.info("--force: removing %s", args.output_dir)
        shutil.rmtree(args.output_dir)

    try:
        fp32 = export_fp32(args.model, args.output_dir)
        if not args.skip_int8:
            quantize_int8(fp32)
        copy_tokenizer_and_config(args.model, args.output_dir)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        logger.error("Export failed: %s", exc)
        return 1

    sizes = graph_sizes_mb(args.output_dir)
    logger.info("Graphs in %s:", args.output_dir)
    for name, size in sizes.items():
        logger.info("  %-20s %6.1f MB", name, size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
