# AI Fluency — reference framework for the analysis stage

> This is the knowledge base the **Opus 4.8 analysis stage** is grounded in. It is
> deliberately self-contained and offline so the assessment is reproducible and does
> not depend on a live network. Update this file to refine what "good" looks like.

AI fluency is the ability to **work with AI systems effectively, efficiently, and
responsibly**. It is a *skill*, not a volume of usage — doing more with an agent does
not make you more fluent; doing it more deliberately does.

We assess fluency with the **4D framework** (Delegation, Description, Discernment,
Diligence), adapted from Anthropic's *AI Fluency: Frameworks & Foundations* (Rick
Dakan & Joseph Feller). The 4Ds are the **competencies**. The deterministic engine
(`insight.py`) measures observable **signals** from transcripts; this stage maps those
signals onto the 4Ds and turns them into a kind, specific, level-based skill map.

---

## The four competencies

### 1. Delegation — *deciding what to hand to the AI, and how much*
Knowing which work to do yourself, which to hand to the agent, and how to split a
goal into agent-sized pieces. Three sub-skills:
- **Problem awareness** — being clear on what you actually want before delegating.
- **Platform awareness** — knowing what this agent is good/bad at, and routing work accordingly.
- **Path awareness** — choosing *how* to get there: one big hand-off, a tight loop, sub-agents, background jobs, planning first.

**Observable signals:** delegation events (sub-agents, background tasks, planning),
breadth of tools reached for, end-to-end hand-offs vs. micro-stepping, whether goals
are scoped before work starts.

### 2. Description — *telling the AI what you want*
The prompting competency: communicating intent, constraints, and the shape of a good
answer. Three sub-skills:
- **Product description** — what the output should be (the goal, the file, the acceptance test).
- **Process description** — how to get there (steps, order, what to touch / not touch).
- **Performance description** — the style/role/format the agent should adopt.

**Observable signals:** do prompts name a concrete artifact (file, path, error)? carry
a constraint ("only touch X", "don't change Y")? state a *why* / acceptance criterion?
Terse one-liners that offload decisions score lower; front-loaded, specific briefs score higher.

### 3. Discernment — *evaluating what the AI gives back*
Critically judging outputs, process, and behavior rather than accepting them. Three sub-skills:
- **Product discernment** — checking the result is actually correct (tests, build, run, read-before-trust).
- **Process discernment** — noticing when the agent took a bad path and redirecting.
- **Performance discernment** — judging whether the interaction style is serving you.

**Observable signals:** verification after edit-bursts (tests/build/run), grounding
edits in a prior read, correcting precisely (naming the symptom + the rule) instead of
vague rejection, clean teardown of things spun up.

### 4. Diligence — *being responsible with the AI*
Using AI thoughtfully and accountably. Three sub-skills:
- **Creation diligence** — owning what you ship; not blind-shipping generated work.
- **Transparency diligence** — being honest about AI's involvement where it matters.
- **Deployment diligence** — verifying before things go live; cleaning up; not leaving messes.

**Observable signals:** verification discipline, teardown of live systems, grounded
(non-blind) edits, reviewing before moving on. (This competency overlaps Discernment in
a coding transcript; weight the *responsibility* angle — did they check before it mattered?)

---

## How engine signals map onto the 4Ds

`insight.py` reports five dimensions + a Delegation axis. Map them like this:

| Engine signal (dimension) | Primary 4D competency | Also informs |
|---|---|---|
| **Briefing / Direction** (constraint, artifact, intent rates) | Description | Delegation (problem awareness) |
| **Delegation axis** (hand-offs / hr: sub-agents, background, planning) | Delegation | — |
| **Toolcraft** (tool breadth, evenness, orchestration) | Delegation (platform & path) | — |
| **Verification** (tests/build/run after edits; teardown) | Discernment | Diligence |
| **Context-setting** (read-before-edit grounding) | Discernment | Diligence |
| **Iteration** (correction rate + specificity) | Description (re-description) | Discernment |

Two cautions the analyst must respect:
- **Agency.** Verification and Context grounding are habits Claude often performs on
  its own; do not credit/penalize the *user's* fluency for them as strongly as for
  Description, Delegation, and Iteration, which the user clearly drives.
- **Confidence.** Each dimension carries a confidence (0–1) from how many opportunities
  it had. Low-confidence signals must be hedged ("limited evidence, but…"), never stated
  as fact.

---

## Level rubric (apply per 4D competency)

| Level | Name | What it looks like |
|---|---|---|
| 1 | Emerging | Mostly reactive; hands off with little structure; rarely checks or scopes. |
| 2 | Developing | Some structure appears, inconsistently; occasional constraints/checks. |
| 3 | Proficient | Habit is present in the *majority* of relevant moments; reliable baseline. |
| 4 | Advanced | Consistent and deliberate; anticipates failure modes; few gaps. |
| 5 | Expert | Reflexive and teachable; sets it up front, layers it, makes it reusable. |

Anchor levels to **rates**, not volume. "Verifies most edit-bursts (70%)" → ~L3–4.
"Names a file/constraint in a minority of action prompts" → ~L2 Description.

---

## What good looks like (use as the target the user is growing toward)

- **Delegation:** "Add a `/health` endpoint to `server.py` only, then run the tests" —
  one scoped hand-off, right-sized, with the path implied. Uses sub-agents/planning for
  big or parallel work.
- **Description:** Goal + one anchor (path/constraint/acceptance test) in most action
  prompts. "Refactor `auth.py` to use the new `Session` type; don't touch the public API; tests must still pass."
- **Discernment:** Edit-bursts end with a test/build/run; edits follow a read of the
  file; corrections name the symptom and the exact fix.
- **Diligence:** Nothing ships unverified; live systems are torn down; the user owns the result.

---

## Output contract for the analysis stage

Produce a JSON object (this is what `insight.py --analysis` renders):

```json
{
  "overall_read": "2–4 sentences, plain English, kind and specific: who this builder is and the single highest-leverage growth move.",
  "skill_map": [
    {
      "competency": "Delegation | Description | Discernment | Diligence",
      "level": 1-5,
      "level_label": "Emerging | Developing | Proficient | Advanced | Expert",
      "summary": "1–2 sentences grounded in THIS person's evidence (cite a real pattern).",
      "evidence": ["short quote or concrete observation from the transcripts", "another"],
      "next_move": "one concrete, doable action for next session (a habit, with a tiny template if useful)."
    }
    // exactly the four competencies, in this order
  ],
  "top_growth": [
    {"title": "...", "why": "...", "how": "...", "example_before": "a real terse prompt of theirs", "example_after": "the same prompt, improved"}
  ],
  "strengths": ["specific things they already do well, grounded in evidence"]
}
```

Rules for the analyst:
1. **Ground every claim in the evidence bundle.** Quote real prompts. No generic advice.
2. **Be kind and useful — write like a good teacher.** Name the skill, why it matters,
   and exactly how to improve, with a before/after from their own prompts.
3. **Respect agency and confidence** (above). Hedge thin signals.
4. **Be honest.** If evidence is sparse for a competency, say so and lower confidence,
   don't invent. The numbers come from the deterministic engine; your job is judgment and direction.
