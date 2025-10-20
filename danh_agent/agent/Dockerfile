FROM python:3.11-slim

# COPY ./rag.py /app
COPY . /app
WORKDIR /app

RUN pip install fastapi chromadb uvicorn sentence_transformers
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
# RUN pip install -r requirements.txt

EXPOSE 8000
EXPOSE 12000
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]