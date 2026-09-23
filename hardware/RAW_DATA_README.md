# Raw physical evidence

Raw files are immutable and are grouped by session: `HWS-002-FIFO`, `HWS-003-BACS`, and `HWS-005-BACS+`. Original filenames and bytes are retained. `support/` holds supplied protocol, manifests, and logs.

Run `python scripts/validate_hardware.py` to generate `SHA256SUMS.txt`, `raw_file_inventory.csv`, and validation tables. No script writes inside `hardware/raw/`.
