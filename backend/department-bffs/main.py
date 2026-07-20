from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import bank, telecom, gov
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Department BFFs", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bank.router)
app.include_router(telecom.router)
app.include_router(gov.router)

@app.get("/health/live")
def health_live():
    return {"status": "up"}

@app.get("/health/ready")
def health_ready():
    # In a real scenario, we might check connections to downstream services.
    # For now, it's just ready if it's up.
    return {"status": "ready"}
