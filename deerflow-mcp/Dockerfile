FROM python:3.12-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db_common.py db_mcp.py seatunnel_mcp.py minio_mcp.py openmetadata_mcp.py dagster_mcp.py ./

EXPOSE 9101 9102 9103 9104 9105 9106 9107 9108 9109

CMD ["python", "db_mcp.py"]
