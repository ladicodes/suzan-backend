import pytest
from sqlmodel import Session, select, SQLModel
from app.db import engine, init_db
from app.models import User, ChatLog, InventoryItem
from app.agents import run_admin_agent, load_history_from_db
from app.rag_engine import load_customer_history
from uuid import uuid4
from datetime import datetime

# Setup Test DB
@pytest.fixture(name="session")
def session_fixture():
    init_db()
    with Session(engine) as session:
        yield session

def test_admin_agent_memory(session):
    # 1. Create User
    user = User(
        business_name="TestBiz",
        phone_number="1234567890",
        password="test",
        bot_name="Suzan"
    )
    session.add(user)
    session.commit()

    # 2. Seed Chat Logs (Simulate previous conversation)
    log1 = ChatLog(
        conversation_id="conv1",
        sender="1234567890",
        message_text="My name is Adrian",
        user_id=user.id,
        timestamp=datetime.utcnow()
    )
    session.add(log1)
    session.commit()

    # 3. Test load_history_from_db
    history = load_history_from_db("1234567890")
    messages = history.messages

    assert len(messages) >= 1
    assert messages[0].content == "My name is Adrian"
    print("Memory Load Success: Agent recalls 'My name is Adrian'")

def test_customer_agent_memory(session):
    # 1. Seed Customer Log (Sender is customer phone, not user)
    customer_phone = "0987654321"
    log1 = ChatLog(
        conversation_id="conv2",
        sender=customer_phone,
        message_text="How much is Rice?",
        user_id=None, # Customer chats might not link to user immediately in logs if not manager mode
        timestamp=datetime.utcnow()
    )
    session.add(log1)
    session.commit()

    # 2. Test load_customer_history
    history = load_customer_history(customer_phone)
    messages = history.messages

    assert len(messages) >= 1
    assert messages[0].content == "How much is Rice?"
    print("Customer Memory Load Success")
