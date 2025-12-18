import os
import sys
import asyncio

# Ensure backend modules can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Updated imports to match new agent structure
from backend.app.rag_engine import process_document, answer_from_rag
from backend.app.agents import run_admin_agent
from backend.tests.create_pdf import create_dummy_pdf

# Mock settings for testing environment if needed, though we rely on export from bash
# from backend.app.config import settings

async def test_ai_flow():
    print("Starting AI Core Verification...")

    # 1. Create Dummy PDF
    pdf_path = os.path.join(os.path.dirname(__file__), "dummy_price_list.pdf")
    create_dummy_pdf(pdf_path)

    # 2. Test Ingestion
    print("\nTesting Ingestion...")
    try:
        # process_document now takes file_id, passing dummy 0
        chunks = await process_document(pdf_path, file_id=0)
        print(f"Ingestion Successful: {chunks} chunks processed.")
    except Exception as e:
        print(f"Ingestion Failed (Expected if Pinecone key invalid): {e}")
        # Continue to test other parts if possible, but RAG relies on this.

    # 3. Test Customer RAG
    print("\nTesting Customer RAG...")
    question = "How much is the 50kg Rice?"
    try:
        response = await answer_from_rag(question)
        print(f"Question: {question}")
        print(f"Answer: {response}")
    except Exception as e:
        print(f"RAG Failed (Expected if Pinecone key invalid): {e}")

    # 4. Test Admin Agent
    print("\nTesting Admin Agent...")
    message = "Sold 2 sneakers to John for 30000"
    try:
        # run_admin_agent(user_phone, message, bot_name, business_name)
        result = await run_admin_agent(
            user_phone="1234567890",
            message=message,
            bot_name="TestBot",
            business_name="TestBiz"
        )
        print(f"Message: {message}")
        print(f"Agent Response: {result}")

    except Exception as e:
        print(f"Agent Execution Failed: {e}")

    # Cleanup
    if os.path.exists(pdf_path):
        os.remove(pdf_path)

if __name__ == "__main__":
    asyncio.run(test_ai_flow())
