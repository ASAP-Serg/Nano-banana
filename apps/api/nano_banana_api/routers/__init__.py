from fastapi import APIRouter

from nano_banana_api.routers import admin, auth, client_errors, images, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(images.router)
api_router.include_router(admin.router)
api_router.include_router(client_errors.router)
