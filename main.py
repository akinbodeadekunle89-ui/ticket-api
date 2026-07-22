import asyncio
import hmac
import hashlib
import json
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status, Depends, BackgroundTasks, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, EmailStr, Field
import httpx
from sqlalchemy.orm import Session

# Import settings, database models, and session dependency
from config import settings
from database import get_session, TicketModel

# ==========================================
# 1. SETTINGS & CONFIGURATION
# ==========================================
WEBHOOK_SECRET = settings.webhook_secret
API_KEY_SECRET = settings.api_key_secret
WEBHOOK_URL = settings.webhook_url

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("api_activity.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("enterprise-integration-api")

# In-memory store for idempotency keys
PROCESSED_EVENT_IDS = set()

# ==========================================
# 2. OPENAPI TAGS & FASTAPI INSTANTIATION
# ==========================================
tags_metadata = [
    {
        "name": "Monitoring",
        "description": "Health check and diagnostic endpoints for operational uptime.",
    },
    {
        "name": "Tickets",
        "description": "Core CRUD operations for customer support ticket management.",
    },
    {
        "name": "Inbound Webhooks",
        "description": "Receives and validates incoming event webhooks from external platforms (e.g. Jira, Salesforce).",
    },
]

app = FastAPI(
    title=settings.app_name,
    description="Production REST API featuring non-blocking background tasks, HMAC security, retry resilience, and inbound webhook processing.",
    version="1.2.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Setup (Allows browser frontends to interact with this API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 3. PYDANTIC SCHEMAS
# ==========================================
class TicketCreate(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    issue: str = Field(..., min_length=5)
    priority: str = Field(default="low")

class TicketResponse(TicketCreate):
    id: int
    status: str = "open"

    class Config:
        from_attributes = True

class TicketUpdate(BaseModel):
    issue: Optional[str] = Field(None, min_length=5)
    priority: Optional[str] = None
    status: Optional[str] = None

class InboundWebhookPayload(BaseModel):
    event_id: str
    event_type: str
    customer: str
    email: EmailStr
    issue: str
    priority: str = "low"

# ==========================================
# 4. UTILITIES & SECURITY DEPENDENCIES
# ==========================================
# Enables Swagger UI "Authorize" button for X-API-Key header authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def generate_hmac_signature(payload_bytes: bytes, secret: str) -> str:
    """Generates a SHA-256 HMAC signature to ensure payload integrity."""
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

def verify_api_key(x_api_key: Optional[str] = Depends(api_key_header)):
    """Verifies that incoming requests contain a valid internal API key."""
    if not x_api_key or x_api_key != API_KEY_SECRET:
        logger.warning("Unauthorized access attempt with invalid or missing API key.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key"
        )
    return x_api_key

# ==========================================
# 5. RESILIENT BACKGROUND TASK WORKER
# ==========================================
async def send_webhook_with_retry(payload: dict, max_retries: int = 3):
    """Background worker that dispatches webhooks with HMAC signatures and exponential backoff retries."""
    payload_json = json.dumps(payload)
    signature = generate_hmac_signature(payload_json.encode("utf-8"), WEBHOOK_SECRET)

    headers = {
        "Content-Type": "application/json",
        "X-Signature-SHA256": signature
    }

    async with httpx.AsyncClient() as client:
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Webhook delivery attempt {attempt}/{max_retries}...")
                response = await client.post(WEBHOOK_URL, content=payload_json, headers=headers, timeout=5.0)
                response.raise_for_status()
                logger.info(f"Webhook delivered successfully! Status: {response.status_code}")
                return
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning(f"Attempt {attempt} failed due to: {exc}")
                if attempt < max_retries:
                    backoff_delay = 2 ** attempt
                    await asyncio.sleep(backoff_delay)
                else:
                    logger.error(f"Failed to deliver webhook after {max_retries} attempts.")

# ==========================================
# 6. REST API ENDPOINTS
# ==========================================
@app.get("/health", status_code=status.HTTP_200_OK, tags=["Monitoring"])
def health_check():
    """Service health check endpoint for monitoring systems."""
    return {"status": "healthy", "service": "ticket-integration-api", "version": "1.2.0"}

@app.post("/tickets", response_model=TicketResponse, status_code=status.HTTP_201_CREATED, tags=["Tickets"])
async def create_ticket(
    ticket_in: TicketCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    logger.info(f"Processing ticket creation for: {ticket_in.customer_name}")

    normalized_priority = ticket_in.priority.lower().strip()
    if normalized_priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=400, detail="Priority must be 'low', 'medium', or 'high'.")

    db_ticket = TicketModel(
        customer_name=ticket_in.customer_name,
        email=ticket_in.email,
        issue=ticket_in.issue,
        priority=normalized_priority,
        status="open"
    )
    session.add(db_ticket)
    session.commit()
    session.refresh(db_ticket)

    payload = {
        "event": "ticket.created",
        "ticket_id": db_ticket.id,
        "customer": db_ticket.customer_name,
        "email": db_ticket.email,
        "issue": db_ticket.issue,
        "priority": db_ticket.priority,
        "status": db_ticket.status
    }

    background_tasks.add_task(send_webhook_with_retry, payload)
    return db_ticket

@app.get("/tickets", response_model=List[TicketResponse], tags=["Tickets"])
def get_all_tickets(session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    return session.query(TicketModel).all()

@app.get("/tickets/{ticket_id}", response_model=TicketResponse, tags=["Tickets"])
def get_ticket_by_id(ticket_id: int, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    ticket = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket #{ticket_id} not found.")
    return ticket

@app.patch("/tickets/{ticket_id}", response_model=TicketResponse, tags=["Tickets"])
def update_ticket(ticket_id: int, ticket_update: TicketUpdate, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    ticket = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket #{ticket_id} not found.")

    update_data = ticket_update.model_dump(exclude_unset=True)
    if not update_data:
        return ticket

    if "priority" in update_data:
        norm = update_data["priority"].lower().strip()
        if norm not in ["low", "medium", "high"]:
            raise HTTPException(status_code=400, detail="Invalid priority value.")
        update_data["priority"] = norm

    if "status" in update_data:
        norm = update_data["status"].lower().strip()
        if norm not in ["open", "in-progress", "resolved", "closed"]:
            raise HTTPException(status_code=400, detail="Invalid status value.")
        update_data["status"] = norm

    for key, value in update_data.items():
        setattr(ticket, key, value)

    session.commit()
    session.refresh(ticket)
    return ticket

@app.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Tickets"])
def delete_ticket(ticket_id: int, session: Session = Depends(get_session), api_key: str = Depends(verify_api_key)):
    ticket = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket #{ticket_id} not found.")

    session.delete(ticket)
    session.commit()
    return None

# ==========================================
# 7. INBOUND WEBHOOK RECEIVER
# ==========================================
@app.post("/webhooks/incoming", status_code=status.HTTP_200_OK, tags=["Inbound Webhooks"])
async def receive_inbound_webhook(
    request: Request,
    payload: InboundWebhookPayload,
    x_signature_sha256: str = Header(...),
    session: Session = Depends(get_session)
):
    logger.info(f"Received inbound webhook event '{payload.event_type}' with ID: {payload.event_id}")

    if payload.event_id in PROCESSED_EVENT_IDS:
        logger.warning(f"Duplicate event detected: {payload.event_id}. Skipping.")
        return {"status": "skipped", "message": "Duplicate event ID ignored."}

    body_bytes = await request.body()
    computed_signature = generate_hmac_signature(body_bytes, WEBHOOK_SECRET)
    
    if not hmac.compare_digest(computed_signature, x_signature_sha256):
        logger.error("Inbound webhook HMAC signature mismatch!")
        raise HTTPException(status_code=401, detail="Invalid HMAC signature.")

    db_ticket = TicketModel(
        customer_name=payload.customer,
        email=payload.email,
        issue=f"[{payload.event_type.upper()}] {payload.issue}",
        priority=payload.priority,
        status="open"
    )
    session.add(db_ticket)
    session.commit()

    PROCESSED_EVENT_IDS.add(payload.event_id)
    return {"status": "success", "event_id": payload.event_id, "ticket_id": db_ticket.id}