FROM python:3.11-slim

RUN apt-get update 
WORKDIR /app

COPY . .
RUN pip install uvicorn websockets wsproto

RUN pip install --no-cache-dir -r requirements.txt
CMD ["uvicorn", "logs:app", "--host", "0.0.0.0", "--port", "8080"]