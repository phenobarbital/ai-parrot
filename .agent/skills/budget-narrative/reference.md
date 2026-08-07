# House style — reference phrasing

Style exemplars ported from the pre-FEAT-420 reference artifact
(`sdd/artifacts/executive_summary.py:159-269` — its MATH was ported to the
`narrative_facts` transformer in FEAT-420 Module 1; this document ports its
SENTENCE SHAPES, not its numbers). Every figure below is an **obviously
fake placeholder** (`$X.XM`, `$XX.XK`, `+X.X%`, `−X.X%`) — never copy one as
real data. Substitute the actual values from the `narrative_facts` object
you were given.

## Headline (`headline`)

Map each combination of `both_improving` / `both_worsening` / `diverging`
to a sentence shape:

- **`both_improving: true`**
  > "Both revenue and EBITDA improved this period: the revenue gap is
  > {rev_direction} at {rev_state} of budget, and EBITDA variance improved
  > by $X.XM."

- **`both_worsening: true`**
  > "Both revenue and EBITDA worsened this period: the revenue gap is
  > {rev_direction} at {rev_state} of budget, and EBITDA variance worsened
  > by $XX.XK."

- **`diverging: true`**
  > "Results are mixed: revenue is {rev_state} of budget and
  > {rev_direction}, while EBITDA {ebitda_direction}."

- **Single-snapshot (`n_snapshots == 1`)** — `rev_direction` is always
  `flat` and `ebitda_direction` is always `held_steady`; say so plainly:
  > "This is a single-snapshot read ({first_label}) — revenue is
  > {rev_state} of budget; no trend is available yet."

## Division reads (`division_reads[]`)

- **`on_track`**
  > "{division} is on track, with no material shortfall."

- **`spread`**
  > "{division}'s shortfall is spread across projects, with no single
  > driver."

- **`concentrated`**
  > "{division}'s shortfall is concentrated in {named}, down $X.XM."

- **`offset_by`**
  > "{division} shows a shortfall in {named}, offset by strong performance
  > in {offsetter}."

## Key driver (`top_driver`)

Trend basis (`trend_basis`) selects the phrasing — there is only a
first-vs-latest figure available, never a day-over-day one:

- **`trend_basis: "since_first"`, trend negative**
  > "{project} in {division} is the largest driver, down $XX.XK and still
  > worsening since {first_label}."

- **`trend_basis: "since_first"`, trend positive**
  > "{project} in {division} is the largest driver, down $XX.XK but
  > improving since {first_label}."

- **`trend_basis: "new_this_period"`**
  > "{project} in {division} is the largest driver, down $XX.XK — new this
  > period, so no trend is available yet."

## Recommendation (`top_driver.urgency`)

- **`immediate`**
  > "Recommend immediate attention on {project} — the shortfall is still
  > widening."

- **`confirm_trend`**
  > "Recommend confirming the trend holds on {project} before assuming the
  > improvement is durable."

- **`check_timing`**
  > "Recommend checking timing on {project} — no clear trend yet to act on."

## Watch / bright lists (`watch[]` / `bright[]`)

- **Watch (worst performers)**
  > "Also watching: {project} in {division}, down $X.XK."

- **Bright (best performers)**
  > "On the bright side: {project} in {division}, up $X.XK."

Never combine `watch`/`bright` entries with the `top_driver` entry into one
sentence unless they name the same project — they answer different
questions (the single worst driver vs. the broader worst/best lists).
