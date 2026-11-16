# Cepheus three-round summary

This is the ZNEPro team's evaluation on Rigetti Cepheus-1-108Q. The hardware plan is 30 cases, three rounds, 162 tasks, and 162,000 shots. The scored arm is `single_run_zero_telemetry`. No direct comparison with M3 or Fire Opal was run on this set.

The main denominator is 25 pre-registered cases. 20 of 25 cases have lower absolute error than raw in all three rounds. 21 of 25 cases have a lower three-round mean absolute error. Two cases are worse than raw in all three rounds: `diag_near_zero_2q` and `ising_6_mag_step1`. `ising_2_corr_step2` is better in 2 of 3 rounds and is the case that makes the mean count 21. `maxcut_path6_angles_a` and `param_hea_2_b` are better in 1 of 3 rounds and still have a higher three-round mean.

No-card receipt coverage for all 30 cases is 148 receipts in each round and 444 in total.

## Families inside the 25

| family | better in 3, 2, 1, 0 rounds | mean lower | family mean | unit |
| --- | --- | ---: | ---: | --- |
| `control_diagnostics` | 4, 0, 0, 1 | 4 | 0.03328591424663367 | dimensionless |
| `vqe_molecular` | 5, 0, 0, 0 | 5 | 0.025372676023568408 | Hartree |
| `qaoa_maxcut` | 4, 0, 1, 0 | 4 | 0.043746796042507335 | cut_weight |
| `ising_dynamics` | 3, 1, 0, 1 | 4 | 0.016534358967124886 | dimensionless |
| `parametric_circuits` | 4, 0, 1, 0 | 4 | 0.023908453390230976 | dimensionless |

## Historical partial card

The appendix covers 4 circuits, 10 case-rounds, and 84 receipts. The card is better than the no-card replay in 5 comparisons and worse in 5. The six main rows are `diag_near_zero_2q` and `diag_product_6q`, rounds 1–3. The four examined rows are `diag_asymmetric_3q` and `h2_sto3g_trial_00`, rounds 2–3. Official temporal validity is undetermined. The deployed engine commit is unknown.

H2 trial 00 uses the registered constant and all 14 non-identity terms. Its uploaded OpenQASM contains cnot, and every compiled H2 program in rounds 2 and 3 has no two-qubit opcode. Field ages at task start span 14.544762 to 14.580604 hours in round 2 and 2.019235 to 2.062868 hours in round 3.

Rebuild the full 25-case table, the examined-five table, and this appendix with `python reproduce.py`.
