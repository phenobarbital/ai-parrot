# Subresource Integrity (SRI) hashes for the interactive catalog

Every `scope: cdn` library entry in `libraries/*.md` declares an `sri_hash`
(and `css_sri_hash` for stylesheets). Browsers refuse to execute a CDN
`<script>`/`<link>` whose fetched bytes do not match its `integrity` attribute,
so these hashes **must be correct** for the library to load.

## Verified vs. placeholder

- `echarts` ships with a **verified** `sha384` hash and works out of the box.
- `mermaid` and `gridjs` currently carry the **placeholder** sentinel
  `sha384-REGENERATEME…`. The catalog registry logs a WARNING for any entry
  still carrying the sentinel; such a library loads in the prompt index but its
  CDN asset will be blocked by the browser until the real hash is filled in.
  (They were left as placeholders because the build environment that generated
  this catalog had no outbound network access to fetch the bytes.)

## Regenerating

With network access, run the helper script from the repo root:

```bash
python packages/ai-parrot/scripts/compute_catalog_sri.py
```

It prints the real `sha384-…` value for every `url`/`css_url` in the catalog.
Paste each value into the matching `sri_hash` / `css_sri_hash` field.

Or compute a single hash by hand:

```bash
curl -fsSL "<URL>" | openssl dgst -sha384 -binary | openssl base64 -A
# prepend "sha384-" to the output
```
