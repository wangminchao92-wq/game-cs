FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8899
CMD ["sh", "-c", "python3 -m uvicorn main:app --host 0.0.0.0 --port 8899"]
