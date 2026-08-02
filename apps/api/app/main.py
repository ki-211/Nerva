from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .ai import get_ai_adapter
from .schemas import ApplyChangeSet, ChangeSet, Document, IngestionCreate, KnowledgeEvent
from .settings import settings
from .store import Store


app = FastAPI(title="Nerva API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store(settings.sqlalchemy_url())
ai = get_ai_adapter()


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version, "ai_provider": settings.ai_provider}


@app.post("/v1/ingestions", response_model=ChangeSet, status_code=201)
def create_ingestion(payload: IngestionCreate):
    proposal = ai.propose(payload.content, payload.title, store.list_documents())
    return store.create_change_set(payload.kind, payload.content, payload.title, proposal)


@app.get("/v1/change-sets/{change_set_id}", response_model=ChangeSet)
def get_change_set(change_set_id: str):
    result = store.get_change_set(change_set_id)
    if not result:
        raise HTTPException(404, "Change set not found")
    return result


@app.post("/v1/change-sets/{change_set_id}/apply", response_model=ChangeSet)
def apply_change_set(change_set_id: str, payload: ApplyChangeSet):
    result = store.apply_change_set(change_set_id, payload.accepted_item_ids)
    if not result:
        raise HTTPException(409, "Change set does not exist or is no longer applicable")
    return result


@app.get("/v1/documents", response_model=list[Document])
def list_documents():
    return store.list_documents()


@app.get("/v1/knowledge-events", response_model=list[KnowledgeEvent])
def list_knowledge_events():
    return store.list_events()
