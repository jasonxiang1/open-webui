# OpenWebUI Knowledge Base Functionality

## 1. Overview

The knowledge base functionality in OpenWebUI allows users to augment the capabilities of Large Language Models (LLMs) by providing them with their own data. This is achieved through a technique called **Retrieval-Augmented Generation (RAG)**.

Users can upload documents, text, and even audio files to create personalized knowledge bases. When a user asks a question in a chat session that is linked to a knowledge base, the system first searches for relevant information within that knowledge base. It then uses this retrieved information, along with the LLM's general knowledge, to generate a more accurate and context-aware answer.

## 2. The RAG Pipeline

The functionality is built on a classic RAG pipeline, which consists of the following steps:

### 2.1. Data Ingestion and Processing

- **Document Loading:** The system can ingest various file formats, including PDFs, Markdown files, Word documents, and audio files, using a flexible document loader architecture.
- **Text Chunking:** The content of the documents, now including the document's summary prepended to each chunk, is intelligently split into smaller, manageable chunks. This process aims to keep related sentences and paragraphs together to preserve semantic context, while also providing overall document context.

### 2_2. Embedding

- Each text chunk is converted into a numerical representation called an "embedding" using a specialized embedding model. These embeddings capture the semantic meaning of the text.
- OpenWebUI supports various embedding models, including those from Ollama and OpenAI, which can be configured by the administrator.

### 2.3. Storage

- The text chunks and their corresponding embeddings are stored in a specialized **vector database**.
- OpenWebUI uses **ChromaDB** by default but also supports other vector stores like Milvus and Pinecone, providing flexibility for different deployment scales.

### 2.4. Retrieval

- When a user submits a query in a chat, the query is also converted into an embedding.
- The system searches the vector database to find the text chunks with embeddings that are most semantically similar to the query's embedding.

### 2.5. Augmentation and Generation

- The retrieved text chunks (which now include the document's summary prepended to each chunk) are injected into the prompt that is sent to the LLM, along with the user's original question.
- The LLM then generates a more accurate and context-aware answer based on both its pre-trained knowledge and the specific, contextual information provided from the user's knowledge base, benefiting from the enhanced context within each chunk.

## 3. Core Features

- **Knowledge Base Management:** Users can create and manage multiple knowledge bases through the "Knowledge" section in the OpenWebUI workspace.
- **Document Upload:** Users can easily upload files from their local machine.
- **Web Search Integration:** Knowledge bases can be augmented with information from the web, with support for various search providers.
- **Citations:** The system provides citations in its responses, allowing users to trace information back to the original source documents.
- **Full Context Mode:** For smaller documents, users can opt to inject the entire document content into the prompt, bypassing the chunking and retrieval process. This is useful for tasks like summarization.
- **Reranking:** OpenWebUI supports external reranking services to improve the relevance of retrieved documents, leading to more accurate answers.

## 4. Backend Implementation

The core backend logic for the knowledge base functionality resides in the `backend/open_webui/retrieval/` directory. API endpoints are defined in `backend/open_webui/routers/`.

### 4.1. Viewing, Editing, and Saving Transcripts

A key feature of the knowledge base is the ability to view and edit the text content (transcript) and summary of any file.

#### Viewing a Transcript and Summary

- **Endpoint:** `GET /api/v1/files/{id}`
- **Handler:** `get_file_by_id()` in `backend/open_webui/routers/files.py`
- **Process:**
    1.  The backend authenticates the user and verifies read access to the file.
    2.  It retrieves the file's record from the database.
    3.  The stored transcript and summary (extracted during the initial upload or edited by the user) are returned to the frontend for display.

#### Editing and Saving a Transcript and Summary

- **Endpoint:** `POST /api/v1/files/{id}/data/content/update`
- **Handler:** `update_file_data_content_by_id()` in `backend/open_webui/routers/files.py`
- **Process:**
    1.  The backend authenticates the user and verifies write access.
    2.  It receives the updated transcript and summary from the frontend.
    3.  Crucially, the backend **re-processes** the file by passing the new content and summary to the `process_file` function in `backend/open_webui/routers/retrieval.py`. This involves:
        -   Splitting the updated transcript into new chunks.
        -   Generating new vector embeddings for these chunks.
        -   Replacing the old embeddings for the file with the new ones in the vector database.
    4.  The file record in the main database is updated with the new transcript and summary.

This re-indexing step ensures that the knowledge base remains consistent and that any user corrections or edits are immediately available for future RAG-based queries.

#### Generating a Summary

- **Endpoint:** `POST /api/v1/files/{id}/generate-summary`
- **Handler:** `generate_summary_by_id()` in `backend/open_webui/routers/files.py`
- **Process:**
    1.  The backend authenticates the user and verifies write access.
    2.  It retrieves the file's content from the database.
    3.  It generates a summary using the `generate_summary` function from `backend/open_webui/routers/retrieval.py`.
    4.  The file record in the main database is updated with the new summary.
    5.  The new summary is returned to the frontend.

## 5. Frontend Implementation

The user interface components for managing knowledge bases are located in the `src/lib/components/workspace/Knowledge/` directory.

The `src/lib/components/workspace/Knowledge/KnowledgeBase.svelte` component is responsible for displaying the knowledge base. When a user clicks on a file, this component calls the `getFileById` function from `src/lib/apis/files/index.ts`, which in turn makes a `GET` request to the `/api/v1/files/{id}` endpoint.

The component now displays both the summary and the content of the selected file. If no summary is present, a placeholder is displayed, and the user can add a summary and save it. A "Generate Summary" button is also available to automatically generate a summary for the file content.

## 6. Configuration

The RAG pipeline is highly configurable via environment variables, which are consolidated in `backend/open_webui/config.py`. These settings, prefixed with `RAG_`, allow administrators to customize everything from the embedding models and text splitter to web search providers and rerankers.