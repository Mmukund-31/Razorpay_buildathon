#!/usr/bin/env python
"""Entrypoint for the synthetic dataset generator (product spec §16-17).

Usage: python scripts/generate_synthetic_dataset.py [--rows 50000] [--seed 42]

Writes ml/data/{full,train,validation,test}.csv (gitignored — regenerate, don't commit) and
prints a summary (row count, recovery rate by failure_class/action, split sizes) so the
generation run is independently verifiable, not just claimed.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ml.data.synthetic_generator import generate, split

DATA_DIR = REPO_ROOT / "ml" / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Generating {args.rows} rows (seed={args.seed})...")
    df = generate(n_rows=args.rows, seed=args.seed)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    full_path = DATA_DIR / "full.csv"
    df.to_csv(full_path, index=False)

    train_df, val_df, test_df = split(df, seed=args.seed)
    train_df.to_csv(DATA_DIR / "train.csv", index=False)
    val_df.to_csv(DATA_DIR / "validation.csv", index=False)
    test_df.to_csv(DATA_DIR / "test.csv", index=False)

    print(f"\nWrote {len(df)} rows to {full_path}")
    print(f"  train:      {len(train_df):>7} ({len(train_df) / len(df):.1%})")
    print(f"  validation: {len(val_df):>7} ({len(val_df) / len(df):.1%})")
    print(f"  test:       {len(test_df):>7} ({len(test_df) / len(df):.1%})")

    print(f"\nOverall recovery rate: {df['actual_recovered'].mean():.3f}")
    print("\nRecovery rate by failure_class:")
    print(df.groupby("failure_class")["actual_recovered"].mean().round(3).to_string())
    print("\nRecovery rate by candidate_action:")
    print(df.groupby("candidate_action")["actual_recovered"].mean().round(3).to_string())
    print("\nRecovery rate by retry_count (should decrease):")
    print(df.groupby("retry_count")["actual_recovered"].mean().round(3).to_string())


if __name__ == "__main__":
    main()
