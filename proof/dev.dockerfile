FROM python:3.11-slim

WORKDIR /app

# 1. Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 2. Copy requirements and install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copy the proto file directly from root and generate code
COPY crawler.proto ./
RUN python -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    crawler.proto

# 4. Copy source code directly from root
COPY grpc_server.py ./
COPY crawler.py ./

# 5. Networking configuration
EXPOSE 50051

# Start the gRPC server by default
CMD ["python", "grpc_server.py"]