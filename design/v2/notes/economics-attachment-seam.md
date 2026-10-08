# Economics attachment seam (F1.1 note)

Status: architectural note only. No economics is implemented in F1. The taxonomy and
storage belong to F2.

## What F1.1 guarantees

Future economic records can attach to the stable identities that F1.1 already persists:

| Economic scope | Identity to attach to |
|---|---|
| Organization / site | the plant row (`plant_id`); organization is implicit until multi-tenant |
| Operational scope / line | `line_id` today; the F3 operational scope later |
| Asset | `equipment_id` (`Incident.equipment_ids`, `WorkAssignment.equipment_ids`) |
| Case | `Incident.id` |
| Work assignment / work order | `WorkAssignment.id`, its `external_refs` (work order and package numbers) and `receipt_id` |
| Intervention | `Intervention.id` plus `intervention_hash` (the exact approved content) |
| Parts and labour | the intervention's work-package parameters (`parts`, `window_min`), and later the `WorkReport` |
| Outcome | `Outcome.id` (only for verified results) |

No table was added for economics, and none is required for these attachments.

## Provenance every future economic value must carry

`RECORDED` (actual, for example an invoice or timesheet), `CONFIGURED` (a set rate or price),
`CALCULATED` (derived from recorded or configured inputs by a versioned formula),
`ESTIMATED` (a model or human estimate) and `COUNTERFACTUAL` (avoided cost). Where no
economic model exists, OPERON must report the value as unavailable rather than invent one.

## Existing values that are not authoritative

The engine still projects illustrative figures inherited from the demo: `proposal.business`
(`recovered_value`, `estimated_cost`, `downtime_hours_avoided`), the dispatch result
`recovered_value`, and `oee_before`/`oee_after`. These come from configuration constants and
binding inputs. They are not measured, they are emitted at dispatch time, and they must not be
treated as realised value, recovery or truth. They stay untouched in F1 (frontend and legacy
pages read them) and are to be replaced with provenance-labelled values, or "unavailable", in
F2.
