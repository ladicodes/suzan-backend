import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    GROQ_API_KEY: Optional[str] = None
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_INDEX_NAME: Optional[str] = None
    HUGGINGFACEHUB_API_TOKEN: Optional[str] = None
    WHATSAPP_TOKEN: Optional[str] = None
    
    # This matches your .env file
    WHATSAPP_PHONE_ID: Optional[str] = None
    
    ADMIN_PHONE: Optional[str] = None 
    WEBHOOK_VERIFY_TOKEN: Optional[str] = None

    # Database
    DATABASE_URL: Optional[str] = None

    # Monitoring
    SENTRY_DSN: Optional[str] = None

    # LangChain tracing
    LANGCHAIN_TRACING_V2: Optional[str] = None
    LANGCHAIN_API_KEY: Optional[str] = None
    LANGCHAIN_PROJECT: Optional[str] = None
    LANGSMITH_TRACING: Optional[str] = None
    LANGSMITH_ENDPOINT: Optional[str] = None
    LANGSMITH_API_KEY: Optional[str] = None
    LANGSMITH_PROJECT: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        env_ignore_empty=True,
        extra="ignore"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Hotfix for malformed .env where ENDPOINT might have spaces
        if self.LANGSMITH_ENDPOINT and " " in self.LANGSMITH_ENDPOINT:
            parts = self.LANGSMITH_ENDPOINT.split(" ")
            self.LANGSMITH_ENDPOINT = parts[0]

    # --- THE FIX IS HERE ---
    # This tricks the code: if it asks for PHONE_NUMBER_ID, give it PHONE_ID
    @property
    def WHATSAPP_PHONE_NUMBER_ID(self):
        return self.WHATSAPP_PHONE_ID

settings = Settings()