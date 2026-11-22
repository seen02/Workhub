FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt
COPY app.py agent_tools.py agent_ux.py document_workflow.py template_layout.py index.html ./
COPY rag_*.py task_runtime.py token_budget.py ./
COPY request_intent.py evidence_selection.py edit_workflow.py ./
COPY user_acl.py ./
COPY knowledge_search.py ./
COPY migrations ./migrations
COPY test*.py ./
RUN mkdir -p /app/data
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
