"""
NER inference module.
Loads fine-tuned DistilBERT and extracts legal entities from query text.

Loaded once at FastAPI startup via load_ner_model().
Fails gracefully — app runs without NER if model not found.

Example:
  Input:  "What did Justice Chandrachud say about Section 302 IPC?"
  Output: {"JUDGE": ["Justice Chandrachud"],
           "PROVISION": ["Section 302"],
           "STATUTE": ["IPC"]}

The augmented query becomes:
  "What did Justice Chandrachud say about Section 302 IPC?
   JUDGE: Justice Chandrachud PROVISION: Section 302 STATUTE: IPC"
"""

import os
import logging
from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification

logger = logging.getLogger(__name__)

NER_MODEL_PATH = os.getenv("NER_MODEL_PATH", "models/ner_model")

TARGET_ENTITIES = {
    "JUDGE", "COURT", "STATUTE", "PROVISION",
    "CASE_NUMBER", "DATE", "PRECEDENT", "LAWYER",
    "PETITIONER", "RESPONDENT", "GPE", "ORG"
}

_ner_pipeline = None


def load_ner_model():
    """
    Load NER model once at startup.
    Fails gracefully — app runs without NER if model not found.
    Call this from api/main.py after download_models().
    """
    global _ner_pipeline

    if not os.path.exists(NER_MODEL_PATH):
        logger.warning(
            f"NER model not found at {NER_MODEL_PATH}. "
            "Entity extraction disabled. App will run without NER."
        )
        return

    try:
        logger.info(f"Loading NER model from {NER_MODEL_PATH}...")
        tokenizer = AutoTokenizer.from_pretrained(NER_MODEL_PATH)
        model = AutoModelForTokenClassification.from_pretrained(NER_MODEL_PATH)
        _ner_pipeline = pipeline(
            "ner",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple"
        )
        logger.info("NER model ready.")
    except Exception as e:
        logger.error(f"NER model load failed: {e}. Entity extraction disabled.")
        _ner_pipeline = None


def extract_entities(text: str) -> dict:
    """
    Run NER on input text.
    Returns dict of {entity_type: [entity_text, ...]}
    Returns empty dict if NER not loaded or inference fails.
    """
    if _ner_pipeline is None:
        return {}

    if not text.strip():
        return {}

    try:
        results = _ner_pipeline(text[:512])
    except Exception as e:
        logger.warning(f"NER inference failed: {e}")
        return {}

    entities = {}
    for result in results:
        entity_type = result["entity_group"]
        entity_text = result["word"].strip()

        if entity_type not in TARGET_ENTITIES:
            continue
        if len(entity_text) < 2:
            continue

        if entity_type not in entities:
            entities[entity_type] = []
        if entity_text not in entities[entity_type]:
            entities[entity_type].append(entity_text)

    return entities


def augment_query(query: str, entities: dict) -> str:
    """
    Append extracted entities to query string for better FAISS retrieval.
    Returns original query unchanged if no entities found.
    """
    if not entities:
        return query

    entity_string = " ".join(
        f"{etype}: {etext}"
        for etype, texts in entities.items()
        for etext in texts
    )

    return f"{query} {entity_string}"