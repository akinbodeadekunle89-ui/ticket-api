import logging

import uuid
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, Field
from database import get_session, engine, Session # Import what you need from your new ficle
import httpx
# ==========================================
# 1. LOGGING CONFIGURATION (The "Flight Recorder")
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("api_activity.log"),  # Saves logs to a physical file for tracing
        logging.StreamHandler()                  # Outputs logs to your console in real-time
    ]
)
logger = logging.getLogger("ticket-api")

logger.info("Initializing Ticket API application...")

# ==========================================
# 2. FASTAPI INSTANTIATION
# ==========================================
app = FastAPI(
    title="Enterprise Customer Support Ticket API",
    description="A robust API built for external application integrations.",
    version="1.0.0"
)

# ==========================================
# 3. DATA MODELING & VALIDATION GUARDS (Pydantic)
# ==========================================
class TicketCreate(BaseModel):
    customer_name: str = Field(
        ..., 
        min_length=1, 
        max_length=100, 
        description="The full name of the customer. Cannot be empty."
    )
    email: EmailStr = Field(
        ..., 
        description="A validated, RFC-compliant email address for customer contact."
    )
    issue: str = Field(
        ..., 
        min_length=5, 
        description="Description of the issue. Minimum 5 characters to avoid useless tickets."
    )
    priority: str = Field(
        default="low", 
        description="Priority level of the ticket. Options: low, medium, high."
    )

class Ticket(TicketCreate):
    id: str  # Generated automatically by our system
    status: str = "open"  # New tickets always default to "open"
    priority: str 

# Validation model for updates - allows updating single fields optionally
class TicketUpdate(BaseModel):
    issue: Optional[str] = Field(
        None, 
        min_length=5, 
        description="Optional new description for the ticket issue."
    )
    priority: Optional[str] = Field(
        None, 
        description="Optional priority update. Must be: low, medium, or high."
    )
    status: Optional[str] = Field(
        None, 
        description="Optional status update. Must be: open, in-progress, resolved, or closed."
    )


# ==========================================
# 4. DATABASE EMULATION (In-Memory Storage)
# ==========================================
tickets_db: List[Ticket] = []

# ==========================================
# 5. API ENDPOINTS (The Integrator Handshakes)
# ==========================================

@app.post(
    "/tickets", 
    response_model=Ticket, 
    status_code=status.HTTP_201_CREATED,
    summary="Create a new support ticket",
    description="Endpoint for external apps to submit a new support ticket. Validates input automatically."
)
def create_ticket(ticket_in: TicketCreate):
    logger.info(f"Incoming ticket request received for customer: '{ticket_in.customer_name}' ({ticket_in.email})")
    
    # 1. Normalize and Validate priority
    normalized_priority = ticket_in.priority.lower().strip()
    if normalized_priority not in ["low", "medium", "high"]:
        logger.warning(f"Invalid priority submission attempted: '{ticket_in.priority}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Priority must be 'low', 'medium', or 'high'."
        )

    # 2. Create the full Ticket object with a unique ID
    system_id = str(uuid.uuid4())
    logger.info(f"Successfully generated unique Ticket ID: {system_id}")
    
    new_ticket = Ticket(
        id=system_id,
        customer_name=ticket_in.customer_name,
        email=ticket_in.email,
        issue=ticket_in.issue,
        priority=normalized_priority,
        status="open"
    )

    # 3. Save to database
    tickets_db.append(new_ticket)
    logger.info(f"Ticket {system_id} successfully saved to memory database.")
    
    return new_ticket      

@app.get(
    "/tickets", 
    response_model=List[Ticket], 
    status_code=status.HTTP_200_OK,
    summary="Retrieve all support tickets",
    description="Returns a complete list of all currently active tickets in the system."
)
def get_all_tickets():
    logger.info(f"Querying database. Total tickets found: {len(tickets_db)}")
    return tickets_db

@app.get(
    "/tickets/{ticket_id}", 
    response_model=Ticket, 
    status_code=status.HTTP_200_OK,
    summary="Retrieve a specific ticket by ID",
    description="Fetch details of a single ticket using its unique UUID."
)
def get_ticket_by_id(ticket_id: str):
    logger.info(f"Searching for ticket with ID: '{ticket_id}'")
    
    for ticket in tickets_db:
        if ticket.id == ticket_id:
            logger.info(f"Ticket match found for ID: '{ticket_id}'")
            return ticket
            
    logger.warning(f"Ticket lookup failed. ID '{ticket_id}' not found in database.")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Ticket with ID '{ticket_id}' was not found."
    )

@app.patch(
    "/tickets/{ticket_id}",
    response_model=Ticket,
    status_code=status.HTTP_200_OK,
    summary="Partially update an existing ticket",
    description="Updates only the specified fields (issue, priority, status) of an existing ticket."
)
def update_ticket(ticket_id: str, ticket_update: TicketUpdate):
    logger.info(f"Attempting to update ticket with ID: '{ticket_id}'")
    
    # 1. Locate the ticket
    target_ticket = None
    for ticket in tickets_db:
        if ticket.id == ticket_id:
            target_ticket = ticket
            break
            
    if not target_ticket:
        logger.warning(f"Update failed. ID '{ticket_id}' not found in database.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket with ID '{ticket_id}' was not found."
        )
    
    # 2. Get only the fields the user provided
    update_data = ticket_update.model_dump(exclude_unset=True)
    if not update_data:
        logger.info(f"No update data was provided for ticket '{ticket_id}'. Returning unchanged.")
        return target_ticket

    # 3. Validate priority if they want to change it
    if "priority" in update_data:
        normalized_priority = update_data["priority"].lower().strip()
        if normalized_priority not in ["low", "medium", "high"]:
            logger.warning(f"Invalid priority update attempt: '{update_data['priority']}'")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Priority must be 'low', 'medium', or 'high'."
            )
        update_data["priority"] = normalized_priority

    # 4. Validate status if they want to change it
    if "status" in update_data:
        normalized_status = update_data["status"].lower().strip()
        if normalized_status not in ["open", "in-progress", "resolved", "closed"]:
            logger.warning(f"Invalid status update attempt: '{update_data['status']}'")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Status must be 'open', 'in-progress', 'resolved', or 'closed'."
            )
        update_data["status"] = normalized_status

    # 5. Save changes
    for key, value in update_data.items():
        setattr(target_ticket, key, value)

    logger.info(f"Ticket '{ticket_id}' successfully updated fields: {list(update_data.keys())}")
    return target_ticket

@app.delete(
    "/tickets/{ticket_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a ticket",
    description="Hard deletes a ticket permanently from the database using its ID."
)
def delete_ticket(ticket_id: str):
    logger.info(f"Attempting to delete ticket with ID: '{ticket_id}'")
    
    global tickets_db
    initial_length = len(tickets_db)
    
    # Rebuild list excluding the target ID
    tickets_db = [ticket for ticket in tickets_db if ticket.id != ticket_id]
    
    if len(tickets_db) == initial_length:
        logger.warning(f"Delete failed. ID '{ticket_id}' not found in database.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket with ID '{ticket_id}' was not found."
        )
        
    logger.info(f"Ticket '{ticket_id}' successfully deleted from database.")
    return None

WEBHOOK_URL = "https://webhook.site/e1b7bb92-bf8d-42b1-86f4-6c338de6c08d"

@app.post("/tickets", response_model=Ticket, status_code=status.HTTP_201_CREATED)
async def create_ticket(ticket_in: TicketCreate, session: Session = Depends(get_session)):
    logger.info(f"Incoming ticket for customer: '{ticket_in.customer_name}'")
    
    normalized_priority = ticket_in.priority.lower().strip()
    if normalized_priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=400, detail="Priority must be 'low', 'medium', or 'high'.")

    system_id = str(uuid.uuid4())
    
    db_ticket = Ticket(
        id=system_id,
        customer_name=ticket_in.customer_name,
        email=ticket_in.email,
        issue=ticket_in.issue,
        priority=normalized_priority,
        status="open"
    )
    
    session.add(db_ticket)
    session.commit()
    session.refresh(db_ticket)
    
    logger.info(f"Ticket {system_id} successfully saved to SQLite database.")

    # ========================================================
    # NEW INTEGRATION BLOCK: Trigger an external system alert
    # ========================================================
    try:
        async with httpx.AsyncClient() as client:
            # We construct a neat payload to send to the external platform
            payload = {
                "event": "ticket.created",
                "ticket_id": db_ticket.id,
                "customer": db_ticket.customer_name,
                "issue": db_ticket.issue,
                "priority": db_ticket.priority
            }
            logger.info(f"Triggering outbound webhook integration for ticket {system_id}...")
            await client.post(WEBHOOK_URL, json=payload, timeout=5.0)
            logger.info("Webhook successfully dispatched.")
    except httpx.HTTPError as exc:
        # Crucial Integrator Step: Log the failure, but don't break the user's request
        logger.error(f"Failed to dispatch webhook to external system: {exc}")

    return db_ticket