from .db import get_conn
from .embeddings import embed_one
from .schema import Candidate


def retrieve(goal: str, k: int = 12) -> list[Candidate]:
    """Vector search: nearest recipes to the goal text by cosine distance."""
    qvec = embed_one(goal)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, tags, minutes
            FROM recipes
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (qvec, k),
        ).fetchall()
    return [Candidate(id=r[0], name=r[1], tags=r[2], minutes=r[3]) for r in rows]
