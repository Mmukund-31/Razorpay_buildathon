# ml/data/

Generated synthetic datasets land here (Phase 3). Not committed — see root `.gitignore`
(`ml/data/*.csv`, `*.parquet`). `scripts/generate_synthetic_dataset.py` writes here with a
deterministic seed; the seed and dataset version are recorded in `model_versions.training_dataset_ref`
so every trained model can be traced back to exactly the data it was trained on.
