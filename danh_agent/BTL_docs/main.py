# from Crawler import get_docs, crawl_to_markdown
from aiohttp import ClientSession
import markdown

async def push_to_database(documents: list):
    async with ClientSession(base_url="http://10.0.0.1:12000") as http_client:
        # Make the request
        request_body = {
          "collection_name": "BTL",
          "meta_data": None,
          "documents": documents
        }
        async with http_client.post(url="/add_documents",json=request_body) as response:
            # Check if request was successful
            if response.status == 200:
                # Get the response data as JSON
                data = await response.json()
                print("Response data:", data)

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
    import os
    import asyncio
    # DOCS_DIR = os.path.join(os.getcwd(), "openwebui_docs", "docs")
    # # List to store all file paths
    # file_paths = []
    # # Walk through the directory
    # for root, dirs, files in os.walk(DOCS_DIR):
    #     for file in files:
    #         # Construct full file path
    #         file_path = os.path.join(root, file)
    #         file_paths.append(file_path)

    documents = []
    # Print all file paths
    # for path in file_paths:
    path="/mnt/e/workspace/tma/tma_agent/BTL_docs/README.md"
    document = read_markdown(path=path)

    # if len(documents) < 10:
    #     documents.append(document)
    #     continue
        
    asyncio.run(push_to_database(documents=[document]))