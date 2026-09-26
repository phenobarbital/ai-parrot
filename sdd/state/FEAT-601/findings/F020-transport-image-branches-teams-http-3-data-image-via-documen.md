---
id: F020
query_id: Q020
type: grep
intent: Per-transport branch rendering http(s) URLs vs local paths (telegram, msteams, whatsapp, slack)
executed_at: 2026-09-24T23:21:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F020 — Transport image branches: Teams (http, ≤3) + data:image via documents; Slack http only; Telegram FSInputFile; WhatsApp str(path)

## Summary
Teams `_parsed_to_card_spec` turns `parsed.images[:3]` into an `ImageSection` only for strings starting with `http://` or `https://`; local paths become a subtle "Image: name" text. It also embeds `documents[:5]` strings that start with `data:image/`. Slack `_build_blocks` makes an `image` block for every http(s) image, with no cap, and a context text for anything else; `data:` is not handled. Telegram `_send_attachments` sends each `parsed.images` entry as `send_photo(FSInputFile(path))`, which is local files only. WhatsApp `_send_parsed_response` calls `client.send_image(image=str(p))` for images and uses `chart.public_url or str(chart.path)` for charts. All four transports go through `parse_response` first, so the URL branches in Teams and Slack are unreachable with today's parser (see F019).

## Citations
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 1128-1157
  symbol: `MSTeamsAgentWrapper._parse_response`
  excerpt: |
    if text_to_check:
        adaptive_card = self._extract_adaptive_card_json(text_to_check)
        if adaptive_card:
            return adaptive_card
    return parse_response(response)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 1259-1276
  symbol: `_parsed_to_card_spec` (images)
  excerpt: |
    for image_path in parsed.images[:3]:
        image_str = str(image_path) if hasattr(image_path, "__str__") else image_path
        if isinstance(image_str, str) and image_str.startswith(("http://", "https://")):
            image_entries.append(ImageEntry(url=image_str, alt_text="Generated Image", size="Large"))
        elif hasattr(image_path, "name"):
            sections.append(TextSection(text=f"Image: {image_path.name}", is_subtle=True))
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 1278-1312
  symbol: `_parsed_to_card_spec` (data:image documents)
  excerpt: |
    for doc in parsed.documents[:5]:
        doc_str = str(doc) if hasattr(doc, "__str__") else doc
        if isinstance(doc_str, str) and doc_str.startswith("data:image/"):
            image_entries.append(ImageEntry(url=doc_str, alt_text="Generated Chart", size="Large"))
    ...
    if image_entries:
        sections.append(ImageSection(images=image_entries, spacing="Medium", separator=True))
- path: `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py`
  lines: 561-564
  symbol: `SlackAgentWrapper` (answer path)
  excerpt: |
    parsed = parse_response(response)
    blocks = self._build_blocks(parsed)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py`
  lines: 591-603
  symbol: `SlackAgentWrapper._build_blocks`
  excerpt: |
    for img in parsed.images:
        image_url = str(img)
        if image_url.startswith("http://") or image_url.startswith("https://"):
            blocks.append({"type": "image", "image_url": image_url, "alt_text": img.name})
        else:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Image generated: `{img}`"}]})
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  lines: 2960-2960
  symbol: `TelegramAgentWrapper._send_attachments`
  excerpt: |
    async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None:
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  lines: 2987-2996
  symbol: `_send_attachments` (images)
  excerpt: |
    for image_path in parsed.images:
        try:
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(image_path),
                caption=image_path.name[:200] if len(parsed.images) > 1 else None,
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  lines: 3544-3546
  symbol: `TelegramAgentWrapper._parse_response`
  excerpt: |
    def _parse_response(self, response: Any) -> ParsedResponse:
        return parse_response(response)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py`
  lines: 286-310
  symbol: `WhatsAppAgentWrapper._send_parsed_response` (images/charts)
  excerpt: |
    for image_path in parsed.images:
        await loop.run_in_executor(_executor,
            lambda p=image_path: client.send_image(to=to, image=str(p)))
    ...
    chart_source = chart.public_url or str(chart.path)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py`
  lines: 221-221
  symbol: `WhatsAppAgentWrapper` (parse)
  excerpt: |
    parsed = parse_response(response)

## Notes
- Partly CONFIRMED, with corrections:
  - Teams caps images at 3, but Slack has no cap.
  - Slack does not handle `data:` at all.
  - Teams handles `data:image/` only when it arrives through `documents`, not `images`.
  - Telegram needs local files; `FSInputFile` wouldn't accept a URL anyway.
  - WhatsApp passes `str(p)`, so a URL string would be accepted downstream (pywa), but the parser removes URLs before they get there.
- Duplicate send paths to update as well: `telegram/wrapper.py` L3714-3760 (second attachment sender), `telegram/crew/crew_wrapper.py` L353-379, `whatsapp/bridge_wrapper.py` L260, and `slack/assistant.py` L184/L237.

