FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirement.txt .
RUN pip install --no-cache-dir -r requirement.txt

# Copy proto and generate stubs in the CURRENT directory (/app)
COPY crawler.proto .
RUN python -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    crawler.proto

# Copy your source code
COPY file_server.py .
COPY crawler.py .

# Create output directory
RUN mkdir -p /app/output

# Expose gRPC port
EXPOSE 50052

CMD ["python", "file_server.py"]