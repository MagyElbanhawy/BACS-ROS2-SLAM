# Reproduction guide

1. Create an isolated Python environment and install `requirements.txt`.
2. Run `python scripts/validate_hardware.py`. Review `hardware/validation/` and stop if any status is invalid.
3. Run `python scripts/reproduce_physical.py` and `python scripts/reproduce_statistics.py`.
4. Run `python scripts/reproduce_simulation.py`; these outputs are explicitly simulated.
5. Run `python scripts/generate_figures.py` and `python -m pytest -q`.

The hardware validator reads raw evidence only. Generated output is deterministic for the committed code and input files. Results marked `NOT_COMPUTABLE` are evidence limitations, not missing-value imputations.
