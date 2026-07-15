import logging
import uuid
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

# ==========================================
# 1. LOGGING CONFIGURATION (The "Flight Recorder")
# ==========================================
# This sets up a standardized logger. In production, logs are our eyes and ears.
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
# Business Logic: We split the models. Customers shouldn't generate their own ID 
# or force a status when creating a ticket. They only supply the raw data.

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

# ==========================================
# 4. DATABASE EMULATION (In-Memory Storage)
# ==========================================
# A simple list acting as our database table
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
    
    # Normalize priority input to keep our data consistent
    normalized_priority = ticket_in.priority.lower().strip()
    if normalized_priority not in ["low", "medium", "high"]:
        logger.warning(f"Invalid priority submission attempted: '{ticket_in.priority}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Priority must be 'low', 'medium', or 'high'."
        )
    
    # Business Logic: Assign a secure, globally unique transaction ID
    system_id = str(uuid.uuid4())
    logger.info(f"Successfully generated unique Ticket ID: {system_id}")
    
    # Package into our storage schema
    new_ticket = Ticket(
        id=system_id,
        customer_name=ticket_in.customer_name,
        email=ticket_in.email,
        issue=ticket_in.issue,
        priority=normalized_priority,
        status="open"
    )
    
    # Save to our database
    tickets_db.append(new_ticket)
    logger.info(f"Ticket {system_id} successfully saved to memory database.")
    
    # Return the validated object with its 201 Created status
    return new_ticket