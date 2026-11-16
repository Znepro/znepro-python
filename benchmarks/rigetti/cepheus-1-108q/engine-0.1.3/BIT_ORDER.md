# Bit order

Stored count keys are `q0_left`. Character 0 is logical measured qubit 0, and character `n-1` is logical measured qubit `n-1`. These are the Braket `measurement_counts` keys. They were not reversed before scoring.

A Pauli string `P_0 P_1 ... P_{n-1}` maps `P_k` to logical qubit `k`. `ZII` is Z0, `IIZ` is Z2, `ZZI` is Z0Z1, and `IZZ` is Z1Z2.

The expectation of a Pauli is the mean of `+1` or `-1` over the stored shots. Each qubit in the Pauli support contributes a minus sign when its character is `1`.

A receipt is bound to a circuit by the SHA-256 of the manifest group's OpenQASM, which is stored on the counts file as `qasm_sha256`.
