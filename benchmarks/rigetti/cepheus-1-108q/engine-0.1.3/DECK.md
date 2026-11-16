# Slide 1. Three-round no-card result

ZNEPro team evaluation on Rigetti Cepheus-1-108Q. Arm: `single_run_zero_telemetry`. Engine 0.1.3.

Hardware plan: 30 cases, three rounds, 162 tasks, 162,000 shots.

Denominator: 25 pre-registered cases. 20 of 25 are better than raw in all three rounds. 21 of 25 have a lower three-round mean absolute error.

Two cases are worse than raw in all three rounds: `diag_near_zero_2q` and `ising_6_mag_step1`.

No direct comparison with M3 or Fire Opal was run on this set.

---

# Slide 2. Families inside the 25

Each case has equal weight. Units stay inside the family.

| family | 3, 2, 1, 0 rounds better | mean lower | family mean |
| --- | --- | ---: | ---: |
| `control_diagnostics` | 4, 0, 0, 1 | 4 | 0.03328591424663367 dimensionless |
| `vqe_molecular` | 5, 0, 0, 0 | 5 | 0.025372676023568408 Hartree |
| `qaoa_maxcut` | 4, 0, 1, 0 | 4 | 0.043746796042507335 cut_weight |
| `ising_dynamics` | 3, 1, 0, 1 | 4 | 0.016534358967124886 dimensionless |
| `parametric_circuits` | 4, 0, 1, 0 | 4 | 0.023908453390230976 dimensionless |

---

# Slide 3. Why 20 of 25 and 21 of 25 differ

A round is better when raw absolute error minus ZNEPro absolute error is positive.

`ising_2_corr_step2` is better in 2 of 3 rounds and has a positive mean, so it is inside the 21 and outside the 20.

Worse than raw in all three rounds: `diag_near_zero_2q` and `ising_6_mag_step1`. `maxcut_path6_angles_a` and `param_hea_2_b` are better in 1 of 3 rounds and have a negative mean.

No case in the 25 is equal to raw, and none is incomplete for engine 0.1.3.

---

# Slide 4. Historical partial card

Separate denominator: 4 circuits, 10 case-rounds, 84 receipts.

The card is better than the no-card replay in 5 comparisons and worse in 5. None are equal.

Main rows: `diag_near_zero_2q` and `diag_product_6q`, rounds 1–3. Examined rows: `diag_asymmetric_3q` and `h2_sto3g_trial_00`, rounds 2–3.

Official temporal validity is undetermined. The deployed engine commit is unknown. This appendix does not change the 20 of 25 or 21 of 25 counts.

---

# Slide 5. H2 trial 00 and reproduction

The energy uses the registered constant and all 14 non-identity terms. The uploaded OpenQASM contains cnot. Every compiled H2 program in rounds 2 and 3 has no two-qubit opcode.

Field ages span 14.544762 to 14.580604 hours in round 2 and 2.019235 to 2.062868 hours in round 3. Each with-card receipt records `calibration_applied: true` and a `calibration_sha256`. That witness does not identify a deployed commit.

From this directory, offline:

```bash
python reproduce.py
```
