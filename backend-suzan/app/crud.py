from sqlmodel import Session, select
from .models import Business, ChatLog, SalesLedger
from .db import engine

def get_first_business():
    with Session(engine) as session:
        return session.exec(select(Business)).first()
