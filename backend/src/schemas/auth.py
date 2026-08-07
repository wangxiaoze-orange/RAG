from pydantic import BaseModel, Field


# ============ 认证 ============
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32, description="登录名")
    password: str = Field(min_length=6, max_length=64)
    nickname: str | None = Field(default=None, max_length=32)
    department_id: int | None = Field(default=None, description="申请加入的部门（待管理员审批）")


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    nickname: str | None = None
    email: str | None = None
    role: str = "user"
    department_id: int | None = None
    department_name: str | None = None
    status: int = 1

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    token: str
    user: UserOut
