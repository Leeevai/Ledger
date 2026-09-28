from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

Strict = ConfigDict(extra="forbid")     # unknown fields → 422, not silently ignored


# ---------- users ----------

class UserCreate(BaseModel):
    model_config = Strict
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)


class UserPatch(BaseModel):
    model_config = Strict
    display_name: str | None = Field(default=None, min_length=1, max_length=100)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    created_at: datetime
    # NOTE: password_hash and is_active are absent. This model is a WALL.


# ---------- sessions ----------

class LoginIn(BaseModel):
    model_config = Strict
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
