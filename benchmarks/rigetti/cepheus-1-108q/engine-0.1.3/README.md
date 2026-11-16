# Rigetti Cepheus-1-108Q, engine 0.1.3

This directory is the ZNEPro team's evaluation on Rigetti hardware. The device is Cepheus-1-108Q and the scored arm is `single_run_zero_telemetry` on engine 0.1.3. No direct comparison with M3 or Fire Opal was run on this set.

The hardware plan is 30 cases, three rounds, 162 tasks, and 162,000 shots. Each task is one measurement group of 1,000 shots.

The main result uses 25 pre-registered cases. Five previously examined cases stay outside that denominator. 20 of 25 cases have lower absolute error than raw in all three rounds. 21 of 25 cases have a lower three-round mean absolute error. Two cases are worse than raw in all three rounds: `diag_near_zero_2q` and `ising_6_mag_step1`.

No-card receipts cover all 30 cases: 148 receipts in each round and 444 receipts in total. A receipt is accepted only when its own `status` is COMPLETED and its own `engine_version` is 0.1.3, and when its observable, arm, and shot count match the stored counts.

The exploratory historical partial-card appendix is separate. It covers 4 circuits, 10 case-rounds, and 84 receipts. The card has lower absolute error than the no-card replay in 5 comparisons and higher absolute error in 5. Official temporal validity is undetermined, and the deployed engine commit is unknown.

A full-card audit of the same 162 tasks found 0 eligible cards, 153 ineligible tasks, and 9 unresolved tasks. The published scores therefore stay on the no-card arm.

## Reproduce

From this directory:

```bash
python reproduce.py
```

The command uses no network and no credential. It reads `manifest.json`, `counts/`, and `receipts/`. Raw values come from the counts. ZNEPro values come from the COMPLETED 0.1.3 receipts. H2 energy is the registered constant plus all 14 non-identity terms. The files under `reproduced/` are outputs of this command, not its inputs.

## Files

- `SUMMARY.md` is the one-page result.
- `DECK.md` is the five-slide briefing.
- `rigetti-cepheus-v1.pdf` is that briefing for Rigetti.
- `manifest.json` defines the circuits, terms, and references.
- `BIT_ORDER.md` states the `q0_left` convention.
- `SCORING.md` states how absolute error is reduced.
- `CARD_AUDIT.md` records why the scored arm sends no card.
- `counts/` holds one original histogram per task.
- `receipts/zero_telemetry/` holds the public no-card receipts.
- `receipts/partial_no_card/` and `receipts/partial_card/` hold the appendix.
- `compiled/` holds the compiled programs for those 18 partial-card tasks.
- `card_context/` holds the field ages used in the appendix.

A task id has the form `r{round}/{case_id}/{group_id}`. A receipt id adds `/{observable}`. These ids are local to this study. A replay on the same shots is the same execution, not another round.
