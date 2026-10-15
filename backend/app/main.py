
from fastapi import FastAPI

app = FastAPI(title="Mini SOC")


@app.get("/health")
def health():
    return {"status": "ok"}
