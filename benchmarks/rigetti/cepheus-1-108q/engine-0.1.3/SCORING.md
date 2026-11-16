# Scoring

The reference is `recorded_primary` in `manifest.json`, the ideal value of the circuit that was measured.

For `weighted_pauli` and `maxcut`, the scalar is the registered constant plus each coefficient times its Pauli expectation. For H2 that sum uses the constant and all 14 non-identity terms. For `components`, the comparable error is the MAE of the registered component errors.

Absolute error is the distance from the reference. Error reduction is raw absolute error minus ZNEPro absolute error. A positive reduction is better than raw. The three-round mean gives each round equal weight. A family mean gives each case in that family equal weight.

The 25-case denominator excludes `diag_asymmetric_3q`, `h2_sto3g_trial_00`, `maxcut_cycle8_angles_a`, `ising_4_end_step3`, and `param_hea_6`. Those five remain in their own table.

The partial-card gain is the no-card absolute error minus the partial-card absolute error on the same counts. A positive gain means the card is closer to the reference than the no-card replay.
