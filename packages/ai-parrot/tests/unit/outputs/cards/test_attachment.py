# packages/ai-parrot/tests/unit/outputs/cards/test_attachment.py
"""Unit tests for attachment helper."""


class TestBuildAttachment:
    def test_wraps_card(self):
        from parrot.outputs.cards.attachment import build_attachment
        card = {"type": "AdaptiveCard", "version": "1.5", "body": []}
        att = build_attachment(card)
        assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert att["content"] is card

    def test_from_spec(self):
        from parrot.outputs.cards.attachment import build_attachment_from_spec
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(title="Test")
        att = build_attachment_from_spec(spec)
        assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert att["content"]["type"] == "AdaptiveCard"
