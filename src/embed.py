"""
Embedding module. Loads MiniLM once at startup, never per request.
"""
from sentence_transformers import SentenceTransformer
import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

print(f"Loading embedding model...")
_model = SentenceTransformer(MODEL_NAME)
print("Embedding model ready.")

def embed_text(text: str) -> np.ndarray:
    """Embed a single string. Returns shape (384,)"""
    return _model.encode(text, normalize_embeddings=True)