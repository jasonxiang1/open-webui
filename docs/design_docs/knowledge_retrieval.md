# Knowledge Base Retrieval and Prompt Augmentation

## 1. Overview

This document details the end-to-end process of how OpenWebUI retrieves information from a knowledge base and augments the prompt sent to a Large Language Model (LLM) during a chat session. This process is a specific implementation of the Retrieval-Augmented Generation (RAG) pattern.

## 2. The High-Level RAG Query Pipeline

When a user sends a message in a chat linked to a knowledge base, the following sequence of events is triggered:

1.  **Query Embedding**: The user's message is converted into a numerical vector (embedding) using the configured embedding model.
2.  **Semantic Search**: The system searches the vector database (e.g., ChromaDB) to find the most semantically similar text chunks from the source documents. These retrieved chunks now inherently contain the document's summary, providing richer context.
3.  **Prompt Augmentation**: The retrieved text chunks are then formatted and injected into a system prompt, along with the user's original query.
4.  **LLM Generation**: This final, context-rich prompt is sent to the selected LLM to generate a response.

## 3. Code-Level Deep Dive

The implementation of the RAG query pipeline is distributed across several key files in the backend, primarily within the `utils` directory.

### Step 1: API Endpoint (`main.py`)

The process is initiated by a call to the chat completions endpoint.

-   **File**: `backend/open_webui/main.py`
-   **Endpoint**: `@app.post("/api/chat/completions")`
-   **Action**: This endpoint receives the chat request and calls `process_chat_payload` to prepare the data for the LLM.

### Step 2: Payload Orchestration (`middleware.py`)

This is where the core RAG logic is orchestrated.

-   **File**: `backend/open_webui/utils/middleware.py`
-   **Primary Function**: `process_chat_payload(...)`

This function coordinates a series of handlers. For RAG, the key steps are:

1.  It calls `chat_completion_files_handler(...)` within the same file.
2.  `chat_completion_files_handler` is responsible for managing any files attached to the chat, including knowledge base documents. It calls `get_sources_from_items(...)` (from `backend/open_webui/retrieval/utils.py`) to perform the vector search and retrieve the relevant document chunks, which are returned as a list of `sources`.
3.  Back in `process_chat_payload`, the code iterates through these `sources`. Each chunk is wrapped in `<source>` tags, which include an `id` for citations and the `name` of the document. These are compiled into a single `context_string`.

```python
# Snippet from backend/open_webui/utils/middleware.py

# If context is not empty, insert it into the messages
if len(sources) > 0:
    context_string = ""
    citation_idx_map = {}

    for source in sources:
        # ... (logic to handle tool results vs. documents) ...
        if "document" in source and not is_tool_result:
            for document_text, document_metadata in zip(
                source["document"], source["metadata"]
            ):
                # ... (logic to get source_name and source_id) ...
                if source_id not in citation_idx_map:
                    citation_idx_map[source_id] = len(citation_idx_map) + 1

                context_string += (
                    f'<source id="{citation_idx_map[source_id]}"'
                    + (f' name="{source_name}"' if source_name else "")
                    + f">{document_text}</source>\n"
                )

    context_string = context_string.strip()
    prompt = get_last_user_message(form_data["messages"])

    # ...

    # Call the templating function
    final_prompt = rag_template(
        request.app.state.config.RAG_TEMPLATE, context_string, prompt
    )

    # Add the final prompt to the message list
    form_data["messages"] = add_or_update_system_message(
        final_prompt,
        form_data["messages"],
    )
```

### 3.1. Document Chunking with Summary (`retrieval.py`)

A significant enhancement has been implemented in the document chunking process to ensure that each chunk retains the overall context of its source document. The document's summary is now prepended to the content of each chunk before it is embedded into the vector database. This improves the relevance and contextual understanding of retrieved information during RAG.

-   **File**: `backend/open_webui/routers/retrieval.py`
-   **Function**: `save_docs_to_vector_db(...)`
-   **Action**: After the document content is split into chunks by the configured text splitter, the document's summary (if available in the metadata) is prepended to the `page_content` of each individual chunk.

```python
# Snippet from backend/open_webui/routers/retrieval.py (within save_docs_to_vector_db)

    if split:
        # ... (existing text splitter logic for character, token, or markdown_header) ...

        # NEW LOGIC: Prepend summary to each chunk
        if metadata and "summary" in metadata and metadata["summary"]:
            summary_text = metadata["summary"]
            for doc in docs: # 'docs' here refers to the list of Document chunks
                doc.page_content = f"Summary: {summary_text}\n\n{doc.page_content}"

    # ... (rest of the function, including embedding and insertion into vector DB) ...
```

### Step 3: Final Prompt Assembly (`task.py`)

The final step is to inject the assembled context and the user's query into the master prompt template.

-   **File**: `backend/open_webui/utils/task.py`
-   **Function**: `rag_template(template: str, context: str, query: str)`
-   **Action**: This function takes the `context_string` and the `query` and performs a string replacement on the master RAG template (defined by the `RAG_TEMPLATE` environment variable).

```python
# Snippet from backend/open_webui/utils/task.py

def rag_template(template: str, context: str, query: str):
    if template.strip() == "":
        template = DEFAULT_RAG_TEMPLATE

    # ... (other template replacements) ...

    template = template.replace("[context]", context)
    template = template.replace("{{CONTEXT}}", context)
    template = template.replace("[query]", query)
    template = template.replace("{{QUERY}}", query)

    return template
```

## 4. Summary of Flow

1.  **Request Start**: `main.py` -> `/api/chat/completions`
2.  **Orchestration**: `utils/middleware.py` -> `process_chat_payload`
3.  **Retrieval**: `process_chat_payload` -> `chat_completion_files_handler` -> `get_sources_from_items`
4.  **Context Assembly**: `process_chat_payload` assembles the `context_string` from retrieved sources.
5.  **Template Injection**: `process_chat_payload` calls `rag_template` in `utils/task.py`.
6.  **Final Prompt**: `rag_template` injects the context and query into the final prompt.
7.  **LLM Call**: The augmented message list is sent to the LLM for generation.
