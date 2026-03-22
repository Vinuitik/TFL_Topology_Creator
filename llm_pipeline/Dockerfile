FROM python:3.13-slim

WORKDIR /app/llm_pipeline

COPY llm_pipeline/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY llm_pipeline/ ./

CMD ["python", "agent.py"]
