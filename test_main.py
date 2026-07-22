import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

import database
from database import TicketModel, get_session
from main import app, API_KEY_SECRET, WEBHOOK_SECRET

# ==========================================
# 1. FIXED IN-MEMORY TEST DATABASE SETUP
# StaticPool forces SQLite to share the SAME memory database across sessions
# ==========================================
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

AUTH_HEADERS = {"X-API-Key": API_KEY_SECRET}

@pytest.fixture(name="session")
def session_fixture():
    """Creates tables once per test, yields a session, and clears tables after."""
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session
    SQLModel.metadata.drop_all(test_engine)

@pytest.fixture(name="client")
def client_fixture(session: Session):
    """Overrides the real DB dependency so FastAPI uses our test session."""
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

# ==========================================
# 2. AUTOMATED TEST CASES
# ==========================================

def test_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_create_ticket_unauthorized(client: TestClient):
    payload = {
        "customer_name": "Jane Doe",
        "email": "jane.doe@example.com",
        "issue": "Cannot log into the customer portal",
        "priority": "high"
    }
    response = client.post("/tickets", json=payload)
    assert response.status_code == 401

def test_create_ticket_success(client: TestClient):
    payload = {
        "customer_name": "Jane Doe",
        "email": "jane.doe@example.com",
        "issue": "Cannot log into the customer portal",
        "priority": "high"
    }
    response = client.post("/tickets", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201
    data = response.json()
    assert data["customer_name"] == "Jane Doe"
    assert data["status"] == "open"
    assert "id" in data

def test_create_ticket_invalid_priority(client: TestClient):
    payload = {
        "customer_name": "Jane Doe",
        "email": "jane.doe@example.com",
        "issue": "Cannot log into the portal",
        "priority": "ultra-critical"
    }
    response = client.post("/tickets", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"] == "Priority must be 'low', 'medium', or 'high'."

def test_get_all_tickets(client: TestClient):
    client.post("/tickets", json={
        "customer_name": "Bob Smith",
        "email": "bob@example.com",
        "issue": "API webhook timeout error",
        "priority": "medium"
    }, headers=AUTH_HEADERS)
    
    response = client.get("/tickets", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_patch_ticket_status(client: TestClient):
    created = client.post("/tickets", json={
        "customer_name": "Alice Green",
        "email": "alice@example.com",
        "issue": "Salesforce sync failing",
        "priority": "low"
    }, headers=AUTH_HEADERS).json()
    
    ticket_id = created["id"]
    
    update_payload = {"status": "in-progress"}
    response = client.patch(f"/tickets/{ticket_id}", json=update_payload, headers=AUTH_HEADERS)
    
    assert response.status_code == 200
    updated_data = response.json()
    assert updated_data["status"] == "in-progress"

def test_delete_ticket(client: TestClient):
    created = client.post("/tickets", json={
        "customer_name": "Charlie Brown",
        "email": "charlie@example.com",
        "issue": "Jira ticket field mapping bug",
        "priority": "low"
    }, headers=AUTH_HEADERS).json()
    
    ticket_id = created["id"]
    
    delete_response = client.delete(f"/tickets/{ticket_id}", headers=AUTH_HEADERS)
    assert delete_response.status_code == 204
    
    get_response = client.get(f"/tickets/{ticket_id}", headers=AUTH_HEADERS)
    assert get_response.status_code == 404

def test_inbound_webhook_processing_and_idempotency(client: TestClient):
    payload = {
        "event_id": "evt_test_99999",
        "event_type": "jira_case_created",
        "customer": "External System User",
        "email": "system@external.com",
        "issue": "Auto-synced case from Jira integration",
        "priority": "medium"
    }
    
    raw_body_bytes = json.dumps(payload, separators=(',', ':')).encode("utf-8")
    
    signature = hmac.new(
        key=WEBHOOK_SECRET.encode("utf-8"),
        msg=raw_body_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

    headers = {
        "X-Signature-SHA256": signature,
        "Content-Type": "application/json"
    }

    response = client.post("/webhooks/incoming", content=raw_body_bytes, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    dup_response = client.post("/webhooks/incoming", content=raw_body_bytes, headers=headers)
    assert dup_response.status_code == 200
    assert dup_response.json()["status"] == "skipped"