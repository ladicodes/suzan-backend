from pydantic import BaseModel
from typing import Optional

# What the frontend sends for Signup
class UserCreate(BaseModel):
    business_name: str
    phone_number: str
    password: str

# What the frontend sends for Login
class UserLogin(BaseModel):
    phone_number: str
    password: str

# What the backend sends back
class UserResponse(BaseModel):
    id: int
    business_name: str
    phone_number: str
    access_token: str
    token_type: str = "bearer"