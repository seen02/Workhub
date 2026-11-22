"""Independent, rebuildable index. Every query is namespace/profile/scope constrained."""
import json
import os
from pathlib import Path

class RagStore:
    def __init__(self, namespace, profile):
        self.namespace=namespace; self.profile=profile

    async def connect(self):
        import psycopg
        from psycopg.rows import dict_row
        args={'row_factory':dict_row, 'connect_timeout':5, 'options':'-c statement_timeout=10000'}
        if os.getenv('RAG_DATABASE_URL'):
            return await psycopg.AsyncConnection.connect(os.environ['RAG_DATABASE_URL'],**args)
        return await psycopg.AsyncConnection.connect(host='rag-postgres',dbname=os.getenv('RAG_DATABASE_NAME','rag'),user='rag',
            password=os.environ['RAG_DB_PASSWORD'],**args)

    async def migrate(self):
        async with await self.connect() as db:
            await db.execute((Path(__file__).parent/'migrations/001_rag.sql').read_text())
            await db.execute('CREATE TABLE IF NOT EXISTS rag_managed_scope(namespace text PRIMARY KEY)')

    async def managed_scope(self):
        async with await self.connect() as db:
            cur=await db.execute('SELECT namespace FROM rag_managed_scope WHERE namespace=%s',(self.namespace,))
            return bool(await cur.fetchone())

    async def inventory(self, collections):
        async with await self.connect() as db:
            cur=await db.execute('SELECT metadata FROM rag_documents WHERE namespace=%s AND active AND collection_id=ANY(%s::text[])',(self.namespace,collections))
            return [r['metadata'] for r in await cur.fetchall()]

    async def current(self, docid):
        async with await self.connect() as db:
            cur=await db.execute('SELECT * FROM rag_documents WHERE namespace=%s AND document_id=%s',(self.namespace,docid))
            return await cur.fetchone()

    async def workhub_projects(self):
        async with await self.connect() as db:
            cur=await db.execute('SELECT collection_id AS id,name FROM rag_workhub_projects WHERE namespace=%s ORDER BY collection_id',(self.namespace,))
            return await cur.fetchall()

    async def set_workhub_projects(self, projects, managed=False):
        async with await self.connect() as db:
            if managed:await db.execute('INSERT INTO rag_managed_scope VALUES(%s) ON CONFLICT DO NOTHING',(self.namespace,))
            await db.execute('DELETE FROM rag_workhub_projects WHERE namespace=%s',(self.namespace,))
            for p in projects:
                await db.execute('INSERT INTO rag_workhub_projects VALUES (%s,%s,%s)',(self.namespace,p['id'],p['name']))

    async def replace(self, doc, version, chunks):
        async with await self.connect() as db:
            await db.execute('''INSERT INTO rag_documents(namespace,document_id,collection_id,active_version,active,metadata)
                VALUES (%s,%s,%s,%s,true,%s::jsonb) ON CONFLICT(namespace,document_id) DO UPDATE
                SET collection_id=excluded.collection_id,active_version=excluded.active_version,active=true,
                metadata=excluded.metadata,indexed_at=now()''',
                (self.namespace,doc['id'],doc['collectionId'],version,json.dumps(doc,ensure_ascii=False)))
            for chunk in chunks:
                await db.execute('''INSERT INTO rag_chunks VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector)
                    ON CONFLICT DO NOTHING''',(self.namespace,doc['id'],version,chunk['chunk_id'],self.profile,
                    chunk['text'],json.dumps({k:v for k,v in chunk.items() if k!='embedding'},ensure_ascii=False),json.dumps(chunk['embedding'])))
            # Retain one fully built version only. Transaction rollback preserves the previous version.
            await db.execute('DELETE FROM rag_chunks WHERE namespace=%s AND document_id=%s AND version<>%s',(self.namespace,doc['id'],version))

    async def deactivate(self, docid):
        async with await self.connect() as db:
            await db.execute('UPDATE rag_documents SET active=false WHERE namespace=%s AND document_id=%s',(self.namespace,docid))

    async def reconcile(self, collection, ids):
        async with await self.connect() as db:
            await db.execute('''UPDATE rag_documents SET active=false WHERE namespace=%s AND collection_id=%s
                AND NOT (document_id=ANY(%s::text[]))''',(self.namespace,collection,ids))

    async def sync_state(self, collection, result):
        async with await self.connect() as db:
            await db.execute('''INSERT INTO rag_sync_state VALUES (%s,%s,%s::jsonb,now())
                ON CONFLICT(namespace,collection_id) DO UPDATE SET result=excluded.result,synced_at=now()''',
                (self.namespace,collection,json.dumps(result,ensure_ascii=False)))

    async def status(self):
        async with await self.connect() as db:
            cur=await db.execute('SELECT collection_id,result,synced_at FROM rag_sync_state WHERE namespace=%s',(self.namespace,))
            states=await cur.fetchall()
            cur=await db.execute('SELECT count(*) AS documents FROM rag_documents WHERE namespace=%s AND active',(self.namespace,))
            return {**await cur.fetchone(),'collections':states,'profile':self.profile}

    async def candidates(self, query, vector, collection, codes):
        # Explicit project identifiers are AND filters, not a soft similarity bonus.
        collections=[collection] if isinstance(collection,str) else list(collection)
        base='''FROM rag_chunks c JOIN rag_documents d ON c.namespace=d.namespace AND c.document_id=d.document_id
            AND c.version=d.active_version WHERE d.active AND d.namespace=%s AND c.profile=%s
            AND d.collection_id=ANY(%s::text[])'''
        params=[self.namespace,self.profile,collections]
        for code in codes:
            base+=" AND (lower(d.metadata->>'title') || ' ' || lower(c.text)) ~ %s"
            import re
            params.append(r'\m'+re.escape(code.lower())+r'\M')
        select="SELECT c.chunk_id,c.document_id,c.version,c.text,c.metadata,d.metadata AS document,d.indexed_at, 1-(c.embedding <=> %s::vector) AS similarity "
        async with await self.connect() as db:
            cur=await db.execute(select+base+" ORDER BY c.embedding <=> %s::vector LIMIT 20",(json.dumps(vector),*params,json.dumps(vector)))
            semantic=await cur.fetchall()
            # Parameterized substring plus trigram ranking works for Korean without claiming morphological FTS.
            cur=await db.execute(select+base+" AND (strpos(lower(c.text),lower(%s))>0 OR similarity(c.text,%s)>0.05 OR strpos(lower(d.metadata->>'title'),lower(%s))>0) ORDER BY (strpos(lower(d.metadata->>'title'),lower(%s))>0) DESC, similarity(c.text,%s) DESC LIMIT 20",(json.dumps(vector),*params,query,query,query,query,query))
            lexical=await cur.fetchall()
        return lexical,semantic
