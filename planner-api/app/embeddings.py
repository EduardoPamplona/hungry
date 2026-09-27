import httpx

from .config import get_settings


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via the TEI server (bge-small-en-v1.5, 384-dim)."""
    url = get_settings().tei_url.rstrip("/") + "/embed"
    resp = httpx.post(url, json={"inputs": texts}, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
