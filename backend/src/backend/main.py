from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from backend.routers.profile import router as profile_router

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

app = FastAPI(title="LinkedIn Profile API")
app.include_router(profile_router)


@app.get("/")
def read_root():
    return {"message": "Server is online"}


def main() -> None:
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8500, reload=True)
