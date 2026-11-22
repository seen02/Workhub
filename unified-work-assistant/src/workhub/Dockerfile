FROM unified-work-assistant/document-agent:migration-baseline
RUN pip install --no-cache-dir 'PyJWT[crypto]==2.10.1' 'websockets==15.0.1' 'pydantic-settings==2.10.1' 'pymongo==4.14.1'
COPY src/report-agent/backend/app /app/legacy_app
COPY src/workhub /app/workhub
WORKDIR /app
CMD ["uvicorn", "workhub.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
