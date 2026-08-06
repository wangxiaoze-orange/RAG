"""API 路由聚合"""
from fastapi import APIRouter

from src.api.v2 import auth, chat, conversations, knowledge_base, providers

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(providers.router)
api_router.include_router(knowledge_base.router)
api_router.include_router(conversations.router)
api_router.include_router(chat.router)
