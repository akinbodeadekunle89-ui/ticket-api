from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session

class TicketModel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_name: str
    email: str
    issue: str
    priority: str = "low"
    status: str = "open"

# Engine setup for application
engine = create_engine("sqlite:///./tickets.db", connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session