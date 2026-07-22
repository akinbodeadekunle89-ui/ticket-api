import asyncio
import hmac
import hashlib
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status, Depends, BackgroundTasks
from pydantic import BaseModel, EmailStr, Field
import httpx
from sqlalchemy.orm import Session

# Import your database models and session dependency
from database import get_session, engine, TicketModel

# ==========================================
# 1. LOGGING & CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("api_activity.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("enterprise-integration-api")

WEBHOOK_URL = "https://webhook.site/e1b7bb92-bf8d-42b1-86f4-6c338de6c08d"
WEBHOOK_SECRET = "super_secret_signing_key_12345"  # Secret key for HMAC signing

# ==========================================
# 2. FASTAPI APP INSTANTIATION
# ==========================================
app = FastAPI(
    title="Enterprise Ticket & Webhook Integration Service",
    description="Production-ready REST API featuring non-blocking background tasks, HMAC security, and retry resilience.",
    version="1.0.0"
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

# ==========================================
# 4. UTILITIES (HMAC Signing)
# ==========================================
def generate_hmac_signature(payload_bytes: bytes, secret: str) -> str:
    """Generates a SHA-256 HMAC signature to ensure payload integrity."""
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

# ==========================================
# 5. RESILIENT BACKGROUND TASK WORKER
# ==========================================
async def send_webhook_with_retry(payload: dict, max_retries: int = 3):
    """
    Background worker that dispatches webhooks with HMAC signatures
    and exponential backoff retry handling.
    """
    import json
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
                logger.info(f"Webhook delivered successfully on attempt {attempt}! Status: {response.status_code}")
                return
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning(f"Attempt {attempt} failed due to: {exc}")
                if attempt < max_retries:
                    backoff_delay = 2 ** attempt  # Exponential backoff: 2s, 4s, 8s...
                    logger.info(f"Retrying in {backoff_delay} seconds...")
                    await asyncio.sleep(backoff_delay)
                else:
                    logger.error(f"Failed to deliver webhook after {max_retries} attempts. Flagging for manual audit.")

# ==========================================
# 6. REST API ENDPOINTS
# ==========================================
@app.get("/health", status_code=status.HTTP_200_OK, tags=["Monitoring"])
def health_check():
    """Service health check endpoint for load balancers and monitoring tools."""
    return {"status": "healthy", "service": "ticket-integration-api", "version": "1.0.0"}

@app.post("/tickets", response_model=TicketResponse, status_code=status.HTTP_201_CREATED, tags=["Tickets"])
async def create_ticket(
    ticket_in: TicketCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    logger.info(f"Processing ticket creation request for: {ticket_in.customer_name}")

    normalized_priority = ticket_in.priority.lower().strip()
    if normalized_priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=400, detail="Priority must be 'low', 'medium', or 'high'.")

    # 1. Persist record to Database
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

    # 2. Prepare payload for sync
    payload = {
        "event": "ticket.created",
        "ticket_id": db_ticket.id,
        "customer": db_ticket.customer_name,
        "email": db_ticket.email,
        "issue": db_ticket.issue,
        "priority": db_ticket.priority,
        "status": db_ticket.status
    }

    # 3. Offload webhook sync to background execution thread
    background_tasks.add_task(send_webhook_with_retry, payload)

    return db_ticket

@app.get("/tickets", response_model=List[TicketResponse], tags=["Tickets"])
def get_all_tickets(session: Session = Depends(get_session)):
    return session.query(TicketModel).all()

@app.get("/tickets/{ticket_id}", response_model=TicketResponse, tags=["Tickets"])
def get_ticket_by_id(ticket_id: int, session: Session = Depends(get_session)):
    ticket = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket #{ticket_id} not found.")
    return ticket

@app.patch("/tickets/{ticket_id}", response_model=TicketResponse, tags=["Tickets"])
def update_ticket(ticket_id: int, ticket_update: TicketUpdate, session: Session = Depends(get_session)):
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
def delete_ticket(ticket_id: int, session: Session = Depends(get_session)):
    ticket = session.query(TicketModel).filter(TicketModel.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket #{ticket_id} not found.")

    session.delete(ticket)
    session.commit()
    return None