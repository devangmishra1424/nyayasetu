"""
NER inference module.
Loads fine-tuned DistilBERT and extracts legal entities from query text.

Loaded once at FastAPI startup — never per request.
Called before FAISS retrieval to augment the query with extracted entities.

Example:
  Input:  "What did Justice Chandrachud say about Section 302 IPC?"
  Output: {"JUDGE": ["Justice Chandrachud"], 
           "PROVISION": ["Section 302"], 
           "STATUTE": ["IPC"]}

The augmented query becomes:
  "What did Justice Chandrachud say about Section 302 IPC? 
   JUDGE: Justice Chandrachud PROVISION: Section 302 STATUTE: IPC"

WHY augment the query?
MiniLM embeds the full query string. Adding extracted entities 
explicitly shifts the embedding closer to chunks that mention 
those specific legal terms — improving retrieval precision.
"""

import os
from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification

NER_MODEL_PATH = os.getenv("NER_MODEL_PATH", "models/ner_model")

TARGET_ENTITIES = {
    "JUDGE", "COURT", "STATUTE", "PROVISION",
    "CASE_NUMBER", "DATE", "PRECEDENT", "LAWYER",
    "PETITIONER", "RESPONDENT", "GPE", "ORG"
}

# Load once at import time
if not os.path.exists(NER_MODEL_PATH):
    raise FileNotFoundError(
        f"NER model not found at {NER_MODEL_PATH}. "
        "Train it on Kaggle first. "
        "System will run without NER until model is available."
    )

print(f"Loading NER model from {NER_MODEL_PATH}...")
_tokenizer = AutoTokenizer.from_pretrained(NER_MODEL_PATH)
_model = AutoModelForTokenClassification.from_pretrained(NER_MODEL_PATH)

_ner_pipeline = pipeline(
    "ner",
    model=_model,
    tokenizer=_tokenizer,
    aggregation_strategy="simple"
)
print("NER model ready.")


def extract_entities(text: str) -> dict:
    """
    Run NER on input text.
    Returns dict of {entity_type: [entity_text, ...]}
    Filters to only legally relevant entity types.
    """
    if not text.strip():
        return {}

    try:
        results = _ner_pipeline(text)
    except Exception as e:
        print(f"NER inference failed: {e}")
        return {}

    entities = {}
    for result in results:
        entity_type = result["entity_group"]
        entity_text = result["word"].strip()

        if entity_type not in TARGET_ENTITIES:
            continue
        if len(entity_text) < 2:  # Skip single characters
            continue

        if entity_type not in entities:
            entities[entity_type] = []
        if entity_text not in entities[entity_type]:  # No duplicates
            entities[entity_type].append(entity_text)

    return entities


def augment_query(query: str, entities: dict) -> str:
    """
    Append extracted entities to query string.
    Returns augmented query for embedding.
    """
    if not entities:
        return query

    entity_string = " ".join(
        f"{etype}: {etext}"
        for etype, texts in entities.items()
        for etext in texts
    )

    return f"{query} {entity_string}"


if __name__ == "__main__":
    # Quick test
    test_queries = [
        "What did Justice Chandrachud say about Article 21?",
        "Find cases related to Section 302 IPC and bail",
        "Supreme Court judgment on fundamental rights in 1978"
    ]

    for q in test_queries:
        entities = extract_entities(q)
        augmented = augment_query(q, entities)
        print(f"\nQuery: {q}")
        print(f"Entities: {entities}")
        print(f"Augmented: {augmented}")