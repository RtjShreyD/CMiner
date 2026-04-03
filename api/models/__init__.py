from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session

# Lightweight persistence layer for tracking Async Agent Runs 
# (In the future, also cron jobs for Video Automation)

class AgentJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_name: str
    status: str = Field(default="queued") # queued, running, completed, failed
    log_file: Optional[str] = None
    output_dir: Optional[str] = None

sqlite_file_name = "cminer_studio.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
