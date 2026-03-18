---
title: NyayaSetu
emoji: ⚖️
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
---

# NyayaSetu — Indian Legal RAG Agent

Ask questions about Indian Supreme Court judgments (1950–2024).

**Live API:** POST `/query` with `{"query": "your legal question"}`

> Not legal advice. Always consult a qualified advocate.


# NyayaSetu — Indian Legal RAG Agent

> Retrieval-Augmented Generation over 26,688 Supreme Court of India judgments (1950–2024).  
> Ask a legal question. Get a cited answer grounded in real case law.
> 1,025,764 chunks indexed (SC judgments, HC judgments, bare acts, constitution, legal references)
> V2 agent with 3-pass reasoning loop and conversation memory

[![Live Demo](https://img.shields.io/badge/🤗%20HuggingFace-Live%20Demo-blue)](https://huggingface.co/spaces/CaffeinatedCoding/nyayasetu)
[![GitHub Actions](https://github.com/devangmishra1424/nyayasetu/actions/workflows/ci.yml/badge.svg)](https://github.com/devangmishra1424/nyayasetu/actions)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Version](https://img.shields.io/badge/version-1.0-green)

---

> **NOT legal advice.** This is a portfolio project. Always consult a qualified advocate.

---

## What It Does

A user types a legal question. The system:

1. Runs **Named Entity Recognition** (fine-tuned DistilBERT) to extract legal entities — judges, statutes, provisions, case numbers
2. Augments the query with extracted entities and embeds it using **MiniLM** (384-dim)
3. Searches a **FAISS index** of 443,598 judgment chunks for the most relevant excerpts
4. Assembles **1024-token context windows** from the parent judgments around each matched chunk
5. Makes a **single LLM call** (Groq — Llama-3.3-70b) with a strict "answer only from provided excerpts" prompt
6. Runs **deterministic citation verification** — checks whether quoted phrases in the answer appear verbatim in the retrieved context

---

## Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────────┐
│  NER Layer (DistilBERT fine-tuned)      │
│  Extracts: JUDGE, COURT, STATUTE,       │
│  PROVISION, CASE_NUMBER, DATE           │
└──────────────────┬──────────────────────┘
                   │ augmented query
                   ▼
┌─────────────────────────────────────────┐
│  Embedding Layer (MiniLM-L6-v2)         │
│  384-dim sentence embedding             │
└──────────────────┬──────────────────────┘
                   │ query vector
                   ▼
┌─────────────────────────────────────────┐
│  FAISS Retrieval (IndexFlatL2)          │
│  443,598 chunks — 26,688 SC judgments   │
│  Memory-mapped — index never fully      │
│  loaded into RAM                        │
└──────────────────┬──────────────────────┘
                   │ top-5 chunks + parent context
                   ▼
┌─────────────────────────────────────────┐
│  LLM Generation (Groq — Llama-3.3-70b) │
│  Single call, strict grounding prompt   │
│  Gemini as fallback                     │
└──────────────────┬──────────────────────┘
                   │ answer
                   ▼
┌─────────────────────────────────────────┐
│  Citation Verification (deterministic)  │
│  Verified ✓ / ⚠ Unverified             │
└──────────────────┬──────────────────────┘
                   │
                   ▼
            JSON Response
```

**Deployment:** Docker container on HuggingFace Spaces (port 7860). Models downloaded from HF Hub at startup — not bundled in the image.

---

## Technical Decisions

**Why no LangChain?**
I built the chunking pipeline, FAISS retrieval, agent loop, and citation verification from scratch in plain Python. This means I can debug each component independently and explain exactly what each one does. I know what LangChain abstracts because I built what it abstracts. I am fully prepared to use LangChain or LangGraph in a team setting.

**Why DistilBERT for NER?**
DistilBERT is 40% smaller and 60% faster than BERT with 97% of its performance. For a token classification task like NER, this tradeoff is correct — the speed matters at inference time and the accuracy loss is negligible for legal entity types.

**Why FAISS IndexFlatL2?**
Exact nearest neighbour search over 443,598 vectors. Approximate methods (HNSW, IVF) trade accuracy for speed — unnecessary at this corpus size. Memory mapping keeps the 650MB index off RAM until a query needs it.

**Why MiniLM for embeddings?**
`all-MiniLM-L6-v2` is designed specifically for semantic similarity tasks. 384 dimensions gives a good balance between retrieval quality and index size. Runs entirely on CPU — no GPU dependency at inference time.

**Why a single LLM call per query?**
Multi-step chains add latency, introduce more failure points, and make hallucination harder to trace. One call with a strict grounding prompt is simpler, faster, and easier to debug. The citation verifier is the safety layer, not a second LLM call.

**Why deterministic citation verification?**
NLI-based verification requires loading a second model (~500MB) and adds ~300ms latency per query. For a portfolio project on a free tier, deterministic substring matching after normalisation gives 80% of the value at 0% of the cost. The limitation (paraphrases pass as verified) is documented.

**Why parent document retrieval?**
Chunks are 256 tokens — good for retrieval precision. But 256 tokens is often mid-sentence with no surrounding context. The LLM needs more. The system retrieves a 1024-token window centred on each matched chunk from the full parent judgment, giving the LLM enough context to answer correctly.

---

## Performance

| Metric | Value |
|---|---|
| NER F1 (overall) | 0.777 |
| Index size | 443,598 chunks from 26,688 judgments |
| FAISS index size on disk | ~650MB |
| Embedding dimensions | 384 |
| Typical query latency | 1,000–1,800ms |
| LLM | Groq Llama-3.3-70b-versatile |
| Deployment | HuggingFace Spaces, CPU only, free tier |

Latency breakdown: ~5ms FAISS search, ~50ms NER + embedding, ~900–1500ms Groq API call, ~10ms citation verification.

---

## Live Query Examples

**Health check:**
```
PS> Invoke-RestMethod -Uri "https://caffeinatedcoding-nyayasetu.hf.space/health"

status  service   version
------  -------   -------
ok      NyayaSetu 1.0.0
```

---

**Query: Fundamental rights under the Indian Constitution**
```
PS> Invoke-RestMethod -Uri "https://caffeinatedcoding-nyayasetu.hf.space/query" `
      -Method POST -ContentType "application/json" `
      -Body '{"query": "What are the fundamental rights guaranteed under the Indian Constitution?"}'

query               : What are the fundamental rights guaranteed under the Indian Constitution?
answer              : The fundamental rights guaranteed under the Indian Constitution are divided
                      into seven categories:
                      "right to equality - arts. 14 to 18;
                      right to freedom - arts. 19 to 22;
                      right against exploitation - arts. 23 and 24;
                      right to freedom of religion arts. 25 to 28;
                      cultural and educational rights arts. 29 and 30;
                      right to property - arts. 31, 31 a and 31b;
                      and right to constitutional remedies arts. 32 to 35" (SC_1958_9972).
                      These fundamental rights are "still reserved to the people after the
                      delegation of rights by the people to the institutions of government"
                      (SC_1958_9972).
                      The Constitution "confirms their existence and gives them protection"
                      (SC_2017_2363).

                      NOTE: This is not legal advice. Consult a qualified advocate.

sources             : SC_2017_2363 (Justice K S Puttaswamy Retd And Anr vs Union Of India, 2017)
                      SC_1958_9972 (Basheshar Nath vs The Commissioner Of Income Tax Delhi, 1958)
                      SC_1992_25797 (Life Insurance Corpn Of India vs Prof Manubhai D Shah, 1992)
                      SC_1962_10537 (Prem Chand Garg vs Excise Commissioner U P Allahabad, 1962)
verification_status : Unverified
entities            : STATUTE
num_sources         : 5
truncated           : False
latency_ms          : 1768.34
```

---

**Query: Right to privacy**
```
PS> Invoke-RestMethod -Uri "https://caffeinatedcoding-nyayasetu.hf.space/query" `
      -Method POST -ContentType "application/json" `
      -Body '{"query": "What is the right to privacy in India and how did the Supreme Court rule on it?"}'

query               : What is the right to privacy in India and how did the Supreme Court rule on it?
answer              : The right to privacy in India is "not absolute" and is "subject to certain
                      reasonable restrictions on the basis of compelling social, moral and public
                      interest" as stated in Justice K S Puttaswamy Retd And Anr vs Union Of India
                      And Ors (ID: SC_2017_2363). According to the same judgment, "the right to
                      privacy has been implied in articles 19 (1) (a) and (d) and article 21" of
                      the Constitution.

                      As noted in Distt Registrar Collector vs Canara Bank Etc (ID: SC_2004_4562),
                      "the right to privacy has been widely accepted as implied in our constitution"
                      and is "the right to be let alone".

                      The Supreme Court has ruled that the right to privacy is a fundamental right
                      emanating from Article 21 of the Constitution, as stated in Justice K S
                      Puttaswamy Retd And Anr vs Union Of India And Ors (ID: SC_2017_2363).

                      NOTE: This is not legal advice. Consult a qualified advocate.

sources             : SC_2017_2363 (Justice K S Puttaswamy Retd And Anr vs Union Of India, 2017)
                      SC_2018_24210 (Justice K S Puttaswamy Retd vs Union Of India, 2018)
                      SC_2004_4562 (Distt Registrar Collector vs Canara Bank Etc, 2004)
verification_status : Unverified
entities            : GPE, COURT
num_sources         : 5
truncated           : False
latency_ms          : 1051.71
```

---

**Query: Doctrine of proportionality**
```
PS> Invoke-RestMethod -Uri "https://caffeinatedcoding-nyayasetu.hf.space/query" `
      -Method POST -ContentType "application/json" `
      -Body '{"query": "What is the doctrine of proportionality and how is it applied in fundamental rights cases?"}'

query               : What is the doctrine of proportionality and how is it applied in
                      fundamental rights cases?
answer              : The doctrine of proportionality is a principle that guides the limitation of
                      fundamental rights. As stated in Anuradha Bhasin vs Union Of India
                      (ID: SC_2020_1572), "the proportionality principle, can be easily summarized
                      by lord diplock's aphorism — you must not use a steam hammer to crack a nut,
                      if a nutcracker would do?"

                      According to Justice K S Puttaswamy Retd vs Union Of India (ID: SC_2018_24210),
                      the proportionality test involves four stages: "a legitimate goal stage";
                      "a suitability or rational connection stage"; "a necessity stage"; and
                      "a balancing stage".

                      In Modern Dental College Res Cen Ors vs State Of Madhya Pradesh Ors
                      (ID: SC_2016_19144), "when a law limits a constitutional right, such a
                      limitation is constitutional if it is proportional".

                      NOTE: This is not legal advice. Consult a qualified advocate.

sources             : SC_2020_1572 (Anuradha Bhasin vs Union Of India, 2020)
                      SC_2018_24210 (Justice K S Puttaswamy Retd vs Union Of India, 2018)
                      SC_2016_19144 (Modern Dental College Res Cen vs State Of Madhya Pradesh, 2016)
                      SC_2023_16817 (Ramesh Chandra Sharma vs The State Of Uttar Pradesh, 2023)
verification_status : Unverified
entities            : (none extracted)
num_sources         : 5
truncated           : False
latency_ms          : 1511.71
```

---

**Validation — query too short (fails fast, model never called):**
```
PS> Invoke-RestMethod -Uri "https://caffeinatedcoding-nyayasetu.hf.space/query" `
      -Method POST -ContentType "application/json" `
      -Body '{"query": "help"}'

Invoke-RestMethod : {"detail":"Query too short — minimum 10 characters"}
StatusCode        : 400
```

---

**Out-of-domain query — LLM correctly refuses:**
```
PS> Invoke-RestMethod -Uri "https://caffeinatedcoding-nyayasetu.hf.space/query" `
      -Method POST -ContentType "application/json" `
      -Body '{"query": "Who won the IPL cricket tournament this year?"}'

answer              : The provided Supreme Court judgment excerpts do not contain any information
                      about the IPL cricket tournament or its winners. The excerpts appear to be
                      court judgments with case information, judge names, and dates, but they do
                      not mention the IPL or any related topics.
verification_status : No verifiable claims
entities            : ORG
num_sources         : 5
latency_ms          : 571.68
```

---

## API

**POST /query**
```json
{
  "query": "What is the doctrine of proportionality in fundamental rights cases?"
}
```

Response:
```json
{
  "query": "...",
  "answer": "The doctrine of proportionality... (SC_2018_24210)",
  "sources": [
    {
      "judgment_id": "SC_2018_24210",
      "title": "Justice K S Puttaswamy Retd vs Union Of India",
      "year": "2018",
      "similarity_score": 0.689,
      "excerpt": "..."
    }
  ],
  "verification_status": "Verified",
  "unverified_quotes": [],
  "entities": {"COURT": ["Supreme Court"]},
  "num_sources": 5,
  "truncated": false,
  "latency_ms": 1511.71
}
```

**GET /health** — `{"status": "ok", "service": "NyayaSetu", "version": "1.0.0"}`

**GET /** — app info and endpoint list

---

## Project Structure

```
NyayaSetu/
├── preprocessing/
│   ├── clean.py              ← text cleaning, OCR error fixing
│   ├── chunk.py              ← recursive splitter, 256 tokens, 50 overlap
│   ├── embed.py              ← MiniLM batch embedding
│   └── build_index.py        ← FAISS IndexFlatL2 construction
├── src/
│   ├── ner.py                ← DistilBERT NER inference
│   ├── retrieval.py          ← FAISS search + parent context assembly
│   ├── agent.py              ← single-pass query pipeline
│   ├── llm.py                ← Groq API call + tenacity retry
│   └── verify.py             ← deterministic citation verification
├── api/
│   ├── main.py               ← FastAPI, 3 endpoints, model download at startup
│   └── schemas.py            ← Pydantic request/response models
├── tests/
│   ├── test_retriever.py
│   ├── test_agent.py
│   ├── test_verify.py
│   └── test_api.py
├── .github/workflows/ci.yml  ← pytest → lint → docker build → HF deploy → smoke test
└── docker/Dockerfile


```

## V2 Agent Architecture

**Pass 1 — Analyse:** LLM call to understand the message, detect tone/stage, 
build structured fact web, update hypotheses, form targeted FAISS queries.

**Pass 2 — Retrieve:** Parallel FAISS search across 3 queries. No LLM call. ~5ms.

**Pass 3 — Respond:** Dynamically assembled prompt based on tone, stage, and 
format needs + full case state + retrieved context.

**Conversation Memory:** Each session maintains a compressed summary + structured 
fact web (parties, events, documents, amounts, hypotheses) updated every turn.

---

## Setup & Reproduction

```bash
git clone https://github.com/devangmishra1424/nyayasetu
cd nyayasetu

pip install -r requirements.txt

# Set environment variables
export GROQ_API_KEY=your_key_here
export HF_TOKEN=your_token_here

# Models (~2.7GB) download automatically from HF Hub at startup
uvicorn api.main:app --host 0.0.0.0 --port 7860
```

---

## Limitations

**Data scope:** Supreme Court of India judgments only, 1950–2024. No High Court judgments, no legislation, no legal commentary.

**Citation verification:** The verifier does exact substring matching after normalisation. LLM paraphrases pass as Verified even when the underlying claim is correct. Full paraphrase detection would require NLI inference — out of scope for v1.

**Out-of-domain queries:** The similarity threshold blocks most irrelevant queries. Queries that share vocabulary with legal text may still pass through to the LLM, which will correctly report no relevant information found.

**Not a legal database:** This system cannot be used as a substitute for Westlaw, SCC Online, or Indian Kanoon. It is a portfolio demonstration of RAG pipeline engineering.

**v1 — planned improvements:**
- Gradio frontend for non-technical users
- MLflow experiment tracking for NER training runs
- Evidently drift monitoring on query logs
- High Court judgment coverage
- Re-ranking layer (cross-encoder) between FAISS retrieval and LLM call

---

## Bug Log

**Bug 1 — `snapshot_download` with `allow_patterns` fetching 0 files**
The FAISS index files were uploaded to HuggingFace Hub under a `faiss_index/` subfolder. The `snapshot_download` call with `allow_patterns="faiss_index/*"` returned 0 files — it couldn't match the pattern against the subfolder structure. Fixed by switching to `hf_hub_download` with explicit `filename` paths per file. Lesson: `snapshot_download` pattern matching behaves differently for nested paths than expected.

**Bug 2 — L2 distance threshold logic inverted**
The similarity threshold in `retrieval.py` used `if best_score < SIMILARITY_THRESHOLD: return []`. This is correct for cosine similarity (higher = better) but wrong for L2 distance (lower = better). The condition was blocking good legal queries and letting through out-of-domain queries. Fixed by flipping to `if best_score > SIMILARITY_THRESHOLD` and setting threshold to 0.85. Lesson: always verify which direction your distance metric runs before writing threshold logic.

**Bug 3 — `api/__init__.py` contained a shell command**
The `api/__init__.py` file contained `echo ""` — a leftover from a PowerShell command accidentally piped into the file. Python threw a syntax error at startup. Fixed by overwriting with an empty string. Lesson: on Windows, `echo "" > file` writes the shell command into the file. Use `"" | Out-File -FilePath file -Encoding utf8` instead.
