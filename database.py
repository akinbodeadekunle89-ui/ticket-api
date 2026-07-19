from sqlmodel import create_engine, Session

# Replace with your actual database URL (e.g., sqlite:///./tickets.db)
sqlite_url = "sqlite:///./tickets.db"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def get_session():
    with Session(engine) as session:
        yield session