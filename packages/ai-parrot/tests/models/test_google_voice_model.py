"""FEAT-798: GoogleVoiceModel and reel-director defaults no longer name retired 2.5 ids."""

from parrot.models.google import GoogleVoiceModel, VideoReelRequest


def test_google_voice_model_default_is_3_8_live() -> None:
    """The Live default is gemini-3.8-live and is an alias of GEMINI_3_8_LIVE."""
    assert GoogleVoiceModel.DEFAULT.value == "gemini-3.8-live"
    assert GoogleVoiceModel.DEFAULT is GoogleVoiceModel.GEMINI_3_8_LIVE


def test_google_voice_model_has_no_2_5_members() -> None:
    """No member name or value of the voice catalogue refers to Gemini 2.5."""
    assert not any(name.startswith("GEMINI_2_5") for name in GoogleVoiceModel.__members__)
    assert not any("gemini-2.5" in value for value in GoogleVoiceModel.all_models())


def test_reel_director_default_is_3_8_flash() -> None:
    """The video-reel director falls back to gemini-3.8-flash."""
    request = VideoReelRequest(prompt="Create a short nature reel.")

    assert request.effective_director_model() == "gemini-3.8-flash"
