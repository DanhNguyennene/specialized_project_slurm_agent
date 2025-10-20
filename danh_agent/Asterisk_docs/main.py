# from Crawler import get_docs, crawl_to_markdown
from aiohttp import ClientSession
import markdown

async def push_to_database(collection:str, documents: list):
    async with ClientSession(base_url="http://10.0.0.1:12000") as http_client:
        # Make the request
        request_body = {
          "collection_name": collection,
          "meta_data": None,
          "documents": documents
        }
        async with http_client.post(url="/add_documents",json=request_body) as response:
            # Check if request was successful
            if response.status == 200:
                # Get the response data as JSON
                data = await response.json()
                print("Response data:", data)
            else:
                print("error: ", await response.json())

async def delete_collection(collection:str):
    async with ClientSession(base_url="http://10.0.0.1:12000") as http_client:
        async with http_client.post(url="/delete_collection", json={"collection_name": collection}) as response:
            if response.status == 200:
                data = await response.json()
                print("Response data:", data)
            else:
                print("error: ", await response.json())
async def create_collection(collection:str):
    async with ClientSession(base_url="http://10.0.0.1:12000") as http_client:
        async with http_client.post(url="/create_collection", json={"collection_name": collection}) as response:
            if response.status == 200:
                data = await response.json()
                print("Response data:", data)
            else:
                print("error: ", await response.json())
def read_markdown(path: str):
    try:
        with open(path, "r", encoding="utf-8") as md_file:
            markdown_content = md_file.read()
    except FileNotFoundError:
        print(f"Error: {path} not found.")
        markdown_content = "" # Initialize with empty string to avoid error
    return markdown_content

def read_to_html(path: str):
    try:
        with open(path, "r", encoding="utf-8") as md_file:
            markdown_content = md_file.read()
            html_content = markdown.markdown(markdown_content)
    except FileNotFoundError:
        print(f"Error: {path} not found.")
        html_content = ""  # Initialize with empty string to avoid error
    return html_content

if __name__ == "__main__":
    # import os
    # import asyncio
    
    # documents = []
    # with open("/mnt/e/workspace/tma/tma_agent/Asterisk_docs/add_user.txt", "r") as doc:
    #   doc = doc.read()
    #   documents.append(doc)
    #   asyncio.run(push_to_database(collection="OpenWebUI_B", documents=documents))

    import os
    import asyncio

    documents = []
    docs_path = "./Asterisk_docs/my_docs"
    
    for filename in os.listdir(docs_path):
        filepath = os.path.join(docs_path, filename)
        if os.path.isfile(filepath):
            with open(filepath, "r") as f:
                documents.append(f.read())
    #delete existing collection
    asyncio.run(delete_collection(collection="WebUI_Markdown"))
    #create new collection
    asyncio.run(create_collection(collection="WebUI_Markdown"))
    #push documents to database
    asyncio.run(push_to_database(collection="WebUI_Markdown", documents=documents))
