# Physical dataset

`hardware/raw/` is the immutable evidence root. The three session directories retain original filenames and bytes. `support/` contains supplied manifests, protocol records, and acquisition logs. `hardware/SHA256SUMS.txt` and `hardware/raw_file_inventory.csv` are generated from the evidence bytes by `scripts/validate_hardware.py`.

Large `.db3` and `.mcap` files are configured for Git LFS. Do not edit, normalize, recompress, or regenerate raw evidence files.
