# Agent Security Guardrails (FEAT-761)

AI-Parrot provides three complementary guardrails for agent-facing threats:

- **Prompt injection** detects instructions in user, tool, or retrieved content that try to override the agent's policy.
- **Jailbreak detection** detects attempts to remove model boundaries or activate unrestricted personas.
- **Prompt leakage detection** detects user extraction attempts and final responses that disclose the rendered system prompt.

They run at separate trust boundaries:

```text
user input ──> INPUT: injection + jailbreak + leakage extraction checks
                                  │
tool/RAG data ──> TOOL_OUTPUT: injection check (explicit opt-in)
                                  │
model response ──> OUTPUT: rendered-system-prompt leakage check ──> caller
```

The guardrails reduce risk; they do not make untrusted content safe or replace tool authorization, least privilege,
confirmation gates, or output validation.

## Quick start

Enable the three input/output protections with the named preset:

```python
from parrot.bots.basic import BasicBot

bot = BasicBot(
    name="SupportBot",
    guardrails=["security"],
)
```

`security` expands to `prompt_injection`, `jailbreak`, and `prompt_leakage`. Configure a member explicitly when its
defaults need to change; the explicit entry replaces that member from the preset:

```python
bot = BasicBot(
    name="SupportBot",
    guardrails=[
        "security",
        {
            "name": "prompt_injection",
            "scan_tool_output": True,
            "injection_probability_threshold": 0.98,
        },
        {
            "name": "jailbreak",
            "block_on_threat": True,
            "jailbreak_probability_threshold": 0.044844940304756165,
        },
        {
            "name": "prompt_leakage",
            "canary": "deployment-specific-random-canary",
            "block_on_threat": False,
        },
    ],
)
```

The preset itself cannot be configured as a dictionary. Configure its members as shown above.

## Policies

| Guardrail | Default stages | Main policy fields | Default behavior on a threat |
|---|---|---|---|
| `prompt_injection` | INPUT | `strict_mode=True`, `block_on_threat=False`, `injection_probability_threshold=0.98`, `scan_tool_output=False` | Wrap as untrusted content |
| `jailbreak` | INPUT | `strict_mode=True`, `block_on_threat=False`, `jailbreak_probability_threshold=0.044844940304756165` | Wrap as untrusted content |
| `prompt_leakage` | INPUT and OUTPUT | `strict_mode=True`, `block_on_threat=False`, `canary=None`, `ngram_size=8`, `min_prompt_shingles=12`, `shingle_hit_threshold=0.12`, `fuzzy_threshold=85` | Wrap extraction attempts; redact disclosures |

`strict_mode=False` makes the corresponding guardrail pass content unchanged. `block_on_threat=True` changes qualifying
INPUT or OUTPUT threats to a block. It does not make tool-output injection checks block tools.

## Verdicts

Guardrails return one of four pipeline actions:

- `PASS`: content is unchanged.
- `TRANSFORM`: risky input is wrapped in `<potentially_unsafe_input>`, or leaked output spans are replaced with
  `[redacted: system-prompt disclosure]`.
- `FLAG`: content continues with a structured, content-free report.
- `BLOCK`: the pipeline stops and the bot returns a canned security response. Block reasons are category labels, never
  the offending text.

Structured reports are attached under `AIMessage.metadata["guardrails"]`; tool reports use
`ToolResult.metadata["guardrails"]`. Reports contain counts, severity, scores, stage, and category data, not inspected
content.

## Tool and retrieval scanning

Tool and retrieval scanning is deliberately opt-in because it adds classifier work to every string result or retrieved
chunk:

```python
guardrails=[
    "security",
    {"name": "prompt_injection", "scan_tool_output": True},
]
```

With `scan_tool_output=True`, prompt injection also runs at `TOOL_OUTPUT` after secret scrubbing. A detected tool result
is always transformed and reported, even if `block_on_threat=True`; the tool turn continues. Vector retrieval uses the
same pipeline with `tool_name="vector_retrieval"` and scans each chunk before joining the chunks inside `<documents>`.
Per-chunk scanning prevents a poisoned late chunk from hiding beyond the classifier's 512-token window.

## Jailbreak model

The committed bake-off selected **`madhurjindal/Jailbreak-Detector-Large`** with its fp32 `onnx/model.onnx` graph and a
threshold of **0.044844940304756165**. The winner is MIT-licensed, so no "Built with Llama" attribution is required.
The measured result, gate amendment, revision, checksum, latency, quality, and caveats are recorded in
[`results-jailbreak/README.md`](../../benchmarks/injection_guardrail_latency/results-jailbreak/README.md).

The selected threshold was fitted to a small corpus, Spanish jailbreak recall was 0.44, and measured p50 latency was
44.81 ms against the amended 45 ms gate. Operators should treat these as deployment-validation requirements rather than
universal guarantees.

## Operations

Model resolution is offline on the request path. At application startup, explicitly warm the jailbreak model:

```python
from parrot.bots.guardrails.builtin.jailbreak import warmup_jailbreak_model

engine = await warmup_jailbreak_model()
```

The coroutine returns `"onnx"` when the ONNX engine resolves and `"none"` when it does not. It is the only jailbreak
path allowed to download. Construction itself never downloads and never raises because a model is absent.

| Environment variable | Default | Purpose |
|---|---|---|
| `PARROT_JAILBREAK_ONNX_DIR` | unset | Local snapshot directory. Highest-priority option for offline/air-gapped hosts. |
| `PARROT_JAILBREAK_ONNX_MODEL` | `madhurjindal/Jailbreak-Detector-Large` | Hugging Face repository used for cache resolution and warm-up. |
| `PARROT_JAILBREAK_ONNX_GRAPH` | `onnx/model.onnx` for the default model | Graph path inside the repository or local snapshot. |
| `PARROT_JAILBREAK_ORT_INTRA_OP_THREADS` | `2` | ONNX Runtime intra-op thread cap. Set before session construction. |
| `PARROT_JAILBREAK_ORT_INTER_OP_THREADS` | `1` | ONNX Runtime inter-op thread cap. Set before session construction. |

Resolution order is `PARROT_JAILBREAK_ONNX_DIR`, then a cached Hugging Face snapshot, then the local heuristic floor.
For air-gapped deployment, provision the graph plus tokenizer/config files into the directory named by
`PARROT_JAILBREAK_ONNX_DIR`. If no valid graph is available, English and Spanish compiled patterns still detect common
boundary-bypass phrases. This heuristic floor is intentionally narrower than the classifier and should be monitored as
degraded protection.

## Prompt leakage

At INPUT, prompt leakage recognizes English and Spanish requests to reveal hidden instructions and either wraps or blocks
them. At OUTPUT, it compares the final response with the exact rendered system prompt captured for that turn. Detection
uses an optional deployment canary, word-shingle overlap, and fuzzy segment alignment. A canary hit is critical; other
matches are high severity.

The rendered prompt is request-local and is only placed in guardrail context when an OUTPUT guardrail declares that it
requires it. It is not copied into the report. Use a unique, non-secret canary per deployment if deterministic canary
detection is desired; rotate it as configuration, not as an authentication credential.

Streaming currently checks prompt leakage only against the assembled final `AIMessage`. Chunks already emitted by
`ask_stream()` are not withheld, so a disclosure can reach the consumer before final-response redaction. Do not stream
sensitive workloads until a withholding adapter is deployed.

## Telemetry and privacy

Jailbreak and prompt-leakage events use the content-free `log_security_category_event` path, and pipeline reports and
telemetry for the new categories are content-free by contract. They may contain category, severity, numeric score,
action, duration, stage, agent/session identifiers, offsets, and aggregate counts. They must not contain user text, tool
output, retrieved chunks, system prompts, matched substrings, or transformed content. The older prompt-injection event
path predates this guarantee and can log matched text; apply appropriate log access and retention controls until that
path is migrated. Do not add payloads when forwarding content-free events to an observer or SIEM.

## Follow-ups

The current implementation intentionally leaves these extensions for separate work:

- evaluate the DLP `orca-sonar` path for broader sensitive-data detection;
- add streaming withholding so prompt-leakage checks happen before chunks are released;
- migrate prompt injection from its legacy resolver to the shared engine chassis;
- validate and retune jailbreak thresholds on representative production languages and traffic.
