---
kind: inline
jira_key: null
fetched_at: 2026-06-08T23:30:45Z
summary_oneline: Voice support for AgentTalk — receive audio over WS, STT → LLM → sub-second TTS (Supertonic), return audio + content
---

# agentalk-voice-support

Idea is implementing a feature for receiving (maybe via websockets) an audio
from the frontend — that's the user's question — transform it to text
(speech-to-text), send the question to the LLM, then take the text answer
(under `response.response`), then pass it through a sub-second ML model for
text-to-speech like **Supertonic** (https://github.com/supertone-inc/supertonic)
and return the **audio + content** to the frontend.

Key design concern raised by the requester:

> I don't think it is easy to use stream-transfer to send the "AIMessage"
> object to the frontend, because `response.data` or `response.output`
> sometimes are objects, markdown data or JSON structures that cannot be
> transferred in a stream fashion — but more importantly, cannot be used for
> text-to-speech transform.

So the TTS path must operate on a clean, speakable text field (`response.response`),
decoupled from the structured/markdown/JSON payload that goes to the frontend
for display.
