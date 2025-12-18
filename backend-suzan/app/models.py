from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime

# Replaces 'Business' - The SaaS User/Owner
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    business_name: str
    phone_number: str = Field(index=True, unique=True) # The unique identifier (WhatsApp Number)
    password_hash: str # Changed to password_hash for security best practices
    bot_name: str = Field(default="Suzan")
    bot_phone_number: str = Field(default="+1 (555) 194-0685") # Assigned Bot Number
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships (Links to other tables)
    inventory: List["InventoryItem"] = Relationship(back_populates="user")
    sales: List["SalesLedger"] = Relationship(back_populates="user")
    chat_logs: List["ChatLog"] = Relationship(back_populates="user")
    uploads: List["UploadedFile"] = Relationship(back_populates="user")
    alerts: List["Alert"] = Relationship(back_populates="user")
    knowledge: List["BusinessInfo"] = Relationship(back_populates="user") # <--- Links to the new table

# The Inventory/Catalog
class InventoryItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    price: float
    stock: int = Field(default=0)
    description: Optional[str] = None
    
    user_id: int = Field(foreign_key="user.id")
    user: Optional[User] = Relationship(back_populates="inventory")

class SalesLedger(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: str
    item_description: Optional[str]
    amount: Optional[float]
    customer_name: Optional[str]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    logged_by: str 
    status: str = Field(default="COMPLETED") 
    
    user_id: int = Field(foreign_key="user.id")
    user: Optional[User] = Relationship(back_populates="sales")

class ChatLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: str
    sender: str
    message_text: Optional[str] = None
    media_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    user_id: Optional[int] = Field(foreign_key="user.id", default=None)
    user: Optional[User] = Relationship(back_populates="chat_logs")

class UploadedFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    filepath: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user_id: int = Field(foreign_key="user.id")
    user: Optional[User] = Relationship(back_populates="uploads")

# Alerts for the Dashboard
class Alert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str # "Sentiment", "Stock", "System"
    message: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_read: bool = Field(default=False)
    
    user_id: int = Field(foreign_key="user.id")
    user: Optional[User] = Relationship(back_populates="alerts")

# --- NEW: BUSINESS KNOWLEDGE MODEL (Fixes your Error) ---
class BusinessInfo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str  # "Product", "Service", "Policy"
    topic: str     # "Rice", "Delivery", "Opening Hours"
    details: str   # "We sell 50kg for 50k", "Free within Lagos"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user_id: int = Field(foreign_key="user.id")
    user: Optional[User] = Relationship(back_populates="knowledge")