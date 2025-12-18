import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from pinecone import Pinecone as PineconeClient
from langsmith import traceable
from starlette.concurrency import run_in_threadpool # <--- Prevents Server Freezing
from langchain.docstore.document import Document # <--- Needed for Text Indexing

from sqlmodel import Session, select
from .db import engine
from .models import InventoryItem, User, ChatLog
from .config import settings
from .prompts import CUSTOMER_SYSTEM_PROMPT
from .tools import check_item_stock, submit_order_request, get_current_time

# Ensure env vars are set
if settings.PINECONE_API_KEY:
    os.environ["PINECONE_API_KEY"] = settings.PINECONE_API_KEY
if settings.GROQ_API_KEY:
    os.environ["GROQ_API_KEY"] = settings.GROQ_API_KEY
if settings.HUGGINGFACEHUB_API_TOKEN:
    os.environ["HUGGINGFACEHUB_API_TOKEN"] = settings.HUGGINGFACEHUB_API_TOKEN

# Initialize Embeddings
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")

store = {}

def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

def load_customer_history(customer_id: str, limit: int = 10):
    history = ChatMessageHistory()
    with Session(engine) as session:
        logs = session.exec(select(ChatLog).where(ChatLog.sender == customer_id).order_by(ChatLog.timestamp.desc()).limit(limit)).all()
        for log in reversed(logs):
            history.add_user_message(log.message_text)
    return history

# --- DOCUMENT PROCESSING (PDFs) ---

def _process_document_sync(file_path: str, file_id: int):
    """
    Synchronous worker for PDF processing.
    We run this in a threadpool so it doesn't block the async event loop.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    # 1. Load PDF
    loader = PyPDFLoader(file_path)
    docs = loader.load()

    for doc in docs:
        doc.metadata["file_id"] = file_id
        doc.metadata["source"] = "pdf_upload"

    # 2. Split Text
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(docs)

    # 3. Upload to Pinecone in Batches
    batch_size = 50
    print(f"🌲 Processing {len(splits)} vectors for Pinecone...")
    
    for i in range(0, len(splits), batch_size):
        batch = splits[i : i + batch_size]
        PineconeVectorStore.from_documents(
            documents=batch,
            embedding=embeddings,
            index_name=settings.PINECONE_INDEX_NAME
        )
    
    return len(splits)

async def process_document(file_path: str, file_id: int):
    """Async wrapper that pushes heavy PDF work to a background thread."""
    return await run_in_threadpool(_process_document_sync, file_path, file_id)

async def delete_document_vectors(file_id: int):
    """Deletes vectors associated with a specific PDF file."""
    def _delete_sync():
        pc = PineconeClient(api_key=settings.PINECONE_API_KEY)
        index = pc.Index(settings.PINECONE_INDEX_NAME)
        index.delete(filter={"file_id": {"$eq": file_id}})
    
    try:
        await run_in_threadpool(_delete_sync)
    except Exception as e:
        print(f"Error deleting from Pinecone: {e}")
        # Log error but don't crash flow

# --- NEW: KNOWLEDGE BASE INDEXING (VOICE/TEXT) ---

async def process_raw_text(text: str, user_id: int):
    """
    Ingests generic text (legacy method).
    """
    doc = Document(page_content=text, metadata={"user_id": user_id, "source": "user_input"})
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents([doc])
    
    def _upload_sync():
        PineconeVectorStore.from_documents(
            documents=splits,
            embedding=embeddings,
            index_name=settings.PINECONE_INDEX_NAME
        )
    await run_in_threadpool(_upload_sync)
    return len(splits)

async def index_business_row(text: str, row_id: int, user_id: int):
    """
    Indexes a specific Fact/Row from the SQL table into Pinecone.
    We tag it with 'row_id' so we can find and delete it later.
    """
    doc = Document(
        page_content=text, 
        metadata={
            "row_id": row_id,       # <--- CRITICAL: Links to SQL Table
            "user_id": user_id, 
            "source": "business_info" 
        }
    )
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents([doc])
    
    def _upload_sync():
        PineconeVectorStore.from_documents(
            documents=splits,
            embedding=embeddings,
            index_name=settings.PINECONE_INDEX_NAME
        )
    await run_in_threadpool(_upload_sync)

async def delete_business_row_vectors(row_id: int):
    """
    Deletes vectors from Pinecone based on the SQL row_id.
    """
    def _delete_sync():
        pc = PineconeClient(api_key=settings.PINECONE_API_KEY)
        index = pc.Index(settings.PINECONE_INDEX_NAME)
        index.delete(filter={"row_id": {"$eq": row_id}})
    
    try:
        await run_in_threadpool(_delete_sync)
        print(f"✅ Deleted vectors for row {row_id}")
    except Exception as e:
        print(f"❌ Error deleting vectors: {e}")

# --- RAG ANSWER GENERATION ---

@traceable
async def answer_from_rag(question: str, user_id: int = None, customer_phone: str = "unknown"):
    """
    Runs the Customer Agent (Tool Calling).
    """
    # Re-fetch user in a new session to avoid DetachedInstanceError
    if user_id:
        with Session(engine) as session:
            user = session.get(User, user_id)
            bot_name = user.bot_name if user else "Suzan"
            business_name = user.business_name if user else "this business"
            user_phone = user.phone_number if user else None
    else:
        bot_name = "Suzan"
        business_name = "this business"
        user_phone = None

    llm = ChatGroq(
        temperature=0,
        model_name="llama-3.3-70b-versatile",
        groq_api_key=settings.GROQ_API_KEY
    )

    # Note: We configure the Retriever to filter by User ID to prevent data leaks
    vectorstore = PineconeVectorStore(
        index_name=settings.PINECONE_INDEX_NAME, 
        embedding=embeddings
    )
    retriever = vectorstore.as_retriever(
        search_kwargs={"filter": {"user_id": user_id}} if user_id else {}
    )

    # Customer Tools
    tools = [check_item_stock, submit_order_request, get_current_time]
    # You could also add a 'search_knowledge_base' tool using the retriever here if needed
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", CUSTOMER_SYSTEM_PROMPT),
        ("system", "IMPORTANT: Check 'check_item_stock' for prices."),
        ("system", "The business owner's phone number is: {user_phone}. Pass this to tools if needed."),
        ("system", "Your customer's phone number is: {customer_phone}. Pass this to tools if needed."),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    session_history = load_customer_history(customer_phone)
    store[customer_phone] = session_history

    agent_with_chat_history = RunnableWithMessageHistory(
        agent_executor,
        get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
    )

    response = await agent_with_chat_history.ainvoke(
        {
            "input": question,
            "bot_name": bot_name,
            "business_name": business_name,
            "user_phone": user_phone,
            "customer_phone": customer_phone
        },
        config={"configurable": {"session_id": customer_phone}}
    )

    return response["output"]