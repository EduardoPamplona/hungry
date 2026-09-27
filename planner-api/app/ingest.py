"""Load a slice of the Food.com recipes CSV, embed, and insert into pgvector.

Run inside the api container (has DB + TEI network):
    docker compose run --rm api python -m app.ingest /data/RAW_recipes.csv 2000

Args: [csv_path] [limit]. Dataset: Food.com "RAW_recipes.csv" (Kaggle).
Columns used: id, name, minutes, tags, ingredients, steps, n_steps.
"""

import sys

import pandas as pd

from .db import get_conn
from .embeddings import embed

BATCH = 32


def _embed_text(row) -> str:
    # What the recipe is "about" — name + tags + ingredients drives retrieval.
    return f"{row['name']} | tags: {row['tags']} | ingredients: {row['ingredients']}"


def main() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/data/RAW_recipes.csv"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 2000

    print(f"Reading {csv_path} (first {limit} rows)...", flush=True)
    df = pd.read_csv(csv_path, nrows=limit)
    df = df.dropna(subset=["id", "name"])

    inserted = 0
    with get_conn() as conn:
        for start in range(0, len(df), BATCH):
            chunk = df.iloc[start : start + BATCH]
            vectors = embed([_embed_text(r) for _, r in chunk.iterrows()])
            with conn.cursor() as cur:
                for (_, r), vec in zip(chunk.iterrows(), vectors):
                    cur.execute(
                        """
                        INSERT INTO recipes (id, name, minutes, tags, ingredients, steps, n_steps, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding
                        """,
                        (
                            int(r["id"]),
                            str(r["name"]),
                            int(r["minutes"]) if pd.notna(r.get("minutes")) else None,
                            str(r.get("tags", "")),
                            str(r.get("ingredients", "")),
                            str(r.get("steps", "")),
                            int(r["n_steps"]) if pd.notna(r.get("n_steps")) else None,
                            vec,
                        ),
                    )
            inserted += len(chunk)
            print(f"  {inserted}/{len(df)}", flush=True)

        # Build the ANN index now that rows are present, so ivfflat trains its
        # centroids on real data (see sql/init.sql for why not at DB init).
        print("Building ivfflat index + ANALYZE...", flush=True)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS recipes_embedding_idx "
            "ON recipes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
        conn.execute("ANALYZE recipes")

    print(f"Done. {inserted} recipes ingested.", flush=True)


if __name__ == "__main__":
    main()
