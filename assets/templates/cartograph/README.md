# Cartograph sprite templates

Place `*.png` crops in class folders: `beast/`, `rss/`, `wood/`, `bread/`, `stone/`, `iron/`.

- Prefer crops from our BlueStacks captures (same zoom as grid sweeps).
- Web references: only if license allows redistribution; note source in the filename or a sidecar `.txt`.
- Matching uses multi-scale OpenCV `TM_CCOEFF_NORMED` (`ks.cartograph.sprites`).
- YOLO graduation: see `export_yolo_labels_stub()` — train offline, then swap the matcher implementation.
