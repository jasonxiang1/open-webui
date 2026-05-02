import os
import asyncio
import pytest
import uuid
import time
from fastapi.testclient import TestClient
from open_webui.main import app  # Import your FastAPI app
from open_webui.models.files import FileModel
from dotenv import load_dotenv

load_dotenv()

# Use an absolute path for the test document
TEST_DOC_PATH = os.path.join(os.path.dirname(__file__), "test_doc.txt")
TEST_DOC_1_PATH = os.path.join(os.path.dirname(__file__), "test_doc_1.txt")
TEST_DOC_2_PATH = os.path.join(os.path.dirname(__file__), "test_doc_2.txt")
TEST_DOC_3_PATH = os.path.join(os.path.dirname(__file__), "test_doc_3.txt")

@pytest.mark.asyncio
async def test_upload_and_process_file_for_summarization():
    """
    Tests the file upload and processing pipeline to debug the generate_summary function.
    """
    client = TestClient(app)

    # Step 1: Authenticate and get a token
    # Replace with your actual test user credentials
    auth_data = {
        "username": os.getenv("TEST_USER_EMAIL"),
        "password": os.getenv("TEST_USER_PASSWORD")
    }
    # If your instance uses a different authentication method, adjust this part.
    # This example assumes a simple username/password login.
    # You might need to create a test user in your database first.
    
    # As a placeholder, we'll assume you have a way to get a valid token.
    # In a real scenario, you would make a POST request to your login endpoint.
    # For now, let's assume we can bypass auth for the test or have a known token.
    # This is a simplified example to focus on the file upload part.
    
    # A placeholder token - replace with a real one from your auth system
    headers = {
        "Authorization": os.getenv("TEST_BEARER_TOKEN")
    }

    # Step 2: Upload the test document
    with open(TEST_DOC_PATH, "rb") as f:
        files = {"file": (os.path.basename(TEST_DOC_PATH), f, "text/plain")}
        response = client.post("/api/v1/files/", files=files, headers=headers)
    
    assert response.status_code == 200
    file_id = response.json().get("id")
    assert file_id

    print(f"File uploaded successfully with ID: {file_id}")

    # Step 3: Trigger the file processing to invoke the summary generation
    process_data = {
        "file_id": file_id,
        "collection_name": f"test-summary-{file_id}"
    }
    
    # Set a breakpoint in the `generate_summary` function in your IDE
    # before running this script.
    print("Now processing the file. Set your breakpoint in generate_summary.")
    response = client.post("/api/v1/retrieval/process/file", json=process_data, headers=headers)

    assert response.status_code == 200
    response_data = response.json()
    
    print(f"Processing response: {response_data}")
    
    # You can add more assertions here to check if the summary was added
    # For example, by querying the vector DB and checking the metadata.
    # TODO: instead of checking the response_data, check the vector db query result
    assert "summary" in response_data
    print(f"Summary found in metadata: {response_data['summary']}")

# To run this test:
# 1. Make sure you have a test user and a valid token.
# 2. Replace 'your_test_token_here' with the actual token.
# 3. Set a breakpoint in the `generate_summary` function in `backend/open_webui/routers/retrieval.py`.
# 4. Run this script from your terminal using pytest:
#    pytest backend/open_webui/test/test_summarization.py

@pytest.mark.asyncio
async def test_upload_and_process_files_batch_for_summarization():
    """
    Tests the file batch upload and processing pipeline to debug the generate_summary function.
    """
    client = TestClient(app)

    # Step 1: Authenticate and get a token
    headers = {
        "Authorization": os.getenv("TEST_BEARER_TOKEN")
    }

    # Step 2: Upload multiple test documents
    test_files = [
        ("test_doc_1.txt", TEST_DOC_1_PATH),
        ("test_doc_2.txt", TEST_DOC_2_PATH),
        ("test_doc_3.txt", TEST_DOC_3_PATH)
    ]
    
    uploaded_files = []
    for filename, filepath in test_files:
        with open(filepath, "rb") as f:
            files = {"file": (filename, f, "text/plain")}
            response = client.post("/api/v1/files/", files=files, headers=headers)
        
        assert response.status_code == 200
        file_data = response.json()
        file_id = file_data.get("id")
        assert file_id
        
        # Read the file content for the batch processing
        with open(filepath, "r") as f:
            content = f.read()
        
        # Create a proper FileModel object
        file_model = FileModel(
            id=file_id,
            user_id=file_data.get("user_id"),
            filename=filename,
            data={"content": content},
            meta=file_data.get("meta", {}),
            created_at=int(time.time()),
            updated_at=int(time.time())
        )
        uploaded_files.append(file_model)
        
        print(f"File {filename} uploaded successfully with ID: {file_id}")

    # Step 3: Process the batch of files
    collection_name = f"test-batch-summary-{uuid.uuid4().hex[:8]}"
    batch_process_data = {
        "files": [file.model_dump() for file in uploaded_files],
        "collection_name": collection_name
    }
    
    print(f"Now processing {len(uploaded_files)} files in batch. Set your breakpoint in generate_summary.")
    response = client.post("/api/v1/retrieval/process/files/batch", json=batch_process_data, headers=headers)

    assert response.status_code == 200
    response_data = response.json()
    
    print(f"Batch processing response: {response_data}")
    
    # Verify the response structure
    assert "results" in response_data
    assert "errors" in response_data
    
    results = response_data["results"]
    errors = response_data["errors"]
    
    # Check that all files were processed successfully
    assert len(results) == len(uploaded_files)
    assert len(errors) == 0
    
    # Verify each file was processed successfully
    for result in results:
        assert result["status"] == "completed"
        assert "file_id" in result
        print(f"File {result['file_id']} processed successfully with status: {result['status']}")
    
    # Verify that summaries were generated for all files
    # You can add more specific assertions here based on your expected behavior
    print(f"All {len(results)} files processed successfully in batch")
    print(f"Collection name: {collection_name}")
    
    # Optional: Query the vector database to verify documents were stored
    # This would require additional API calls to verify the data was actually stored
    # and that summaries are accessible in the metadata

# To run this test:
# 1. Make sure you have a test user and a valid token.
# 2. Set environment variables TEST_USER_EMAIL, TEST_USER_PASSWORD, and TEST_BEARER_TOKEN.
# 3. Set a breakpoint in the `generate_summary` function in `backend/open_webui/routers/retrieval.py`.
# 4. Run this script from your terminal using pytest:
#    pytest backend/open_webui/test/test_summarization.py::test_upload_and_process_files_batch_for_summarization
