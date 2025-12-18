from langchain_core.tools import tool
from langchain_core.pydantic_v1 import BaseModel, Field
from sqlmodel import Session, select, func, or_
from .db import engine
from .models import SalesLedger, InventoryItem, User, BusinessInfo
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional

# --- INPUT SCHEMAS ---

class CheckStockInput(BaseModel):
    query: str = Field(description="The name of the product to search for")
    user_phone: Optional[str] = Field(default=None, description="The business owner's phone number")

class SubmitOrderInput(BaseModel):
    item_name: str = Field(description="Name of the item requested")
    # Adding a clear description helps the AI choose the right format
    quantity: int = Field(description="Quantity requested. Must be a whole number/integer.")
    customer_phone: str = Field(description="The customer's phone number")
    user_phone: Optional[str] = Field(default=None, description="The business owner's phone number")

class AnalyticsInput(BaseModel):
    period: str = Field(description="Time period: 'today', 'yesterday', 'week', 'month'")
    user_phone: Optional[str] = Field(default=None, description="The business owner's phone number")

class LogSaleInput(BaseModel):
    item: str = Field(description="Description of item sold")
    amount: float = Field(description="Total amount of the sale")
    user_phone: Optional[str] = Field(default=None, description="The business owner's phone number")

class ManageInventoryInput(BaseModel):
    action: str = Field(description="'ADD' or 'UPDATE'")
    name: str = Field(description="Product name")
    price: float = Field(default=0.0, description="Price of the product")
    stock: int = Field(default=0, description="Quantity in stock")
    user_phone: Optional[str] = Field(default=None, description="The business owner's phone number")

class GetCurrentTimeInput(BaseModel):
    pass

# --- CUSTOMER TOOLS ---

@tool(args_schema=CheckStockInput)
def check_item_stock(query: str, user_phone: str = None):
    """
    Searches for products in BOTH the formal Inventory AND the Knowledge Base (taught facts).
    Returns price, stock status, and details.
    """
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == user_phone)).first()
        if not user: return "Error: User not found."

        results = []

        # 1. Search Formal Inventory (InventoryItem)
        inventory_items = session.exec(select(InventoryItem).where(
            InventoryItem.user_id == user.id,
            InventoryItem.name.ilike(f"%{query}%")
        )).all()

        for p in inventory_items:
            stock_status = f"{p.stock} left" if p.stock > 0 else "Out of Stock"
            results.append(f"📦 [INVENTORY] {p.name}: ₦{p.price:,.2f} ({stock_status})")

        # 2. Search Knowledge Base (BusinessInfo) - The "Teach Suzan" data
        knowledge_items = session.exec(select(BusinessInfo).where(
            BusinessInfo.user_id == user.id,
            or_(
                BusinessInfo.topic.ilike(f"%{query}%"),
                BusinessInfo.details.ilike(f"%{query}%")
            )
        )).all()

        for k in knowledge_items:
            results.append(f"🧠 [KNOWLEDGE] {k.topic}: {k.details}")

        # 3. Consolidate Results
        if not results:
            return f"I couldn't find any items matching '{query}' in the inventory or knowledge base."

        return "\n".join(results)

@tool(args_schema=SubmitOrderInput)
def submit_order_request(item_name: str, quantity: int, customer_phone: str, user_phone: str = None):
    """
    Creates a record in SalesLedger with status='PENDING'.
    """
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == user_phone)).first()
        if not user: return "Error: User not found."

        # Find item in inventory to get price
        item = session.exec(select(InventoryItem).where(
            InventoryItem.user_id == user.id,
            InventoryItem.name.ilike(f"%{item_name}%")
        )).first()

        amount = (item.price * quantity) if item else 0.0

        sale = SalesLedger(
            transaction_id=str(uuid4()),
            item_description=f"{quantity} x {item_name}",
            amount=amount,
            customer_name=f"Customer {customer_phone}",
            logged_by=customer_phone,
            user_id=user.id,
            status="PENDING",
            timestamp=datetime.now()
        )
        session.add(sale)
        session.commit()

    return "✅ Order submitted! Waiting for confirmation."

# --- ADMIN TOOLS ---

@tool(args_schema=AnalyticsInput)
def get_sales_analytics(period: str, user_phone: str = None):
    """
    Returns pre-calculated SQL sums for the period.
    """
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == user_phone)).first()
        if not user: return "Error: User not found."

        now = datetime.now()
        start_date = now

        if period == "today":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "yesterday":
            start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now - timedelta(days=30)

        query = select(func.sum(SalesLedger.amount), func.count(SalesLedger.id)).where(
            SalesLedger.user_id == user.id,
            SalesLedger.timestamp >= start_date,
            SalesLedger.status == "COMPLETED"
        )

        if period == "yesterday":
             query = query.where(SalesLedger.timestamp < end_date)

        result = session.exec(query).first()
        total_revenue = result[0] if result[0] else 0.0
        total_count = result[1] if result[1] else 0

        return f"Sales Analytics ({period}):\n💰 Total Revenue: ₦{total_revenue:,.2f}\n📦 Transactions: {total_count}"

@tool(args_schema=LogSaleInput)
def log_offline_sale(item: str, amount: float, user_phone: str = None):
    """
    Logs a confirmed sale for walk-in customers.
    """
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == user_phone)).first()
        if not user: return "Error: User not found."

        sale = SalesLedger(
            transaction_id=str(uuid4()),
            item_description=item,
            amount=amount,
            customer_name="Walk-in",
            logged_by=user_phone,
            user_id=user.id,
            status="COMPLETED",
            timestamp=datetime.now()
        )
        session.add(sale)
        session.commit()
    return f"✅ Recorded offline sale: {item} for ₦{amount:,.2f}."

@tool(args_schema=ManageInventoryInput)
def manage_inventory(action: str, name: str, price: float = 0, stock: int = 0, user_phone: str = None):
    """
    Adds or updates a product in the inventory.
    """
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == user_phone)).first()
        if not user: return "Error: User not found."

        if action.upper() == "ADD":
            existing = session.exec(select(InventoryItem).where(InventoryItem.user_id == user.id, InventoryItem.name == name)).first()
            if existing: return f"Product '{name}' already exists. Use update."

            prod = InventoryItem(user_id=user.id, name=name, price=price, stock=stock)
            session.add(prod)
            session.commit()
            return f"✅ Added {name} (Price: {price}, Stock: {stock})."

        elif action.upper() == "UPDATE":
            prod = session.exec(select(InventoryItem).where(InventoryItem.user_id == user.id, InventoryItem.name == name)).first()
            if not prod: return f"Product '{name}' not found."

            if price > 0: prod.price = price
            if stock > 0: prod.stock = stock
            session.add(prod)
            session.commit()
            return f"✅ Updated {name}."

    return "Invalid action."

# --- SHARED TOOLS ---

@tool(args_schema=GetCurrentTimeInput)
def get_current_time():
    """Returns the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")