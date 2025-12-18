from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends, Query, BackgroundTasks, Form
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select, or_  # <--- FIXED: Added or_
from uuid import uuid4
import os
import shutil
from better_profanity import profanity
import sentry_sdk
import requests
from pydantic import BaseModel # <--- FIXED: Added BaseModel

from .config import settings
from .db import engine, init_db
from .models import ChatLog, SalesLedger, UploadedFile, User, Alert, InventoryItem, BusinessInfo
from .whatsapp import send_whatsapp
from .rag_engine import answer_from_rag, process_document, delete_document_vectors, index_business_row
from .utils import save_upload_file
from .agents import run_admin_agent, analyze_sentiment, extract_business_info, transcribe_audio
from .auth import router as auth_router
from .tools import submit_order_request

# Initialize profanity filter
profanity.load_censor_words()

# Monitoring
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=1.0,
        profile_session_sample_rate=1.0,
        profile_lifecycle="trace",
    )

if getattr(settings, "LANGSMITH_TRACING", None):
    os.environ["LANGCHAIN_TRACING_V2"] = str(settings.LANGSMITH_TRACING)
    if getattr(settings, "LANGSMITH_API_KEY", None):
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGSMITH_API_KEY
    if getattr(settings, "LANGSMITH_PROJECT", None):
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGSMITH_PROJECT
    if getattr(settings, "LANGSMITH_ENDPOINT", None):
        os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT
    # Fallback to LANGCHAIN_PROJECT if LANGSMITH_PROJECT is not set but LANGCHAIN_PROJECT is
    elif getattr(settings, "LANGCHAIN_PROJECT", None):
         os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
else:
    if settings.LANGCHAIN_TRACING_V2:
        os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
    if settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    if settings.LANGCHAIN_PROJECT:
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["Auth"])

init_db()

@app.on_event("startup")
def on_startup():
    init_db()

# --- Helpers for Interactive Messages ---

def send_interactive_list(to: str, header: str, body: str, sections: list):
    """Sends a WhatsApp Interactive List Message."""
    url = f"https://graph.facebook.com/v17.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header},
            "body": {"text": body},
            "action": {"button": "Menu", "sections": sections}
        }
    }
    requests.post(url, headers=headers, json=payload)

def send_interactive_buttons(to: str, body: str, buttons: list):
    """Sends a WhatsApp Interactive Button Message."""
    url = f"https://graph.facebook.com/v17.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    formatted_buttons = [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {"buttons": formatted_buttons}
        }
    }
    requests.post(url, headers=headers, json=payload)


# --- Configuration Endpoints ---
@app.get("/config/bot-number")
def get_bot_number(phone: str = Query(...)):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == phone)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"botNumber": user.bot_phone_number}

@app.get("/config")
def get_config(phone: str = Query(None)):
    with Session(engine) as session:
        if phone:
            user = session.exec(select(User).where(User.phone_number == phone)).first()
        else:
            user = session.exec(select(User)).first()

        if user:
            return {"name": user.bot_name, "status": "active"}
        return {"name": "Suzan", "status": "active"}

@app.post("/config/name")
def update_assistant_name(data: dict):
    new_name = data.get("name")
    phone = data.get("phone")

    if profanity.contains_profanity(new_name):
         raise HTTPException(status_code=400, detail="Name contains inappropriate language")

    with Session(engine) as session:
        query = select(User)
        if phone:
            query = query.where(User.phone_number == phone)
        user = session.exec(query).first()

        if user:
            user.bot_name = new_name
            session.add(user)
            session.commit()
            return {"name": user.bot_name}
    return {"name": new_name}

@app.post("/config/status")
def update_status(data: dict):
    new_status = data.get("status")
    # For now we just return it, you can add DB logic if needed to persist status
    return {"status": new_status}

@app.delete("/config/account")
async def delete_account(phone: str = Query(...)):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == phone)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        files = session.exec(select(UploadedFile).where(UploadedFile.user_id == user.id)).all()
        for f in files:
            try:
                await delete_document_vectors(f.id)
                if os.path.exists(f.filepath):
                    os.remove(f.filepath)
            except Exception as e:
                print(f"Error cleaning up file {f.id}: {e}")

        for model in [SalesLedger, InventoryItem, ChatLog, Alert, UploadedFile, BusinessInfo]:
            stmt = select(model).where(model.user_id == user.id)
            results = session.exec(stmt).all()
            for r in results:
                session.delete(r)

        session.delete(user)
        session.commit()

        return {"message": "Account permanently deleted"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), phone: str = Query(...)):
    try:
        file_path = save_upload_file(file)
        with Session(engine) as session:
            user = session.exec(select(User).where(User.phone_number == phone)).first()
            if not user:
                 raise HTTPException(status_code=404, detail="User not found")

            db_file = UploadedFile(filename=file.filename, filepath=file_path, user_id=user.id)
            session.add(db_file)
            session.commit()
            session.refresh(db_file)

            await process_document(file_path, file_id=db_file.id)

        return {"message": "File uploaded", "id": db_file.id, "filename": db_file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files")
def list_files(phone: str = Query(...)):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == phone)).first()
        if not user: return []
        files = session.exec(select(UploadedFile).where(UploadedFile.user_id == user.id)).all()
        return files

@app.delete("/files/{file_id}")
async def delete_file(file_id: int):
    with Session(engine) as session:
        file_record = session.get(UploadedFile, file_id)
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")

        try:
            await delete_document_vectors(file_id)
        except Exception as e:
            print(f"Error deleting vectors: {e}")

        if os.path.exists(file_record.filepath):
            os.remove(file_record.filepath)

        session.delete(file_record)
        session.commit()
        return {"message": "Deleted"}

@app.get("/inventory")
def get_inventory(phone: str = Query(...)):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == phone)).first()
        if not user:
             return []
        items = session.exec(select(InventoryItem).where(InventoryItem.user_id == user.id)).all()
        return items

@app.post("/inventory")
def add_inventory(data: dict):
    phone = data.get("phone")
    name = data.get("name")
    price = data.get("price")
    stock = data.get("stock", 0)

    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == phone)).first()
        if not user:
             raise HTTPException(status_code=404, detail="User not found")

        item = InventoryItem(user_id=user.id, name=name, price=price, stock=stock)
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

@app.get("/sales")
def get_sales(phone: str = Query(...)):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == phone)).first()
        if not user:
             return []

        sales = session.exec(select(SalesLedger).where(SalesLedger.user_id == user.id).order_by(SalesLedger.timestamp.desc())).all()
        return [
            {
                "id": s.id,
                "item": s.item_description,
                "amount": f"₦{s.amount:,.2f}" if s.amount else "₦0.00",
                "customer": s.customer_name or "Unknown",
                "date": s.timestamp.strftime("%Y-%m-%d %H:%M")
            } for s in sales
        ]

@app.get("/alerts")
def get_alerts(phone: str = Query(...)):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == phone)).first()
        if not user:
             return []
        alerts = session.exec(select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at.desc())).all()
        return alerts

# --- KNOWLEDGE ENDPOINTS ---

class KnowledgeRequest(BaseModel):
    phone: str
    text: str

@app.post("/knowledge/process")
async def process_knowledge(data: KnowledgeRequest):
    """
    Processes manual text input from the 'Teach Suzan' page.
    """
    with Session(engine) as session:
        # Validate User
        user = session.exec(select(User).where(or_(
            User.phone_number == data.phone, 
            User.phone_number == f"+{data.phone.strip('+')}"
        ))).first()
        
        if not user: raise HTTPException(404, "User not found")

        try:
            # AI Extraction
            print(f"🧠 Extracting info from text: {data.text[:50]}...")
            extracted_data = await extract_business_info(data.text)
            
            new_rows = []
            for fact in extracted_data.facts:
                # 1. Save to SQL
                row = BusinessInfo(
                    user_id=user.id,
                    category=fact.category,
                    topic=fact.topic,
                    details=fact.details
                )
                session.add(row)
                session.flush() 
                
                # 2. Save to Vector DB
                row_text = f"{fact.category} - {fact.topic}: {fact.details}"
                await index_business_row(row_text, row.id, user.id)
                
                new_rows.append(row)
            
            session.commit()
            print(f"✅ Saved {len(new_rows)} facts.")
            return {"message": "Processed", "rows_added": len(new_rows)}

        except Exception as e:
            print(f"❌ Knowledge Process Error: {e}")
            raise HTTPException(500, detail=f"AI Extraction Failed: {str(e)}")

@app.post("/knowledge/voice")
async def process_voice_knowledge(file: UploadFile = File(...), phone: str = Form(...)):
    """
    1. Uploads Audio
    2. Transcribes via Groq Whisper
    3. Extracts Business Facts
    4. Saves to SQL & Pinecone
    """
    with Session(engine) as session:
        # Validate User
        user = session.exec(select(User).where(or_(
            User.phone_number == phone, 
            User.phone_number == f"+{phone.strip('+')}"
        ))).first()
        
        if not user: raise HTTPException(404, "User not found")

        try:
            # 1. Save Audio Temporarily
            temp_filename = f"voice_{uuid4()}.webm"
            # Ensure uploads dir exists
            if not os.path.exists("uploads"):
                os.makedirs("uploads")
                
            temp_path = f"uploads/{temp_filename}"
            
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            # 2. Transcribe (Whisper)
            print(f"🎙️ Transcribing {temp_filename}...")
            transcribed_text = await transcribe_audio(temp_path)
            print(f"📝 Text: {transcribed_text}")
            
            # Clean up audio file
            if os.path.exists(temp_path):
                os.remove(temp_path)

            # 3. Reuse the Extraction Logic
            extracted_data = await extract_business_info(transcribed_text)
            
            new_rows = []
            for fact in extracted_data.facts:
                # Save to SQL
                row = BusinessInfo(
                    user_id=user.id,
                    category=fact.category,
                    topic=fact.topic,
                    details=fact.details
                )
                session.add(row)
                session.flush()
                
                # Save to Vector DB
                row_text = f"{fact.category} - {fact.topic}: {fact.details}"
                await index_business_row(row_text, row.id, user.id)
                new_rows.append(row)
            
            session.commit()
            return {"message": "Processed", "text": transcribed_text, "rows_added": len(new_rows)}

        except Exception as e:
            print(f"❌ Voice Process Error: {e}")
            raise HTTPException(500, detail=str(e))

@app.get("/knowledge")
def get_knowledge(phone: str = Query(...)):
    with Session(engine) as session:
        user = session.exec(select(User).where(or_(
            User.phone_number == phone, 
            User.phone_number == f"+{phone.strip('+')}"
        ))).first()
        
        if not user: return []
        return session.exec(select(BusinessInfo).where(BusinessInfo.user_id == user.id)).all()

@app.delete("/knowledge/{id}")
async def delete_knowledge(id: int, phone: str = Query(...)):
    with Session(engine) as session:
        user = session.exec(select(User).where(or_(
            User.phone_number == phone, 
            User.phone_number == f"+{phone.strip('+')}"
        ))).first()
        
        row = session.get(BusinessInfo, id)
        if row and row.user_id == user.id:
            session.delete(row)
            session.commit()
            # Note: Add delete_business_row_vectors(id) if available in rag_engine
            return {"ok": True}
        raise HTTPException(404, "Not found")

# --- WEBHOOK LOGIC ---

async def handle_customer_message(sender: str, text: str, user_id: int):
    with Session(engine) as session:
        business_owner = session.get(User, user_id)
        if not business_owner: return 

        # 1. Menu Trigger
        if "menu" in text.lower():
            sections = [{"title": "Options", "rows": [{"id": "browse_items", "title": "Browse Items"}, {"id": "support", "title": "Contact Support"}]}]
            send_interactive_list(sender, "Welcome!", "How can I help?", sections)
            return

        # 2. RAG & Agent
        response = await answer_from_rag(text, user_id=user_id, customer_phone=sender)

        # 3. Check for Trigger Token (From Agent)
        if "[TRIGGER_BUY_BUTTONS]" in response:
            send_interactive_buttons(sender, "Would you like to place this order?", [
                {"id": "yes_buy", "title": "Yes, Order"},
                {"id": "no_cancel", "title": "No, Cancel"}
            ])
        else:
            send_whatsapp(sender, response)

        # 4. Log
        session.add(ChatLog(conversation_id=str(uuid4()), sender="Suzan", message_text=response, user_id=None))
        session.commit()

async def handle_interactive_message(sender: str, button_id: str, user_id: int):
    with Session(engine) as session:
        business_owner = session.get(User, user_id)
        if not business_owner: return

        if button_id == "yes_buy":
            submit_order_request.invoke({"item_name": "Item from Chat", "quantity": 1, "customer_phone": sender, "user_phone": business_owner.phone_number})
            send_whatsapp(sender, "✅ Request sent!")
            send_whatsapp(business_owner.phone_number, f"🔔 New Order from {sender}")
        elif button_id == "no_cancel":
            send_whatsapp(sender, "Order cancelled.")
        elif button_id == "browse_items":
            response = await answer_from_rag("List items", user_id=user_id, customer_phone=sender)
            send_whatsapp(sender, response)
        elif button_id == "support":
            send_whatsapp(business_owner.phone_number, f"ℹ️ Support request from {sender}")
            send_whatsapp(sender, "Owner notified.")


@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == settings.WEBHOOK_VERIFY_TOKEN:
            return PlainTextResponse(content=challenge, status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Verification failed")
    return {"status": "ok"}

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    entry = body.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return {"ok": True}

    message = messages[0]
    sender = message.get("from")
    msg_type = message.get("type")

    with Session(engine) as session:
        # Identify User (Business Owner)
        # 1. Is the sender the Owner?
        user = session.exec(select(User).where(User.phone_number == sender)).first()

        if user:
            # --- ADMIN ROUTE ---
            if msg_type == "text":
                text = message.get("text", {}).get("body")

                # Log User Message
                log = ChatLog(
                    conversation_id=message.get("id", str(uuid4())),
                    sender=sender,
                    message_text=text,
                    user_id=user.id
                )
                session.add(log)
                session.commit()

                async def admin_task(u_phone, msg_text, u_id):
                    # Refetch user
                    with Session(engine) as session:
                        u_obj = session.get(User, u_id)
                        if not u_obj: return

                        resp = await run_admin_agent(u_phone, msg_text, u_obj.bot_name, u_obj.business_name)
                        send_whatsapp(u_phone, resp)
                        # Log Bot Response
                        log = ChatLog(conversation_id=str(uuid4()), sender=u_obj.bot_phone_number, message_text=resp, user_id=u_obj.id)
                        session.add(log)
                        session.commit()

                background_tasks.add_task(admin_task, sender, text, user.id)
                return {"mode": "admin"}

        else:
            # --- CUSTOMER ROUTE ---
            # Find the business owner (Default to first user for now)
            business_owner = session.exec(select(User)).first()
            if not business_owner:
                send_whatsapp(sender, "System not configured.")
                return {"mode": "error"}

            # Determine Message Content for Logging
            text = ""
            if msg_type == "text":
                text = message.get("text", {}).get("body")
            elif msg_type == "interactive":
                # Handle both Buttons and Lists correctly
                interaction = message.get("interactive", {})
                int_type = interaction.get("type")
                
                if int_type == "button_reply":
                    text = f"[Button] {interaction['button_reply']['id']}"
                elif int_type == "list_reply":
                    text = f"[List] {interaction['list_reply']['id']}"

            # Log Customer Message
            log = ChatLog(
                conversation_id=message.get("id", str(uuid4())),
                sender=sender,
                message_text=text,
                user_id=None
            )
            session.add(log)
            session.commit()

            # Dispatch Background Tasks
            if msg_type == "text":
                background_tasks.add_task(handle_customer_message, sender, text, business_owner.id)

            elif msg_type == "interactive":
                interaction = message.get("interactive", {})
                if interaction.get("type") == "button_reply":
                    button_id = interaction.get("button_reply", {}).get("id")
                    background_tasks.add_task(handle_interactive_message, sender, button_id, business_owner.id)
                elif interaction.get("type") == "list_reply":
                    list_id = interaction.get("list_reply", {}).get("id")
                    background_tasks.add_task(handle_interactive_message, sender, list_id, business_owner.id)

            return {"mode": "customer"}

    return {"ok": True}