from fastapi import FastAPI, HTTPException
import chromadb
from chromadb.errors import IDAlreadyExistsError, InternalError, ChromaError
from pydantic import BaseModel
from typing import Dict, Any, List
import uvicorn
# from sentence_transformers import SentenceTransformer

DEBUG = True
# CHROMA_SERVER_HOST = "0.0.0.0"
# CHROMA_SERVER_PORT = "8001"

import os
CHROMA_SERVER_HOST = os.environ["CHROMA_SERVER_HOST"]
CHROMA_SERVER_PORT = os.environ["CHROMA_SERVER_HTTP_PORT"]

rag_server = FastAPI(
    title="RAG server",
    description="Rag server for agent query and Admin control over vector database.",
    version="0.1",
    debug=DEBUG
)

chroma_client = chromadb.HttpClient(host=CHROMA_SERVER_HOST, port=CHROMA_SERVER_PORT)

# TODO: Add authorization for create, add, delete collection endpoint to admin only, query endpoint should also have authorization for agent

class BaseRAGserverResponseModel(BaseModel):
    collection_name: str
    meta_data: Dict[str, Any] | None = None

class BaseRAGserverResquestModel(BaseModel):
    collection_name: str
    meta_data: Dict[str, Any] | None = None


class CreateDeleteResponse(BaseRAGserverResponseModel):
    pass

class CreateDeleteRequest(BaseRAGserverResquestModel):
    pass

@rag_server.post("/create_collection", response_model=CreateDeleteResponse)
async def create_collection(request: CreateDeleteRequest) -> Dict[str, Any]:
    """Create a new collection in ChromaDB"""
    
    collection_name = request.collection_name

    if not collection_name or collection_name=="":
        raise HTTPException(422, f"required collection_name argument as part of the request")
    
    meta_data = None
    if request.meta_data:
        meta_data = request.meta_data
    
    try:
        collection = chroma_client.create_collection(
            get_or_create=False,
            name=collection_name,
            metadata=meta_data
        )
        return CreateDeleteResponse(
            collection_name=collection_name,
            meta_data={
                "id": collection.id
            }
        )
    except Exception as e:
        # catch chromadb server error:
        if "ChromaError" in str(e):
            if "already exists" in str(e):
                raise HTTPException(409, f"collection {collection_name} is already exists.")

        raise HTTPException(500, f"{e}")

@rag_server.post("/delete_collection", response_model=CreateDeleteResponse)
async def delete_collection(request: CreateDeleteRequest) -> Dict[str, Any]:
    """Delete a collection from Database"""

    collection_name = request.collection_name
    
    if not collection_name or collection_name=="":
        raise HTTPException(422, f"required collection_name argument as part of the request")
    
    try:
        chroma_client.delete_collection(name=collection_name)
        return CreateDeleteResponse(
            collection_name=collection_name,
            meta_data={"status": "deleted"}
        )
    except Exception as e:
        raise HTTPException(500, f"{e}")

class AddDocsResponse(BaseRAGserverResponseModel):
    pass

class AddDocsRequest(BaseRAGserverResquestModel):
    documents: List[str]

@rag_server.post("/add_documents", response_model=AddDocsResponse)
async def add_documents(request:AddDocsRequest) -> Dict[str, Any]:
    """Add documents to a collection"""

    collection_name = request.collection_name
    documents = request.documents

    if not collection_name or collection_name=="":
        raise HTTPException(422, f"required collection_name argument as part of the request")
    
    if not documents:
        return AddDocsResponse(
            collection_name=collection_name,
            meta_data={
                "status": "complete",
                "detail": "no documents to add"
            }
        )
    try:
        # Fetch or create the collection
        collection = chroma_client.get_collection(name=collection_name)

        # Generate IDs
        ids = [f"doc_{i}_{hash(doc) % 100000}" for i, doc in enumerate(documents)]

        # Add to collection
        collection.add(
            documents=documents,
            # metadatas=processed_metadatas,    # leave for furture AI driven feature
            ids=ids
        )

        return AddDocsResponse(
            collection_name=collection_name,
            meta_data={
                "number of documents added": len(documents)
            }
        )
    except Exception as e:
        print(e)
        raise HTTPException(500, f"{e}")

class QueryCollectionResponse(BaseRAGserverResponseModel):
    query: str
    result: List[Dict[str, Any]]

class QueryCollectionRequest(BaseRAGserverResquestModel):
    query: str
    n_result: int = 5
    where: Any = None

@rag_server.post("/query_collection", response_model=QueryCollectionResponse)
async def query_collection(request: QueryCollectionRequest) -> Dict[str, Any]:
    """Query a collection for similar documents"""
    collection_name = request.collection_name
    query = request.query
    n_results = request.n_result
    where = request.where
    
    if not collection_name:
        raise HTTPException(422, f"required collection_name argument as part of the request")
    if not query:
        raise HTTPException(422, f"required query argument as part of the request")
    
    try:
        collection = chroma_client.get_collection(name=collection_name)
        
        # Perform similarity search
        results = collection.query(
            query_texts=query,
            n_results=n_results,
            # where=where,
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        formatted_results = []
        for i in range(len(results["documents"][0])):
            formatted_results.append({
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
                "id": results["ids"][0][i]
            })
        
        return QueryCollectionResponse(
            collection_name=collection_name,
            query=query,
            result=formatted_results,
            meta_data={
                "number of highest simularity": len(formatted_results),
            }
        )
    except Exception as e:
        raise HTTPException(500, f"{e}")

class GetCollectionResponse(BaseRAGserverResponseModel):
    id: str
    document_count: int

class GetCollectionRequest(BaseRAGserverResponseModel):
    pass

@rag_server.post("/get_collection_info", response_model=GetCollectionResponse)
async def get_collection_info(request: GetCollectionRequest) -> Dict[str, Any]:
    """Get information about a specific collection"""

    collection_name = request.collection_name
    
    if not collection_name:
        raise HTTPException(422, f"required collection_name argument as part of the request")
    
    try:
        collection = chroma_client.get_collection(name=collection_name)
        count = collection.count()
        return GetCollectionResponse(
            collection_name=collection_name,
            id=str(collection.id),
            meta_data= collection.metadata,
            document_count= count
        )
    except Exception as e:
        raise HTTPException(500, f"{e}")

class ListCollectionResponse(BaseModel):
    set_of_collection: List[Dict[str, Any]]
    total_collections: int

@rag_server.get("/get_list_collection", response_model=ListCollectionResponse)
async def list_collections() -> ListCollectionResponse:
    """List all collections"""
    try:
        collections = chroma_client.list_collections()
        collection_info = []
        for collection in collections:
            collection_info.append({
                "name": collection.name,
                "id": collection.id,
                "metadata": collection.metadata
            })
        return ListCollectionResponse(
            set_of_collection=collection_info,
            total_collections=len(collection_info)
        )
    except Exception as e:
        raise HTTPException(500, f"{e}")


if __name__ == "__main__":
    uvicorn.run(
        app="rag:rag_server",
        host="0.0.0.0",
        port=12000,
        reload=True,
        log_level="debug"
    )