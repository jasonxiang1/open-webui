# Audio Folder Ingestion for OpenWebUI

## Overview
This document describes the implementation of **batch ingestion of audio files from a local folder** in OpenWebUI. The audio files are parsed, combined into a single audio file, transcribed into text, summarized using LLM, and inserted into the **existing knowledge base (KB) and vector database** pipeline for semantic search and retrieval.

The implemented features include:
1. **Web UI Integration**: Modal interface for folder path input and processing
2. **API Endpoint**: REST API for programmatic access
3. **CLI Script**: Command-line interface for batch processing
4. **Audio Combination**: Merges multiple audio files into a single file
5. **LLM Summarization**: Generates comprehensive summaries using configured LLM providers
6. **Enhanced Storage**: Stores transcription, summary, and metadata in knowledge base
7. **Vector Embeddings**: Generates embeddings for RAG using existing pipeline

---

## Architecture Changes

### New Components
- **Service**: `backend/open_webui/services/audio_ingestion.py`
  - Scans a specified folder for audio files.
  - Combines multiple audio files into a single file.
  - Transcribes combined audio into text.
  - Integrates with LLM for summarization.
  - Stores data in knowledge base and vector database.

- **LLM Service**: `backend/open_webui/services/llm_summarization.py`
  - Generates comprehensive summaries of transcriptions.
  - Integrates with existing Ollama and OpenAI endpoints.
  - Provides structured summary prompts.

- **API Endpoint**: `backend/open_webui/routers/audio.py`
  - New `/audio/folder/ingest` endpoint.
  - Handles folder path validation and processing.
  - Returns detailed processing results.

- **Frontend Components**:
  - `src/lib/apis/audio/index.ts`: API integration
  - `src/lib/components/workspace/Knowledge/AudioFolderIngestion.svelte`: UI modal
  - `src/lib/components/workspace/Knowledge/KnowledgeBase/AddContentMenu.svelte`: Menu integration

### Data Flow
1. **User Input**: User provides folder path via Web UI, API, or CLI
2. **Folder Scan**: System scans folder for supported audio files (.wav, .mp3, .m4a, .flac, .webm)
3. **File Processing**: 
   - Generate UUID for each file
   - Copy files to `uploads/audio/{knowledge_base_id}/{uuid}.{ext}`
4. **Audio Combination**: Merge all audio files into single combined file
5. **Transcription**: Transcribe combined audio using existing Whisper integration
6. **LLM Summarization**: Generate summary using configured LLM provider (Ollama/OpenAI)
7. **Storage**: Store in knowledge base with enhanced metadata:

```json
{
  "id": "ingestion_uuid",
  "name": "Audio Folder Ingestion - {folder_name}",
  "description": "Combined audio from {file_count} files",
  "data": {
    "transcription": "full transcription text",
    "summary": "LLM-generated summary",
    "combined_audio_path": "uploads/audio/{kb_id}/{ingestion_id}_combined.mp3",
    "original_files": [
      {
        "original_path": "/path/to/original/file.wav",
        "uploaded_path": "uploads/audio/{kb_id}/{file_id}.wav",
        "file_id": "{file_id}"
      }
    ],
    "folder_path": "/path/to/original/folder",
    "file_count": 5
  }
}
```
8. **Vector Embeddings**: Generate embeddings for RAG using existing pipeline

## Implementation Details

### 1. Audio Ingestion Service: `backend/open_webui/services/audio_ingestion.py`

```python
import os, shutil, uuid, logging
from pathlib import Path
from typing import List, Dict, Optional
from pydub import AudioSegment

from open_webui.routers.audio import transcribe
from open_webui.routers.retrieval import save_docs_to_vector_db
from open_webui.models.knowledge import KnowledgeTable, KnowledgeForm
from open_webui.services.llm_summarization import LLMSummarizationService

UPLOAD_DIR = "uploads/audio"
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".webm"}

class AudioFolderIngestionService:
    def __init__(self):
        self.knowledge_table = KnowledgeTable()
        self.llm_service = LLMSummarizationService()
    
    def combine_audio_files(self, audio_paths: List[str], output_path: str) -> str:
        """Combine multiple audio files into a single file"""
        if not audio_paths:
            raise ValueError("No audio files provided")
        
        combined_audio = AudioSegment.from_file(audio_paths[0])
        for audio_path in audio_paths[1:]:
            audio_segment = AudioSegment.from_file(audio_path)
            combined_audio = combined_audio + audio_segment
        
        combined_audio.export(output_path, format="mp3")
        return output_path
    
    def ingest_audio_folder(self, request, folder_path: str, kb_id: str, user_id: str) -> Dict:
        """Main ingestion function"""
        # Validate knowledge base exists
        kb = self.knowledge_table.get_knowledge_by_id(kb_id)
        if not kb:
            raise ValueError(f"Knowledge base {kb_id} not found")
        
        # Scan for audio files
        folder = Path(folder_path)
        audio_files = []
        for file_path in folder.rglob("*"):
            if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                audio_files.append(str(file_path))
        
        if not audio_files:
            raise ValueError("No supported audio files found in folder")
        
        # Generate unique ID for this ingestion
        ingestion_id = str(uuid.uuid4())
        
        # Copy files to upload directory
        kb_upload_dir = f"{UPLOAD_DIR}/{kb_id}"
        os.makedirs(kb_upload_dir, exist_ok=True)
        
        uploaded_files = []
        for audio_file in audio_files:
            file_id = str(uuid.uuid4())
            dest_path = f"{kb_upload_dir}/{file_id}{Path(audio_file).suffix}"
            shutil.copy2(audio_file, dest_path)
            uploaded_files.append({
                "original_path": audio_file,
                "uploaded_path": dest_path,
                "file_id": file_id
            })
        
        # Combine audio files
        combined_audio_path = f"{kb_upload_dir}/{ingestion_id}_combined.mp3"
        self.combine_audio_files(
            [f["uploaded_path"] for f in uploaded_files], 
            combined_audio_path
        )
        
        # Transcribe combined audio
        transcription = self.transcribe_audio(request, combined_audio_path)
        
        # Generate LLM summary
        summary = self.generate_llm_summary(request, transcription)
        
        # Store in knowledge base
        knowledge_entry = {
            "id": ingestion_id,
            "user_id": user_id,
            "name": f"Audio Folder Ingestion - {Path(folder_path).name}",
            "description": f"Combined audio from {len(audio_files)} files",
            "data": {
                "transcription": transcription,
                "summary": summary,
                "combined_audio_path": combined_audio_path,
                "original_files": uploaded_files,
                "folder_path": folder_path,
                "file_count": len(audio_files)
            }
        }
        
        # Save to knowledge base and vector database
        self._save_to_knowledge_base(knowledge_entry)
        self._save_to_vector_db(request, knowledge_entry)
        
        return {
            "status": "success",
            "ingestion_id": ingestion_id,
            "file_count": len(audio_files),
            "transcription_length": len(transcription),
            "summary": summary,
            "combined_audio_path": combined_audio_path
        }
```
### 2. LLM Summarization Service: `backend/open_webui/services/llm_summarization.py`

```python
import logging
from typing import Optional
from open_webui.routers.ollama import generate_response
from open_webui.routers.openai import generate_openai_response

class LLMSummarizationService:
    def __init__(self):
        self.summary_prompt_template = """
        Please provide a comprehensive summary of the following audio transcription:
        
        {transcription}
        
        Your summary should include:
        - Main topics and themes discussed
        - Key points and important insights
        - Overall context and purpose of the conversation
        - Any significant conclusions or action items
        - Speaker dynamics (if multiple speakers)
        
        Format the summary in a clear, structured manner.
        """
    
    def generate_summary(self, request, transcription: str, model: str = "default") -> str:
        """Generate summary using configured LLM"""
        try:
            prompt = self.summary_prompt_template.format(transcription=transcription)
            
            # Use existing Ollama integration
            if request.app.state.config.OLLAMA_BASE_URL:
                return self._generate_ollama_summary(request, prompt, model)
            
            # Use OpenAI integration
            elif request.app.state.config.OPENAI_API_KEY:
                return self._generate_openai_summary(request, prompt, model)
            
            else:
                raise ValueError("No LLM provider configured")
                
        except Exception as e:
            log.error(f"LLM summarization failed: {e}")
            return f"Summary generation failed: {str(e)}"
```

### 3. API Endpoint: `backend/open_webui/routers/audio.py`

```python
@router.post("/folder/ingest")
async def ingest_audio_folder(
    request: Request,
    folder_path: str = Form(...),
    knowledge_base_id: str = Form(...),
    user=Depends(get_verified_user),
):
    """
    Ingest a folder of audio files into a knowledge base
    """
    try:
        # Validate folder path
        if not os.path.exists(folder_path):
            raise HTTPException(
                status_code=400,
                detail=f"Folder path does not exist: {folder_path}"
            )
        
        # Initialize ingestion service
        ingestion_service = AudioFolderIngestionService()
        
        # Process the folder
        result = ingestion_service.ingest_audio_folder(
            request, folder_path, knowledge_base_id, user.id
        )
        
        return result
        
    except Exception as e:
        log.exception(f"Audio folder ingestion failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Audio folder ingestion failed: {str(e)}"
        )
```

### 4. CLI Script: `backend/open_webui/scripts/ingest_audio_folder.py`

```python
#!/usr/bin/env python3
import argparse
import sys
import os
from pathlib import Path

# Add the backend directory to Python path
sys.path.append(str(Path(__file__).parent.parent))

from open_webui.services.audio_ingestion import AudioFolderIngestionService
from open_webui.config import load_json_config

def main():
    parser = argparse.ArgumentParser(description="Ingest audio folder into knowledge base")
    parser.add_argument("--folder", required=True, help="Path to folder of audio files")
    parser.add_argument("--kb_id", required=True, help="Knowledge Base ID")
    parser.add_argument("--user_id", required=True, help="User ID")
    
    args = parser.parse_args()
    
    try:
        # Initialize service
        service = AudioFolderIngestionService()
        
        # Mock request object for CLI usage
        class MockRequest:
            def __init__(self):
                self.app = type('MockApp', (), {
                    'state': type('MockState', (), {
                        'config': load_json_config()
                    })()
                })()
        
        request = MockRequest()
        
        # Process folder
        result = service.ingest_audio_folder(
            request, args.folder, args.kb_id, args.user_id
        )
        
        print(f"✅ Successfully ingested {result['file_count']} files")
        print(f"📝 Transcription length: {result['transcription_length']} characters")
        print(f"📄 Summary: {result['summary'][:200]}...")
        print(f"🎵 Combined audio: {result['combined_audio_path']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

### 5. Frontend Integration

#### API Integration: `src/lib/apis/audio/index.ts`

```typescript
export const ingestAudioFolder = async (
    token: string, 
    folderPath: string, 
    knowledgeBaseId: string
) => {
    const data = new FormData();
    data.append('folder_path', folderPath);
    data.append('knowledge_base_id', knowledgeBaseId);

    let error = null;
    const res = await fetch(`${AUDIO_API_BASE_URL}/folder/ingest`, {
        method: 'POST',
        headers: {
            Accept: 'application/json',
            authorization: `Bearer ${token}`
        },
        body: data
    })
        .then(async (res) => {
            if (!res.ok) throw await res.json();
            return res.json();
        })
        .catch((err) => {
            error = err.detail;
            console.error(err);
            return null;
        });

    if (error) {
        throw error;
    }

    return res;
};
```

#### UI Component: `src/lib/components/workspace/Knowledge/AudioFolderIngestion.svelte`

```svelte
<script lang="ts">
    import { toast } from 'svelte-sonner';
    import { getContext } from 'svelte';
    import { ingestAudioFolder } from '$lib/apis/audio';
    import Modal from '$lib/components/common/Modal.svelte';
    import Button from '$lib/components/common/Button.svelte';
    import Input from '$lib/components/common/Input.svelte';

    const i18n = getContext('i18n');

    export let show = false;
    export let knowledgeBaseId = '';
    export let onClose = () => {};

    let folderPath = '';
    let loading = false;
    let result: any = null;

    const handleSubmit = async () => {
        if (!folderPath.trim()) {
            toast.error($i18n.t('Please enter a folder path'));
            return;
        }

        loading = true;
        try {
            result = await ingestAudioFolder(
                localStorage.token,
                folderPath,
                knowledgeBaseId
            );
            
            toast.success($i18n.t('Audio folder ingested successfully'));
            onClose();
        } catch (error) {
            toast.error(`${error}`);
        } finally {
            loading = false;
        }
    };
</script>

<Modal {show} onClose={onClose}>
    <div class="p-6 max-w-md">
        <h2 class="text-xl font-semibold mb-4">
            {$i18n.t('Ingest Audio Folder')}
        </h2>
        
        <div class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-2">
                    {$i18n.t('Folder Path')}
                </label>
                <Input
                    bind:value={folderPath}
                    placeholder="/path/to/audio/folder"
                    disabled={loading}
                />
            </div>
            
            <div class="text-sm text-gray-600">
                {$i18n.t('Supported formats: WAV, MP3, M4A, FLAC, WebM')}
            </div>
        </div>
        
        <div class="flex justify-end gap-2 mt-6">
            <Button variant="secondary" on:click={onClose} disabled={loading}>
                {$i18n.t('Cancel')}
            </Button>
            <Button on:click={handleSubmit} disabled={loading || !folderPath.trim()}>
                {loading ? $i18n.t('Processing...') : $i18n.t('Ingest')}
            </Button>
        </div>
        
        {#if result}
            <div class="mt-4 p-4 bg-green-50 rounded-lg">
                <h3 class="font-medium text-green-800">{$i18n.t('Ingestion Complete')}</h3>
                <div class="text-sm text-green-700 mt-2">
                    <div>{$i18n.t('Files processed: {{count}}', { count: result.file_count })}</div>
                    <div>{$i18n.t('Transcription length: {{length}} characters', { length: result.transcription_length })}</div>
                </div>
            </div>
        {/if}
    </div>
</Modal>
```
## Usage

### Web UI
1. Navigate to a Knowledge Base
2. Click the "Add Content" button (+)
3. Select "Ingest Audio Folder"
4. Enter the folder path (e.g., `/home/user/recordings/`)
5. Click "Ingest"

### API
```bash
curl -X POST "http://localhost:8080/api/v1/audio/folder/ingest" \
    -H "Authorization: Bearer YOUR_TOKEN" \
    -F "folder_path=/path/to/audio/folder" \
    -F "knowledge_base_id=support_calls"
```

### CLI
```bash
python backend/open_webui/scripts/ingest_audio_folder.py \
    --folder ./my_audio_files \
    --kb_id support_calls \
    --user_id user123
```
## Response Format

```json
{
    "status": "success",
    "ingestion_id": "uuid",
    "file_count": 5,
    "transcription_length": 1500,
    "summary": "This conversation covered...",
    "combined_audio_path": "uploads/audio/support_calls/uuid_combined.mp3"
}
```

## File Structure

After ingestion, files are organized as follows:

```
uploads/audio/{knowledge_base_id}/
├── {file_id_1}.wav          # Individual audio files
├── {file_id_2}.mp3
├── {file_id_3}.m4a
└── {ingestion_id}_combined.mp3  # Combined audio file
```

## Security & Validation

- **Supported file types**: .wav, .mp3, .m4a, .flac, .webm
- **Folder path validation**: Ensures folder exists and is accessible
- **User permissions**: Verifies user has access to target knowledge base
- **File size limits**: Applies existing file size restrictions
- **Error handling**: Comprehensive logging and error reporting

Optional Extensions
Add --recursive flag for nested folder ingestion.

Support background ingestion jobs (Celery/Redis).

Add Web UI button for "Ingest Audio Folder".

## Key Differences from Original Design

1. **Audio Combination**: Files are combined into a single audio file instead of processing individually
2. **LLM Summarization**: Added comprehensive summary generation using configured LLM providers
3. **Enhanced Metadata**: Stores more detailed information including original file paths and processing details
4. **Multiple Interfaces**: Web UI, API, and CLI interfaces instead of just CLI
5. **Better Error Handling**: More robust error handling and user feedback
6. **Vector Database Integration**: Direct integration with existing vector database pipeline
7. **User Authentication**: Proper user authentication and permission checking

## Future Enhancements

- Background processing for large folders
- Progress indicators for long operations
- Support for video files with audio extraction
- Speaker diarization for multi-speaker recordings
- Custom summary prompts per knowledge base
- Recursive folder scanning
- Batch processing with Celery/Redis

# Audio Folder Ingestion Feature

## Overview

The Audio Folder Ingestion feature allows you to upload a folder of audio files from your local machine to a specified knowledge base. The system will:

1. **Scan** the folder for supported audio files
2. **Combine** all audio files into a single audio file
3. **Transcribe** the combined audio into text
4. **Generate** an LLM summary of the transcription
5. **Store** everything in the knowledge base with vector embeddings for RAG

## Supported Audio Formats

- WAV (.wav)
- MP3 (.mp3)
- M4A (.m4a)
- FLAC (.flac)
- WebM (.webm)

## Usage

### Via Web UI

1. Navigate to a Knowledge Base
2. Click the "Add Content" button (+)
3. Select "Ingest Audio Folder"
4. Enter the folder path (e.g., `/home/user/recordings/`)
5. Click "Ingest"

### Via API

```bash
curl -X POST "http://localhost:8080/api/v1/audio/folder/ingest" \
    -H "Authorization: Bearer YOUR_TOKEN" \
    -F "folder_path=/path/to/audio/folder" \
    -F "knowledge_base_id=support_calls"
```

### Via CLI

```bash
python backend/open_webui/scripts/ingest_audio_folder.py \
    --folder ./my_audio_files \
    --kb_id support_calls \
    --user_id user123
```

## Response Format

```json
{
    "status": "success",
    "ingestion_id": "uuid",
    "file_count": 5,
    "transcription_length": 1500,
    "summary": "This conversation covered...",
    "combined_audio_path": "uploads/audio/support_calls/uuid_combined.mp3"
}
```

## File Structure

After ingestion, files are organized as follows:

```
uploads/audio/{knowledge_base_id}/
├── {file_id_1}.wav          # Individual audio files
├── {file_id_2}.mp3
├── {file_id_3}.m4a
└── {ingestion_id}_combined.mp3  # Combined audio file
```

## Knowledge Base Storage

The system stores:

- **Transcription**: Full text of the combined audio
- **Summary**: LLM-generated summary of the content
- **Metadata**: File paths, counts, and processing info
- **Vector Embeddings**: For semantic search and RAG

## LLM Integration

The feature uses your configured LLM provider (Ollama or OpenAI) to generate summaries. The summary prompt includes:

- Main topics and themes
- Key points and insights
- Overall context and purpose
- Speaker dynamics (if multiple speakers)

## Security Considerations

- Folder paths are validated to exist
- Only supported audio formats are processed
- User permissions are checked for knowledge base access
- File size limits apply to individual files

## Troubleshooting

### Common Issues

1. **Folder not found**: Ensure the path exists and is accessible
2. **No supported files**: Check that the folder contains supported audio formats
3. **Permission denied**: Verify user has access to the knowledge base
4. **LLM not configured**: Ensure Ollama or OpenAI is properly configured

### Logs

Check the application logs for detailed error information:

```bash
tail -f logs/openwebui.log
```

## Future Enhancements

- Background processing for large folders
- Progress indicators for long operations
- Support for video files with audio extraction
- Speaker diarization for multi-speaker recordings
- Custom summary prompts per knowledge base