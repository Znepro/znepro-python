# Benchmarks

Recorded hardware studies. Each study keeps its own counts, receipts, and an offline rebuild. Nothing here calls the live API.

| Family | Path | What it records |
|---|---|---|
| AWS Braket | [`braket_case_studies/`](braket_case_studies/README.md) | LANL QAOA on Ankaa, QuEra Aquila (256 sites), PennyLane LiH |
| Rigetti | [`rigetti/cepheus-1-108q/engine-0.1.3/`](rigetti/cepheus-1-108q/engine-0.1.3/README.md) | Cepheus-1-108Q, engine 0.1.3, three rounds, scored without a calibration card |

The Rigetti denominator is 25 pre-registered cases: 20 of 25 are better than raw in all three rounds, and 21 of 25 have a lower three-round mean absolute error. Rebuild that study with `python3 benchmarks/rigetti/cepheus-1-108q/engine-0.1.3/reproduce.py`.
