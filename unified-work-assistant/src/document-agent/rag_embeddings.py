import os
import httpx

class Embeddings:
    def __init__(self, profile):self.profile=profile
    async def call(self, **payload):
        async with httpx.AsyncClient(timeout=120) as client:
            response=await client.post(os.getenv('RAG_EMBEDDING_URL','http://embedding-worker:8000')+'/embed',json=payload)
            response.raise_for_status();value=response.json()
        if value['profile']!=self.profile:raise ValueError('Embedding profile mismatch; reindex with configured revision')
        return value
