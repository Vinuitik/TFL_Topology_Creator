FROM python:3.12-slim

WORKDIR /app/llm_pipeline

COPY llm_pipeline/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_coreference_web_trf

COPY llm_pipeline/ ./

CMD ["python", "agent.py"]
