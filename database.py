from sqlmodel import create_engine, Session, SQLModel, Field

sqlite_url = "sqlite:///./tickets.db"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def get_session():
    with Session(engine) as session:
        yield session

# Add the database table model right here!
class TicketModel(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    customer_name: str
    email: str
    issue: str
    priority: str
    status: str = "open"

# Create the database tables on startup
SQLModel.metadata.create_all(engine)