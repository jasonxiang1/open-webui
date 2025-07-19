import os
import asyncio
import pytest
from fastapi.testclient import TestClient
from open_webui.main import app  # Import your FastAPI app
from dotenv import load_dotenv

load_dotenv()

# Use an absolute path for the test document
TEST_DOC_PATH = os.path.join(os.path.dirname(__file__), "test_doc.txt")

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
