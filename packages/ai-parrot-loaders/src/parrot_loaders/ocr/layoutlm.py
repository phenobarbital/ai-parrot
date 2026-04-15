"""
LayoutLMv3 semantic layout analyzer for parrot_loaders.

Uses Microsoft's ``layoutlmv3-base`` model to classify OCR tokens into
semantic categories: title, paragraph, table, list, figure, and caption.

All heavy dependencies (``transformers``, ``torch``) are guarded with
try/except both at module level and inside ``__init__``.  If either
dependency is absent the class can still be imported; only instantiation
will raise ``ImportError``.
"""
import logging
from typing import List, Optional

from PIL import Image

from .models import LayoutLine, LayoutResult, OCRBlock

logger = logging.getLogger(__name__)

# Guard module-level optional imports so the file is importable even when
# the libraries are absent.
try:
    from transformers import (  # type: ignore[import]
        LayoutLMv3ForTokenClassification,
        LayoutLMv3Processor,
    )

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _TRANSFORMERS_AVAILABLE = False

try:
    import torch  # type: ignore[import]

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


class LayoutLMv3Analyzer:
    """Semantic layout analyzer using LayoutLMv3 token classification.

    Loads ``microsoft/layoutlmv3-base`` with ``apply_ocr=False`` (we supply
    our own OCR results) and classifies each word token into one of the
    semantic label categories defined in :attr:`LABEL_MAP`.

    All model-related imports are deferred to ``__init__`` so the class is
    importable even when ``transformers`` / ``torch`` are not installed.

    Attributes:
        LABEL_MAP: Mapping from integer prediction index to semantic label
            string.
    """

    LABEL_MAP = {
        0: "paragraph",
        1: "title",
        2: "list",
        3: "table",
        4: "figure",
        5: "caption",
    }

    def __init__(self, model_name: str = "microsoft/layoutlmv3-base") -> None:
        """Load the LayoutLMv3 model and processor.

        Args:
            model_name: HuggingFace model identifier.

        Raises:
            ImportError: If ``transformers`` or ``torch`` is not installed.
        """
        try:
            from transformers import (  # type: ignore[import]
                LayoutLMv3ForTokenClassification,
                LayoutLMv3Processor,
            )
        except ImportError as exc:
            raise ImportError(
                "transformers is not installed. "
                "Install with: pip install transformers"
            ) from exc

        try:
            import torch as _torch  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "torch is not installed. "
                "Install with: pip install torch"
            ) from exc

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            "Loading LayoutLMv3 model '%s' (this may take a moment on first run).",
            model_name,
        )

        device_str = "cuda" if _torch.cuda.is_available() else "cpu"
        self._device = _torch.device(device_str)

        self._processor = LayoutLMv3Processor.from_pretrained(
            model_name, apply_ocr=False
        )
        self._model = LayoutLMv3ForTokenClassification.from_pretrained(model_name)
        self._model.to(self._device)
        self._model.eval()

        self.logger.info(
            "LayoutLMv3 model loaded on %s.", self._device
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, blocks: List[OCRBlock], image: Image.Image) -> LayoutResult:
        """Classify OCR blocks into semantic regions using LayoutLMv3.

        Args:
            blocks: OCR blocks containing text and bounding boxes.
            image: The PIL image corresponding to the OCR blocks (used by
                the LayoutLMv3 processor for visual features).

        Returns:
            A :class:`LayoutResult` with lines labelled by semantic type.
        """
        import torch as _torch  # type: ignore[import]

        if not blocks:
            return LayoutResult(
                lines=[], tables=[], columns_detected=1, avg_confidence=0.0
            )

        words = [b.text for b in blocks]
        bboxes = self._rescale_bboxes(blocks, image.width, image.height)

        encoding = self._processor(
            image,
            words,
            boxes=bboxes,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=512,
        )
        encoding = {k: v.to(self._device) for k, v in encoding.items()}

        with _torch.no_grad():
            outputs = self._model(**encoding)
            # Shape: (batch=1, seq_len, num_labels) → argmax along label dim
            logits = outputs.logits  # type: ignore[attr-defined]
            predictions = logits.argmax(-1).squeeze().tolist()

        # predictions may be a single int when seq_len==1
        if isinstance(predictions, int):
            predictions = [predictions]

        # Map token predictions back to words (skip special tokens: CLS, SEP, PAD)
        # input_ids shape: (1, seq_len)
        input_ids = encoding["input_ids"].squeeze().tolist()
        word_labels = self._align_predictions_to_words(
            words, input_ids, predictions
        )

        # Build LayoutLines from (word, label) pairs
        lines = self._build_lines(blocks, word_labels)
        tables = self._extract_tables(lines)
        columns_detected = max(1, len(set(b.bbox[0] for b in blocks)) // 2)
        avg_confidence = sum(b.confidence for b in blocks) / len(blocks)

        return LayoutResult(
            lines=lines,
            tables=tables,
            columns_detected=columns_detected,
            avg_confidence=avg_confidence,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rescale_bboxes(
        self,
        blocks: List[OCRBlock],
        image_width: int,
        image_height: int,
        target_size: int = 1000,
    ) -> List[List[int]]:
        """Rescale bounding boxes from pixel coordinates to 0-1000 range.

        LayoutLMv3 requires bounding boxes expressed on a 0–1000 integer
        scale relative to image dimensions.

        Args:
            blocks: OCR blocks whose bboxes will be rescaled.
            image_width: Width of the source image in pixels.
            image_height: Height of the source image in pixels.
            target_size: Target scale (default 1000 as required by LayoutLMv3).

        Returns:
            A list of ``[x1, y1, x2, y2]`` lists rescaled to 0–*target_size*.
        """
        result: List[List[int]] = []
        for b in blocks:
            x1, y1, x2, y2 = b.bbox
            result.append(
                [
                    int(x1 / image_width * target_size),
                    int(y1 / image_height * target_size),
                    int(x2 / image_width * target_size),
                    int(y2 / image_height * target_size),
                ]
            )
        return result

    def _align_predictions_to_words(
        self,
        words: List[str],
        input_ids: List[int],
        predictions: List[int],
    ) -> List[str]:
        """Map token-level predictions back to word-level labels.

        This is a simplified alignment that assigns the first token's label
        to each word.  Subword tokens are skipped.

        Args:
            words: Original word strings.
            input_ids: Tokenised input IDs (includes CLS/SEP/PAD).
            predictions: Per-token label predictions.

        Returns:
            A list of label strings, one per word.
        """
        # Build a word index that mirrors what the processor does:
        # CLS token at position 0, then word tokens, then SEP/PAD
        labels: List[str] = []
        word_idx = 0
        for token_pos, token_id in enumerate(input_ids):
            if word_idx >= len(words):
                break
            # Skip special tokens (usually id 0 or very high ids — a rough
            # heuristic; the exact ids differ per tokenizer)
            if token_pos == 0:
                # CLS token
                continue
            pred = predictions[token_pos] if token_pos < len(predictions) else 0
            label = self.LABEL_MAP.get(pred, "paragraph")
            labels.append(label)
            word_idx += 1

        # Pad with "paragraph" if fewer labels than words
        while len(labels) < len(words):
            labels.append("paragraph")

        return labels[: len(words)]

    def _build_lines(
        self, blocks: List[OCRBlock], labels: List[str]
    ) -> List[LayoutLine]:
        """Combine blocks with their semantic labels into LayoutLine objects.

        Each block becomes its own LayoutLine for simplicity.  The
        ``is_header`` flag is set when the label is ``"title"``.

        Args:
            blocks: OCR blocks.
            labels: Per-block semantic labels.

        Returns:
            List of LayoutLine instances.
        """
        lines: List[LayoutLine] = []
        for block, label in zip(blocks, labels):
            y_center = (block.bbox[1] + block.bbox[3]) / 2.0
            is_header = label == "title"
            lines.append(
                LayoutLine(blocks=[block], y_center=y_center, is_header=is_header)
            )
        return lines

    def _extract_tables(
        self, lines: List[LayoutLine]
    ) -> List[List[List[str]]]:
        """Extract table data from lines labelled as 'table'.

        Consecutive table-labelled lines form a single table.

        Args:
            lines: LayoutLine objects with semantic labels embedded in their
                blocks (not directly accessible, so we rely on consecutive
                grouping).

        Returns:
            List of tables (each a list of row-lists of strings).
        """
        # All table lines in one table for simplicity
        table_rows = [
            [b.text for b in line.blocks]
            for line in lines
            if any(
                getattr(b, "_label", None) == "table" for b in line.blocks
            )
        ]
        return [table_rows] if table_rows else []
