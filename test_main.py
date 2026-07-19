import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from main import app, get_session, Ticket # Assumes your API code is in main.py
from database import get_session, engine # Import what you need from your new file
# ==========================================
# 1. TESTING SETUP & FIXTURES (The Sandbox)
# ==========================================

# Create an isolated, in-memory database just for our test runs
test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

@pytest.fixture(name="session")
def session_fixture():
    """Creates tables before tests run and drops them afterward."""
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session
    SQLModel.metadata.drop_all(test_engine)

@pytest.fixture(name="client")
def client_fixture(session: Session):
    """Overrides the real database session dependency with our test session."""
    def get_session_override():
        return session
    
    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

# ==========================================
# 2. THE AUTOMATED TEST CASES
# ==========================================

def test_create_ticket(client: TestClient):
    """Verify that a valid ticket payload successfully creates a ticket."""
    payload = {
        "customer_name": "Jane Doe",
        "email": "jane.doe@example.com",
        "issue": "Cannot log into the customer portal",
        "priority": "high"
    }
    response = client.post("/tickets", json=payload)
    
    assert response.status_code == 201
    data = response.json()
    assert data["customer_name"] == "Jane Doe"
    assert data["status"] == "open"
    assert "id" in data  # Ensure our UUID was system-generated

def test_create_ticket_invalid_priority(client: TestClient):
    """Verify that an invalid priority rejects the request with a 400 Bad Request."""
    payload = {
        "customer_name": "Jane Doe",
        "email": "jane.doe@example.com",
        "issue": "Cannot log into the portal",
        "priority": "ultra-critical"  # Invalid option
    }
    response = client.post("/tickets", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Priority must be 'low', 'medium', or 'high'."

def test_get_all_tickets(client: TestClient):
    """Verify we can fetch the entire list of tickets."""
    # Add a mock ticket first
    client.post("/tickets", json={
        "customer_name": "Bob Smith",
        "email": "bob@example.com",
        "issue": "API webhook timeout error",
        "priority": "medium"
    })
    
    print(app.routes)
    response = client.get("/tickets")
    assert response.status_code == 200
    assert len(response.json()) == 2

def test_patch_ticket_status(client: TestClient):
    """Verify partial updates (PATCH) successfully modify status without breaking other fields."""
    # 1. Create a ticket
    created = client.post("/tickets", json={
        "customer_name": "Alice Green",
        "email": "alice@example.com",
        "issue": "Salesforce sync failing",
        "priority": "low"
    }).json()
    
    ticket_id = created["id"]
    
    # 2. Update just the status
    update_payload = {"status": "in-progress"}
    response = client.patch(f"/tickets/{ticket_id}", json=update_payload)
    
    assert response.status_code == 200
    updated_data = response.json()
    assert updated_data["status"] == "in-progress"
    assert updated_data["customer_name"] == "Alice Green"  # Should remain unchanged

def test_delete_ticket(client: TestClient):
    """Verify a ticket can be permanently removed from the system."""
    created = client.post("/tickets", json={
        "customer_name": "Charlie Brown",
        "email": "charlie@example.com",
        "issue": "Jira ticket field mapping bug",
        "priority": "low"
    }).json()
    
    ticket_id = created["id"]
    
    # Delete it
    delete_response = client.delete(f"/tickets/{ticket_id}")
    assert delete_response.status_code == 204
    
    # Verify it's truly gone
    get_response = client.get(f"/tickets/{ticket_id}")
    assert get_response.status_code == 404
    
def test_read_main(client):
        # Replace "/your-endpoint" with an actual endpoint from your main.py
    response = client.get("/tickets") 
    assert response.status_code == 200