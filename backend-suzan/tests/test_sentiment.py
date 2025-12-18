import os
import sys
import asyncio

# Ensure backend modules can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.app.agents import analyze_sentiment

async def test_sentiment():
    print("Testing Sentiment Analysis Agent...")

    # Test Negative
    neg_msg = "This is a scam! I want my money back immediately."
    print(f"\nMessage: {neg_msg}")
    try:
        res = await analyze_sentiment(neg_msg)
        print(f"Result: {res}")
        if res.get("sentiment") == "NEGATIVE" and res.get("requires_human") is True:
            print("✅ Verified Negative")
        else:
            print("❌ Failed Negative check")
    except Exception as e:
        print(f"Error: {e}")

    # Test Neutral/Positive
    pos_msg = "How much is the rice?"
    print(f"\nMessage: {pos_msg}")
    try:
        res = await analyze_sentiment(pos_msg)
        print(f"Result: {res}")
        if res.get("requires_human") is False:
             print("✅ Verified Neutral")
        else:
             print("❌ Failed Neutral check")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_sentiment())
