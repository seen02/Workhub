"""CPU-only embedding service; startup and inference never download models."""
import os
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
import torch
from sentence_transformers import SentenceTransformer
from rag_chunks import split_document

torch.set_num_threads(int(os.getenv('EMBEDDING_THREADS','2')))
MODEL_PATH=os.getenv('EMBEDDING_MODEL_PATH','/models/e5')
if not Path(MODEL_PATH,'config.json').is_file():
    raise RuntimeError('Run install_rag_models.py before starting embedding-worker')
model=SentenceTransformer(MODEL_PATH,device='cpu',local_files_only=True)
profile=Path(MODEL_PATH,'PROFILE').read_text().strip()
app=FastAPI()
lock=asyncio.Lock()

class EmbedRequest(BaseModel):
    query:str=Field(default='',max_length=1800)
    document:dict|None=None

@app.get('/health')
def health():return {'profile':profile,'dimensions':384,'device':'cpu','offline':True}

@app.post('/embed')
async def embed(req:EmbedRequest, request:Request):
    async with lock:
        chunks=split_document(req.document,model.tokenizer) if req.document else []
        texts=[c['embedding_text'] for c in chunks] if req.document else ['query: '+req.query]
        if any(len(model.tokenizer.encode(t))>512 for t in texts):raise HTTPException(422,'Embedding input exceeds 512 tokens')
        if not texts:return {'profile':profile,'chunks':[]}
        vectors=[]
        for offset in range(0,len(texts),4):
            if await request.is_disconnected():raise HTTPException(499,'Embedding request cancelled')
            batch=await asyncio.to_thread(model.encode,texts[offset:offset+4],batch_size=4,normalize_embeddings=True,show_progress_bar=False)
            vectors.extend(batch.tolist())
        if chunks:
            return {'profile':profile,'chunks':[{**c,'embedding':v} for c,v in zip(chunks,vectors)]}
        return {'profile':profile,'vector':vectors[0]}
