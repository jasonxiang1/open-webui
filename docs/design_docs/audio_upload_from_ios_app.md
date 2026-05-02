---

````markdown
# Audio Upload and Ingestion for OpenWebUI

## Overview
This document describes how to extend the OpenWebUI repository to support **audio file ingestion** from an external client (e.g., a React Native iOS mobile app). The audio will be uploaded to OpenWebUI, transcribed into text, and inserted into the **existing knowledge base (KB) and vector database** pipeline for semantic search and retrieval.

The goal is to:
1. Add a new API endpoint for audio upload.
2. Transcribe audio into text using Whisper (or external STT engine).
3. Store transcription in the knowledge database.
4. Insert embeddings into the vector database, with audio metadata preserved.
5. (Optional) Allow the web UI to display and playback audio.

---

## Architecture Changes

### New Components
- **Router**: `server/routers/audio.py`
  - Handles file upload via `POST /audio/upload`.
- **Service**: `server/services/transcription.py`
  - Provides `transcribe_audio(file_path: str) -> str`.
- **Knowledge Service Update**: `insert_into_kb` extended to accept audio metadata.
- **Static File Storage**: Store uploaded audio in `uploads/audio/{knowledge_base_id}/`.

### Data Flow
1. Client sends audio file + `knowledge_base_id` to `POST /audio/upload`.
2. File is saved under `uploads/audio/{knowledge_base_id}/{uuid}.m4a`.
3. Audio is transcribed → text string.
4. Text is inserted into KB with metadata:
   ```json
   {
     "kb_id": "support_calls",
     "text": "transcribed text here",
     "metadata": {
       "audio_path": "uploads/audio/support_calls/{uuid}.m4a",
       "file_id": "{uuid}"
     }
   }
````

5. Embeddings are generated from `text` and stored in the vector DB.

---

## API Contract

### Endpoint: `POST /audio/upload`

**Request (multipart/form-data):**

* `file`: Audio file (e.g., `.m4a`, `.wav`, `.mp3`).
* `knowledge_base_id`: String identifier for KB.

**Response (JSON):**

```json
{
  "status": "success",
  "file_id": "uuid",
  "transcription": "Hello, I need help resetting my password."
}
```

**Error Responses:**

* `400 Bad Request` – Missing file or invalid KB ID.
* `500 Internal Server Error` – Transcription or DB insertion failure.

---

## Implementation Details

### 1. Router: `server/routers/audio.py`

```python
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from uuid import uuid4
import shutil, os
from server.services.transcription import transcribe_audio
from server.services.knowledge import insert_into_kb

router = APIRouter(prefix="/audio", tags=["Audio"])

UPLOAD_DIR = "uploads/audio"

@router.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form(...)
):
    try:
        os.makedirs(f"{UPLOAD_DIR}/{knowledge_base_id}", exist_ok=True)
        file_id = str(uuid4())
        file_path = f"{UPLOAD_DIR}/{knowledge_base_id}/{file_id}.m4a"

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        transcription = transcribe_audio(file_path)

        insert_into_kb(
            kb_id=knowledge_base_id,
            text=transcription,
            metadata={"audio_path": file_path, "file_id": file_id}
        )

        return {"status": "success", "file_id": file_id, "transcription": transcription}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

### 2. Service: `server/services/transcription.py`

```python
def transcribe_audio(file_path: str) -> str:
    """
    Transcribe audio file into text.
    Default implementation uses OpenAI Whisper.
    Replace with cloud API if needed.
    """
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(file_path)
        return result["text"]
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {e}")
```

---

### 3. Update: `server/services/knowledge.py`

Modify `insert_into_kb` to allow audio metadata.

```python
def insert_into_kb(kb_id: str, text: str, metadata: dict):
    entry = {
        "kb_id": kb_id,
        "text": text,
        "metadata": metadata
    }
    # Existing functions handle persistence + embeddings
    save_to_relational_db(entry)
    save_to_vector_db(entry["text"], metadata=entry["metadata"])
```

---

### 4. FastAPI Main App Integration

In `server/main.py`:

```python
from server.routers import audio

app.include_router(audio.router)
```

---

### 5. File Storage

* Directory: `uploads/audio/{knowledge_base_id}/`
* Naming convention: `{uuid}.m4a`
* Ensure directory is created if missing.

---

## Security & Validation

* Restrict uploads to audio MIME types (`audio/mpeg`, `audio/wav`, `audio/mp4`, etc.).
* Validate `knowledge_base_id` against existing KBs.
* Apply existing authentication/authorization middleware.
* Sanitize file paths (avoid traversal).

---

## Optional UI Extensions

* In the OpenWebUI frontend, display transcription text in KB entries.
* If `metadata.audio_path` exists, render:

  ```html
  <audio controls src="/uploads/audio/{kb_id}/{file_id}.m4a"></audio>
  ```

---

## Future Extensions

* Background transcription queue for large uploads.
* Support for additional file formats (e.g., video).
* Speaker diarization for multi-speaker recordings.
* Compression before upload (Opus/WebM).

---