import os
from groq import Groq
from langchain_groq import ChatGroq
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import List
from sqlmodel import Session, select
from .config import settings
from .db import engine
from .models import ChatLog, User
from .tools import (
    get_sales_analytics,
    log_offline_sale,
    check_item_stock,
    get_current_time
)
from .prompts import ADMIN_SYSTEM_PROMPT, SENTIMENT_ANALYSIS_PROMPT

# Global Memory Store (In-memory for MVP, use Redis for Prod)
store = {}

def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

def load_history_from_db(user_phone: str, limit: int = 10):
    """Loads the last N messages from the SQL ChatLog into LangChain history."""
    history = ChatMessageHistory()
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone_number == user_phone)).first()
        if user:
            logs = session.exec(select(ChatLog).where(ChatLog.user_id == user.id).order_by(ChatLog.timestamp.desc()).limit(limit)).all()
            for log in reversed(logs):
                if log.sender == user_phone:
                     history.add_user_message(log.message_text)
                else:
                     history.add_ai_message(log.message_text)
    return history

async def run_admin_agent(user_phone: str, message: str, bot_name: str, business_name: str):
    """
    Runs the Admin Agent (Tool Calling) with Persistent Memory.
    """
    llm = ChatGroq(
        temperature=0,
        model_name="llama-3.3-70b-versatile",
        groq_api_key=settings.GROQ_API_KEY
    )

    # Updated Admin Tools
    tools = [get_sales_analytics, log_offline_sale, check_item_stock, get_current_time]

    prompt = ChatPromptTemplate.from_messages([
        ("system", ADMIN_SYSTEM_PROMPT),
        ("system", "Your phone number is {user_phone}. Pass this to tools as 'user_phone' when required."),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    session_history = load_history_from_db(user_phone)
    store[user_phone] = session_history

    agent_with_chat_history = RunnableWithMessageHistory(
        agent_executor,
        get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
    )

    response = await agent_with_chat_history.ainvoke(
        {
            "input": message,
            "bot_name": bot_name,
            "business_name": business_name,
            "owner_phone": user_phone,
            "user_phone": user_phone # Explicitly passed for prompt injection
        },
        config={"configurable": {"session_id": user_phone}}
    )

    return response["output"]

async def analyze_sentiment(message: str):
    """
    Analyzes message sentiment using Llama 3 to determine if human intervention is needed.
    """
    llm = ChatGroq(
        temperature=0,
        model_name="llama-3.3-70b-versatile",
        groq_api_key=settings.GROQ_API_KEY
    )

    parser = JsonOutputParser()

    prompt = PromptTemplate(
        template=SENTIMENT_ANALYSIS_PROMPT,
        input_variables=["message"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )

    chain = prompt | llm | parser

    try:
        response = await chain.ainvoke({"message": message})
        return response
    except Exception as e:
        print(f"Sentiment Analysis Error: {e}")
        return {"sentiment": "NEUTRAL", "requires_human": False}

# --- DATA EXTRACTION AGENT (Crucial for Teach Suzan) ---

class InfoExtraction(BaseModel):
    category: str = Field(description="The type of info: 'Product', 'Service', 'Offer', 'Policy', 'Contact'")
    topic: str = Field(description="The specific subject, e.g., 'Eggs', 'Delivery', 'Opening Hours'")
    details: str = Field(description="The value, price, or specific rule")

class ExtractionResult(BaseModel):
    facts: List[InfoExtraction]

async def extract_business_info(text: str):
    """
    Uses Llama 3 to parse free-form text into structured business facts.
    """
    llm = ChatGroq(
        temperature=0,
        model_name="llama-3.3-70b-versatile",
        groq_api_key=settings.GROQ_API_KEY
    )

    # Force AI to output strict JSON
    structured_llm = llm.with_structured_output(ExtractionResult)

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a Data Extraction Assistant. Extract specific details from the user's business description into structured rows."),
        ("human", f"Extract data from this text: {text}")
    ])

    chain = prompt | structured_llm
    return await chain.ainvoke({})

# --- AUDIO TRANSCRIPTION (Crucial for Voice Notes) ---

async def transcribe_audio(file_path: str):
    """
    Transcribes audio using Groq's Whisper model (distil-whisper-large-v3-en).
    """
    client = Groq(api_key=settings.GROQ_API_KEY)
    
    with open(file_path, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=(os.path.basename(file_path), file.read()),
            model="whisper-large-v3",
            response_format="json",
            language="en",
            temperature=0.0
        )
    
    return transcription.text