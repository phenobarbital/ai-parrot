# Roost performatives, protocols and obligations

Source of truth: `parrot/roost/performatives.py`.

## Acts

| Act | Reply owed | Allowed replies | Wakes receiver |
|---|---|---|---|
| `inform` | no | — | if addressed |
| `request` | yes | `agree`, `refuse`, `inform`, `failure` | if LLM-backed |
| `query` | yes | `inform`, `failure` | if LLM-backed |
| `agree` | no | — | never |
| `refuse` | no | — | never |
| `failure` | no | — | requester to re-plan |
| `cfp` | yes | `propose`, `refuse` | if capability matches |
| `propose` | yes | `accept`, `reject` | never |
| `accept` | yes | `agree`, `refuse` | if LLM-backed |
| `reject` | no | — | never |
| `subscribe` | no | — | never |
| `not_understood` | no | — | never |

## Protocols

`inform`, `request`, `query`, `contract_net` (cfp / propose / accept / reject) and `subscribe`. Each conversation
follows one protocol; the harness enforces the state machine and rejects replies outside the allowed set.

## Failure codes

`TIMEOUT`, `HOP_LIMIT`, `TOKEN_BUDGET`, `POLICY`, `CAPACITY`, `NO_BIDS`, `CANCELLED`, `STALE_CONTRACT`, `INTERNAL`.

## Origin-tool map

LLM-visible tools map to acts (`ORIGIN_TOOL_MAP`): `report` -> `inform`, `ask_agent` -> `query`,
`call_for_proposals` -> `cfp`, `watch` -> `subscribe`. Mounted capability tools map to `request` in the toolkit,
not by name.
