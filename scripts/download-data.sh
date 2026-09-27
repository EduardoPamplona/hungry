#!/usr/bin/env bash
# Fetch the Food.com recipes CSV into ./data via the Kaggle CLI.
# Needs Kaggle API creds (~/.kaggle/kaggle.json) and `pip install kaggle`.
# If you don't have Kaggle set up, download RAW_recipes.csv manually from
#   https://www.kaggle.com/datasets/shuyangli94/food-com-recipes-and-user-interactions
# and drop it at ./data/RAW_recipes.csv
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/data"
mkdir -p "$DIR"

if [ -f "$DIR/RAW_recipes.csv" ]; then
  echo "Already present: $DIR/RAW_recipes.csv"
  exit 0
fi

if ! command -v kaggle >/dev/null 2>&1; then
  echo "kaggle CLI not found. Install it (pip install kaggle) and set ~/.kaggle/kaggle.json,"
  echo "or download RAW_recipes.csv manually into $DIR"
  exit 1
fi

kaggle datasets download -d shuyangli94/food-com-recipes-and-user-interactions \
  -f RAW_recipes.csv -p "$DIR" --unzip
echo "Done: $DIR/RAW_recipes.csv"
