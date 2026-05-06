# AGENTS.md

This repository is a private/internal standards assistant for IEEE, IEC, SPLN, SNI, and related electrical engineering PDF documents.

## Product rules

- The system must not publish copyrighted standards text publicly.
- The system must not send full PDFs to Gemini.
- The system should only send selected retrieved chunks to Gemini.
- The system must cite standard body, file/standard name, clause/section if available, and page number.
- If retrieved context is insufficient, the assistant must say so clearly.
- Prefer retrieval-first behavior over general LLM answers.
- Bahasa Indonesia is the default language.
- English must be available as an optional selected language.

## Tech rules

- Use Python and Streamlit.
- Use JSONL/JSON/CSV files as the lightweight database.
- Do not require PostgreSQL, Supabase, Firebase, Pinecone, Chroma, Qdrant, or other hosted databases.
- Google Drive or a local synced Drive folder is the document storage layer.
- For hosted demos, Google Drive API service-account sync may download PDFs into temporary local storage before indexing.
- Use PyMuPDF for PDF extraction.
- Use Tesseract OCR only as a local fallback for scanned PDFs; do not send full PDFs to Gemini for OCR.
- Use scikit-learn TF-IDF search for the first version.
- Gemini 2.5 Flash is used only for answer generation after retrieval.

## Code style

- Keep the code simple and readable.
- Add type hints to public functions.
- Add docstrings to major functions.
- Avoid unnecessary abstractions.
- Handle missing files, empty PDFs, scanned PDFs, and missing API keys gracefully.
- Do not log full standard excerpts by default.
- Do not commit `.env`, Streamlit secrets, service account keys, generated indexes, or standards PDFs.
- Do not hardcode English UI text directly in Streamlit components. Use the translation dictionary.

## Main user flows

1. Put PDFs in `data/pdfs/`.
2. Build/rebuild the index.
3. Ask questions with retrieved evidence.
4. Compare IEC vs IEEE vs SPLN by topic.

# Quality requirements

- Make the first version simple and working.
- Prefer readable code over complex abstractions.
- Add type hints where useful.
- Add docstrings to major functions.
- Handle empty PDFs, scanned PDFs, and missing text gracefully.
- If PDF appears scanned, warn user that OCR is not implemented yet.
- Do not implement OCR in the first version unless easy.
- Do not add unnecessary dependencies.
- Do not require a real database.
- Do not require local GPU.
- Do not require Docker.
- Do not require cloud deployment.
- Keep everything runnable locally.

# Definition of done

The implementation is complete when:

- I can place IEC, IEEE, SPLN, and SNI PDFs in `data/pdfs/`.
- I can run the Streamlit app.
- I can choose Bahasa Indonesia by default or switch to English.
- I can build a `chunks.jsonl` index.
- I can search chunks by keyword/topic.
- I can ask Gemini a question using only retrieved chunks.
- I can compare IEC vs IEEE vs SPLN on a topic.
- Output includes citations with standard/body/file/page/clause when available.
- No full PDF is sent to Gemini.
- The README explains setup and usage.
- Basic import checks pass.
