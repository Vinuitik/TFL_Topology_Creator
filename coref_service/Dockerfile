FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*

COPY coref_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m spacy download en_core_web_lg && python -m coreferee install en

COPY coref_service/coref.proto ./coref.proto
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. coref.proto

COPY coref_service/server.py ./server.py

CMD ["python", "server.py"]
