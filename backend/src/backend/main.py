from typing import Annotated

import uvicorn
from fastapi import FastAPI, Query

app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: Annotated[str | None, Query()] = None):
    return {"item_id": item_id, "q": q}


def main() -> None:
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8500, reload=True)