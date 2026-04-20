FROM python:3.10-slim

WORKDIR /app/llm_pipeline

RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*

COPY llm_pipeline/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir torch>=2.2.0 --index-url https://download.pytorch.org/whl/cu118
RUN pip install --no-cache-dir -r requirements.txt

# Generate gRPC client stubs from the coref service proto
RUN pip install --no-cache-dir grpcio-tools>=1.60.0
COPY coref_service/coref.proto /tmp/coref.proto
RUN python -m grpc_tools.protoc -I/tmp --python_out=. --grpc_python_out=. /tmp/coref.proto

COPY llm_pipeline/ ./

CMD ["python", "agent.py"]
