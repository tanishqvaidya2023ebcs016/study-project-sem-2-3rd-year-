FROM python:3.11-slim

WORKDIR /app

# Install build tools for gRPC and netcat for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    netcat-openbsd && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files from your root into the container's /app
COPY . .

# Generate gRPC code from the root crawler.proto
RUN python -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    crawler.proto

# Ensure the output directory exists for the file server
RUN mkdir -p /app/output

EXPOSE 50051 50052