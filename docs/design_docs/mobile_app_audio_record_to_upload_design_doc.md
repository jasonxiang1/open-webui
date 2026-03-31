Mobile App: Audio Note Upload to OpenWebUI
1. Overview
This document outlines the design and architecture for a new feature in the mobile application that allows users to record audio notes and upload them directly into a specified knowledge dataset within their local OpenWebUI instance. This enables users to easily capture thoughts, memos, or meeting notes on the go and later use their local Large Language Model (LLM) via OpenWebUI to query, summarize, or transcribe this audio content.

The feature consists of three main parts:

An in-app audio recording interface.

A mechanism to manage and select recorded audio files.

An API client to handle the authenticated upload of audio files to the OpenWebUI server's document API.

2. Goals and Objectives
Goal: To seamlessly integrate mobile audio capture with the OpenWebUI knowledge base.

Objectives:

Provide a simple, one-tap interface to start and stop audio recording.

Securely and reliably upload the recorded audio file to the user's OpenWebUI server over the local network.

Provide clear feedback to the user regarding the status of the upload (e.g., in-progress, success, failure).

Ensure the uploaded audio is immediately available for use as a document source in OpenWebUI chats (e.g., Summarize #my-note-2025-08-02.m4a).

3. System Architecture and Data Flow
The feature operates within the existing mobile app and local network environment.

3.1. High-Level Architecture
Mobile App (Audio File Creation): The user records an audio note on their mobile device. The app saves this as an audio file (e.g., .m4a, .mp3) to the device's local storage.

Mobile App to OpenWebUI Server (File Upload): The mobile app sends the audio file via an authenticated HTTP POST request to the OpenWebUI server, which is running on the local network at a specific IP address and port.

OpenWebUI Server to Document Store (Ingestion): The OpenWebUI server receives the file and processes it, adding it to its Vector DB / Document Store.

OpenWebUI Server and Ollama Server (LLM Interaction): The OpenWebUI server communicates with the Ollama Server for all LLM-related tasks, such as summarizing or answering questions about the newly uploaded document when prompted by the user.

3.2. Data Flow
Record: The user records an audio note within the mobile app. The app saves the recording as a file (e.g., note-20250802-1125.m4a) to the device's local storage.

Upload: The user initiates an upload. The mobile app constructs an HTTP POST request with multipart/form-data.

The request is sent to the OpenWebUI server's /api/v1/documents endpoint.

An Authorization: Bearer <API_KEY> header is included for authentication.

The request body contains the audio file and the target collection_name (e.g., "mobile-notes").

Process: The OpenWebUI server receives the request, authenticates the API key, and ingests the audio file into its document store, making it available for RAG (Retrieval-Augmented Generation) operations.

Query: The user can then reference the uploaded audio file in a chat prompt within OpenWebUI or the mobile app (which communicates with the Ollama API) to interact with its content.

4. Feature Components
4.1. Mobile App Components
4.1.1. User Interface (UI)
Recording Button: A prominent button on the main chat interface to start/stop recording.

Recording Indicator: A visual timer or microphone icon to show that recording is active.

Upload Status: A temporary toast notification or a status icon next to the message to indicate "Uploading...", "Upload Complete", or "Upload Failed".

Settings Screen: A new section in the app's settings for configuring the OpenWebUI server address (IP:Port) and the secret API Key.

4.1.2. Audio Recorder Module
Utilizes the device's native audio recording APIs (or a cross-platform library like expo-av).

Format: Records in a common format like M4A (for iOS) or MP3 to ensure compatibility.

File Naming: Generates a unique, descriptive filename for each recording (e.g., audio-note-YYYY-MM-DD-HH-mm-ss.m4a).

4.1.3. OpenWebUI API Client
A dedicated module responsible for all communication with the OpenWebUI server.

uploadAudioNote(fileUri, fileName) function:

Constructs a FormData object.

Appends the file, filename, and collection name.

Executes the fetch request with the correct headers.

Handles response parsing and error management.

4.2. Server-Side Components (OpenWebUI)
/api/v1/documents Endpoint: The existing API endpoint for document ingestion. No changes are required on the server side, as we are using an existing, stable API.

5. API Interaction Details
POST /api/v1/documents
URL: http://<user_configured_ip>:<user_configured_port>/api/v1/documents

Method: POST

Headers:

Authorization: Bearer <user_configured_api_key>

Content-Type: multipart/form-data; boundary=... (set automatically by the fetch client)

Body (multipart/form-data):

file: The binary content of the audio file.

collection_name: A string representing the target dataset. This will be hardcoded initially to mobile-notes but can be made configurable later.

Success Response (200 OK):

{
  "message": "Document created successfully",
  "filename": "audio-note-2025-08-02-11-25-30.m4a"
}

Error Response (401 Unauthorized):

{
  "detail": "Unauthorized"
}

6. Security Considerations
API Key Storage: The OpenWebUI API key is sensitive. It will be stored on the device using a secure storage mechanism (e.g., iOS Keychain, Android Keystore/EncryptedSharedPreferences). It must not be stored in plain text.

Network: All communication happens on the user's local Wi-Fi network. While this is inherently more secure than the public internet, users should be advised to use a trusted network. The app will communicate over HTTP, as setting up HTTPS with valid certificates on a local network is complex for non-technical users.

7. Future Enhancements
Background Uploads: Allow uploads to continue if the user navigates away from the app.

Automatic Transcription: After a successful upload, automatically trigger a call to the Ollama API to transcribe the audio and save the text as a separate document or as metadata.

Audio Library: A dedicated screen in the app to view, play back, and manage past recordings and their upload status.

Configurable Collection: Allow users to select which OpenWebUI collection to upload to from within the app.
