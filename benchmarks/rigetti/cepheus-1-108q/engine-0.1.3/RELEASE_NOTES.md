# rigetti-cepheus-v1

This is the ZNEPro team's evaluation on Rigetti Cepheus-1-108Q, engine 0.1.3.

The hardware plan is 30 cases, three rounds, 162 tasks, and 162,000 shots. The scored arm is `single_run_zero_telemetry`. Of the 25 pre-registered cases, 20 of 25 have lower absolute error than raw in all three rounds, and 21 of 25 have a lower three-round mean absolute error. Two cases are worse than raw in all three rounds: `diag_near_zero_2q` and `ising_6_mag_step1`.

No-card receipts cover all 30 cases: 148 in each round and 444 in total. The exploratory historical partial card covers 4 circuits, 10 case-rounds, and 84 receipts. The card is better than the no-card replay in 5 comparisons and worse in 5. No direct comparison with M3 or Fire Opal was run on this set.

The PDF attached to this release is `rigetti-cepheus-v1.pdf`.

From the study directory:

```bash
python reproduce.py
```
