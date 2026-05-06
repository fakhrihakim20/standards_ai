# Asisten Standar IEEE-IEC-SPLN

Prototype Streamlit untuk asisten standar internal/private. Aplikasi membaca PDF standar dari folder lokal, mengekstrak teks dengan PyMuPDF, membuat indeks JSONL ringan, mengambil cuplikan relevan secara lokal dengan TF-IDF, lalu mengirim hanya cuplikan terpilih ke Gemini 2.5 Flash.

## Privacy and Copyright

This app is for private/internal use with documents you have rights to access. Do not publish copyrighted standards text publicly. The app sends only selected retrieved excerpts to Gemini, not full PDFs. Answers should cite sources and say when retrieved context is insufficient. Always verify final answers against the official standards.

## Folder Structure

```text
standards_ai/
|-- app.py
|-- requirements.txt
|-- packages.txt
|-- .env.example
|-- .gitignore
|-- README.md
|-- AGENTS.md
|-- .streamlit/
|   `-- secrets.example.toml
|-- data/
|   |-- pdfs/
|   `-- index/
|       |-- chunks.jsonl
|       `-- standards_index.json
`-- src/
    |-- pdf_extract.py
    |-- chunking.py
    |-- indexing.py
    |-- search.py
    |-- compare.py
    |-- drive_storage.py
    |-- gemini_client.py
    |-- ocr.py
    |-- prompts.py
    |-- i18n.py
    `-- utils.py
```

## Setup

Run these commands from the `standards_ai/` folder:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

For Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

Edit `.env`:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GOOGLE_DRIVE_FOLDER_ID=your_google_drive_folder_id_here
GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service-account.json
APP_ENCRYPTION_KEY=generate_with_python_cryptography_fernet_key
DISABLE_LOGIN=false
```

Generate an encryption key for saved per-user defaults:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Google Drive PDF Storage

For free Streamlit Community Cloud hosting, keep standards PDFs in Google Drive and share the folder with a Google Cloud service account.

High-level steps:

1. Create a Google Cloud project.
2. Enable the Google Drive API.
3. Create a service account and download its JSON key.
4. Create or choose a Google Drive folder for standards PDFs.
5. Share that Drive folder with the service account `client_email`.
6. Set `GOOGLE_DRIVE_FOLDER_ID` and service account credentials in `.env` locally or Streamlit secrets in the cloud.

For Streamlit Community Cloud, paste secrets like this:

```toml
GEMINI_API_KEY = "your_gemini_api_key_here"
GEMINI_MODEL = "gemini-2.5-flash"
GOOGLE_DRIVE_FOLDER_ID = "your_google_drive_folder_id_here"
APP_ENCRYPTION_KEY = "generate_with_python_cryptography_fernet_key"
DISABLE_LOGIN = false
GOOGLE_SERVICE_ACCOUNT_JSON = """
{
  "type": "service_account",
  "project_id": "...",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n",
  "client_email": "...",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "...",
  "universe_domain": "googleapis.com"
}
"""

[auth]
redirect_uri = "https://your-streamlit-app.streamlit.app/oauth2callback"
cookie_secret = "generate_a_long_random_string"
client_id = "your_google_oauth_client_id"
client_secret = "your_google_oauth_client_secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
client_kwargs = { "scope" = "openid email profile" }
```

The app downloads PDFs from Drive into temporary local storage, then builds the local JSONL index. It still does not send full PDFs to Gemini.

For saving defaults and OCR/index cache back to Drive, share the Drive folder with the service account as **Editor**. Viewer access is enough for reading PDFs, but not enough for writing cache/settings files.

You can also provide credentials directly in the web UI:

- Sidebar: enter a custom Gemini API key and Gemini model.
- `Indeks PDF / Index PDFs`: enter a Google Drive folder link or folder ID.
- Upload or paste the Google service account JSON.

Credentials entered in the UI are used only for the current Streamlit session. They are not written to `.env`, JSON files, or the repository.

## Google Login and Per-Account Defaults

The app supports Google login through Streamlit's native OIDC login. Configure the `[auth]` block in Streamlit secrets and add the deployed URL as an authorized redirect URI in Google Cloud:

```text
https://your-streamlit-app.streamlit.app/oauth2callback
```

If `[auth]` is missing, the app shows a login configuration warning instead of silently entering guest mode. For local development only, set:

```toml
DISABLE_LOGIN = true
```

After login, users can save encrypted defaults per Google account:

- Gemini API key
- Gemini model
- Google Drive folder link/ID
- Google service account JSON
- service account email

Defaults are encrypted with `APP_ENCRYPTION_KEY` and stored as JSON files in Google Drive under:

```text
.standards_ai_cache/user_settings/
```

Do not lose or rotate `APP_ENCRYPTION_KEY` unless you are willing to discard saved defaults.

## Free Cloud Database / OCR Cache

Yes, this system can use a free cloud storage layer before adding a real database. For this prototype, Google Drive is used as a lightweight cloud database:

```text
.standards_ai_cache/index_cache/chunks.jsonl
.standards_ai_cache/index_cache/standards_index.json
```

Recommended workflow for many scanned PDFs:

1. Sync PDFs from Google Drive.
2. Enable OCR.
3. Rebuild the index once.
4. Click `Save OCR/index cache to Drive`.
5. On future redeploys, click `Load OCR/index cache from Drive`.

This avoids repeating OCR every time Streamlit Cloud restarts. It also keeps the no-PostgreSQL/no-vector-database constraint.

## Add PDFs Locally

Put IEC, IEEE, SPLN, SNI, or related electrical engineering PDFs in:

```text
data/pdfs/
```

The app detects the standards body and likely standard number from file names such as `IEC_60599.pdf`, `IEEE_C57_104.pdf`, `SPLN_D3_002.pdf`, or `SNI_...pdf`.

## Build or Rebuild Index

Open the `Indeks PDF / Index PDFs` tab.

If using Google Drive, paste the folder link/ID and service account JSON, then click `Sinkronkan dari Google Drive / Sync from Google Drive` first. The app shows the Drive PDF locations that were downloaded. Then click `Bangun Ulang Indeks / Rebuild Index`.

The app creates:

- `data/index/chunks.jsonl`
- `data/index/standards_index.json`
- `data/index/drive_manifest.json`

When PDFs are synced from Google Drive, chunks include Drive source metadata:

- `drive_path`
- `drive_file_id`
- `drive_web_url`

If a PDF has little or no extractable text, enable `Gunakan OCR untuk PDF hasil scan / Use OCR for scanned PDFs` before rebuilding the index. OCR uses local Tesseract after the PDF is downloaded or placed locally. It still does not send full PDFs to Gemini.

For local Windows usage, install Tesseract OCR separately if OCR fails with `Tesseract executable is not installed`. Streamlit Community Cloud installs Tesseract from `packages.txt`.

## Ask Questions

Use the `Tanya Standar / Ask Standards` tab. The app retrieves top chunks locally in the background, builds a compact prompt, and sends only those retrieved chunks to Gemini. It never sends full PDFs.

## Compare IEC vs IEEE vs SPLN

Use the `Bandingkan IEC vs IEEE vs SPLN / Compare` tab. Enter a topic, select bodies, and compare. Retrieval is done separately per selected standards body so Gemini receives grouped evidence.

## GitHub and Streamlit Community Cloud

Recommended free deployment:

1. Push this project to a private GitHub repository.
2. Do not commit `.env`, `.streamlit/secrets.toml`, PDFs, or generated indexes.
3. In Streamlit Community Cloud, create an app from the GitHub repo.
4. Set the app entrypoint to `app.py`.
5. Paste the secrets shown above into Advanced settings.
6. Share the Google Drive PDF folder with the service account email.
7. In the app, sync from Google Drive and rebuild the index.

## Troubleshooting

- Missing API key: create `.env` from `.env.example` and set `GEMINI_API_KEY`.
- Google Drive configuration missing: set `GOOGLE_DRIVE_FOLDER_ID` and service account credentials.
- Google Drive finds no PDFs: confirm the folder ID is correct and the folder is shared with the service account email.
- No PDFs found: place PDFs in `data/pdfs/`.
- Empty or scanned PDFs: enable OCR when rebuilding the index. If OCR is unavailable locally, install Tesseract OCR and make sure it is on PATH.
- Gemini API error: check your API key, internet connection, quota, and model name.
- Poor search results: use more specific technical terms, standard numbers, gas names such as `CO`, `CO2`, `H2`, `CH4`, `C2H2`, or increase the number of excerpts.
