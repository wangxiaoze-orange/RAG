from pydantic import BaseModel, Field


# ============ 认证 ============
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32, description="登录名")
    password: str = Field(min_length=6, max_length=64)
    nickname: str | None = Field(default=None, max_length=32)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    nickname: str | None = None
    email: str | None = None

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    token: str
    user: UserOut
