"""Telegram notification helper for Investment Memos.

One-shot send of an ``InvestmentMemoOutput`` to a Telegram chat using
``aiogram.Bot`` directly — no polling loop or wrapper required.

Environment variables:
    TELEGRAM_BOT_TOKEN           — Bot token (required).
    FINANCE_TELEGRAM_DESTINATION — Default chat-id when none is supplied.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from navconfig import config

if TYPE_CHECKING:
    from .swarm import InvestmentMemoOutput

logger = logging.getLogger("parrot.finance.telegram_notify")


# ─────────────────────────────────────────────────────────────────────
# Memo → Markdown
# ─────────────────────────────────────────────────────────────────────


def format_memo_markdown(memo: InvestmentMemoOutput) -> str:
    """Convert an ``InvestmentMemoOutput`` to human-readable Markdown.

    The output is compatible with Telegram's ``MarkdownV2`` parse mode
    (special chars are escaped) but is also perfectly readable as plain
    Markdown in logs/files.
    """
    lines: list[str] = []

    # ── Header ───────────────────────────────────────────────────
    lines.append(f"📋 *Investment Memo* — {memo.id}")
    lines.append(f"_Created: {memo.created_at} | Valid until: {memo.valid_until}_")
    lines.append("")

    # ── Executive summary ────────────────────────────────────────
    lines.append("*Executive Summary*")
    lines.append(memo.executive_summary)
    lines.append("")

    # ── Market conditions ────────────────────────────────────────
    lines.append("*Market Conditions*")
    lines.append(memo.market_conditions)
    lines.append("")

    # ── Recommendations ──────────────────────────────────────────
    if memo.recommendations:
        lines.append(f"*Recommendations ({len(memo.recommendations)})*")
        for i, rec in enumerate(memo.recommendations, 1):
            signal_emoji = {
                "BUY": "🟢", "SELL": "🔴", "HOLD": "🟡",
                "SHORT": "🔻", "COVER": "🔺",
            }.get(rec.signal.upper(), "⚪")

            lines.append(
                f"{i}. {signal_emoji} *{rec.asset}* ({rec.asset_class}) "
                f"— {rec.signal} {rec.action}"
            )
            lines.append(
                f"   Size: {rec.sizing_pct:.1f}% | "
                f"SL: {rec.stop_loss:.2f} | "
                f"TP: {rec.take_profit:.2f}" if rec.take_profit else
                f"   Size: {rec.sizing_pct:.1f}% | SL: {rec.stop_loss:.2f}"
            )
            lines.append(f"   Consensus: {rec.consensus_level}")
            lines.append(f"   Bull: {rec.bull_case}")
            lines.append(f"   Bear: {rec.bear_case}")
            lines.append("")
    else:
        lines.append("_No recommendations in this memo._")
        lines.append("")

    # ── Risk warnings ────────────────────────────────────────────
    if memo.risk_warnings:
        lines.append("*⚠️ Risk Warnings*")
        for warning in memo.risk_warnings:
            lines.append(f"• {warning}")
        lines.append("")

    # ── Deliberation info ────────────────────────────────────────
    lines.append(
        f"_Deliberation: {memo.deliberation_rounds} round(s) "
        f"| Consensus: {memo.final_consensus}_"
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Telegram send
# ─────────────────────────────────────────────────────────────────────

def _escape_markdown_v2(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2 parse mode."""
    special = r"_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


async def send_memo_to_telegram(
    memo: InvestmentMemoOutput,
    chat_id: str | int | None = None,
    *,
    use_markdown: bool = True,
) -> bool:
    """Send the investment memo to a Telegram chat.

    Args:
        memo: The ``InvestmentMemoOutput`` to send.
        chat_id: Target chat/user ID.  Falls back to the
            ``FINANCE_TELEGRAM_DESTINATION`` env var.
        use_markdown: Send with Markdown formatting (default ``True``).

    Returns:
        ``True`` if the message was sent successfully, ``False`` otherwise.
    """
    _chat_id = chat_id or config.get("FINANCE_TELEGRAM_DESTINATION")
    if not _chat_id:
        logger.error(
            "Cannot send Telegram notification: no chat_id provided "
            "and FINANCE_TELEGRAM_DESTINATION is not set."
        )
        return False

    bot_token = config.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.error(
            "Cannot send Telegram notification: TELEGRAM_BOT_TOKEN is not set."
        )
        return False

    text = format_memo_markdown(memo)

    try:
        from aiogram import Bot  # noqa: C0415

        bot = Bot(token=bot_token)
        try:
            # Telegram has a 4096-char limit per message.
            # If the memo is longer, split into chunks.
            max_len = 4096
            chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]

            parse_mode = "Markdown" if use_markdown else None
            for chunk in chunks:
                await bot.send_message(
                    chat_id=int(_chat_id),
                    text=chunk,
                    parse_mode=parse_mode,
                )

            logger.info(
                "📨 Investment memo %s sent to Telegram chat %s (%d chunks)",
                memo.id, _chat_id, len(chunks),
            )
            return True

        finally:
            session = bot.session
            if session:
                await session.close()

    except Exception as exc:
        logger.error(
            "Failed to send Telegram notification: %s", exc,
            exc_info=True,
        )
        return False
