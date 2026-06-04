"""AudioFieldRenderer — HTML5 field renderer for FieldType.AUDIO.

Renders a FieldType.AUDIO field as a record button + hidden input + inline
JavaScript using the MediaRecorder API. The recording button controls
start/stop, the waveform indicator provides visual feedback, and the hidden
<input> stores the transcribed text (populated via the audio WebSocket or
client-side transcription).

This renderer implements the FieldRenderer protocol and is registered in
HTML5Renderer._build_registry() for FieldType.AUDIO.

Added by FEAT-224 (FormDesigner Audio Renderer).
"""

from __future__ import annotations

import html
from typing import Any

from ...core.schema import FormField
from ...core.types import LocalizedString


def _resolve_label(value: LocalizedString | None, locale: str = "en") -> str:
    """Resolve a LocalizedString to a plain string.

    Args:
        value: String or locale dict.
        locale: BCP 47 locale tag.

    Returns:
        Resolved string, or empty string if value is None.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), "")


class AudioFieldRenderer:
    """HTML5 field renderer for FieldType.AUDIO fields.

    Produces a self-contained HTML snippet with:
    - A label element for the field.
    - A record button (start/stop toggle).
    - A visual waveform indicator.
    - A hidden <input> that stores the transcribed text.
    - Inline JavaScript using the MediaRecorder API.

    Implements the FieldRenderer protocol so it can be registered in
    HTML5Renderer._registry.

    Example::

        renderer = AudioFieldRenderer()
        html_snippet = await renderer.render(field, locale="en")
    """

    async def render(
        self,
        field: FormField,
        *,
        locale: str = "en",
        prefilled: Any = None,
        error: str | None = None,
    ) -> str:
        """Render the audio field as an HTML5 snippet.

        Args:
            field: The FormField to render (must be FieldType.AUDIO).
            locale: BCP 47 locale for label resolution.
            prefilled: Pre-filled transcription text (shown in the hidden
                input as default value).
            error: Optional validation error message.

        Returns:
            HTML string with the recording button, waveform, hidden input,
            and inline JavaScript.
        """
        field_id = html.escape(field.field_id)
        label_text = html.escape(_resolve_label(field.label, locale))
        required_attr = " required" if field.required else ""
        error_html = (
            f'<div class="field-error" id="{field_id}-error">'
            f'{html.escape(error)}</div>'
            if error
            else ""
        )
        prefilled_value = html.escape(str(prefilled)) if prefilled else ""
        description_html = ""
        if field.description:
            desc_text = html.escape(_resolve_label(field.description, locale))
            description_html = (
                f'<p class="field-description" id="{field_id}-desc">{desc_text}</p>'
            )

        return f"""\
<div class="form-field form-field--audio" data-field-type="audio" data-field-id="{field_id}">
  <label class="field-label" for="{field_id}-transcript">{label_text}</label>
  {description_html}
  <div class="audio-recorder" id="{field_id}-recorder">
    <button
      type="button"
      class="audio-record-btn"
      id="{field_id}-btn"
      aria-label="Start recording"
      data-recording="false"
    >
      <span class="audio-record-icon">&#9679;</span>
      <span class="audio-record-label">Record</span>
    </button>
    <div class="audio-waveform" id="{field_id}-waveform" aria-hidden="true">
      <span></span><span></span><span></span><span></span><span></span>
    </div>
  </div>
  <input
    type="hidden"
    id="{field_id}-transcript"
    name="{field_id}"
    value="{prefilled_value}"
    data-audio-field="{field_id}"{required_attr}
  />
  {error_html}
  <script>
  (function() {{
    var btn = document.getElementById('{field_id}-btn');
    var input = document.getElementById('{field_id}-transcript');
    var waveform = document.getElementById('{field_id}-waveform');
    var mediaRecorder = null;
    var audioChunks = [];

    if (!btn || !input) return;

    btn.addEventListener('click', function() {{
      if (btn.dataset.recording === 'false') {{
        navigator.mediaDevices.getUserMedia({{ audio: true }}).then(function(stream) {{
          mediaRecorder = new MediaRecorder(stream, {{ mimeType: 'audio/webm' }});
          audioChunks = [];
          mediaRecorder.addEventListener('dataavailable', function(e) {{
            audioChunks.push(e.data);
          }});
          mediaRecorder.addEventListener('stop', function() {{
            var blob = new Blob(audioChunks, {{ type: 'audio/webm' }});
            var event = new CustomEvent('audio-recorded', {{
              detail: {{ fieldId: '{field_id}', blob: blob }},
              bubbles: true
            }});
            btn.dispatchEvent(event);
            stream.getTracks().forEach(function(t) {{ t.stop(); }});
          }});
          mediaRecorder.start();
          btn.dataset.recording = 'true';
          btn.setAttribute('aria-label', 'Stop recording');
          btn.querySelector('.audio-record-label').textContent = 'Stop';
          if (waveform) waveform.classList.add('audio-waveform--active');
        }}).catch(function(err) {{
          console.error('Audio recording error:', err);
        }});
      }} else {{
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {{
          mediaRecorder.stop();
        }}
        btn.dataset.recording = 'false';
        btn.setAttribute('aria-label', 'Start recording');
        btn.querySelector('.audio-record-label').textContent = 'Record';
        if (waveform) waveform.classList.remove('audio-waveform--active');
      }}
    }});

    document.addEventListener('audio-transcription', function(e) {{
      if (e.detail && e.detail.fieldId === '{field_id}') {{
        input.value = e.detail.text || '';
      }}
    }});
  }})();
  </script>
</div>"""
