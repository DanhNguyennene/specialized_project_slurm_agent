import os

def retrievalBugs(description):
    data = __getRelatedFile()

    related = "\n".join(
        f"Example {i+1}:\n<example>\n{item}\n</example>" for i, item in enumerate(data)
    )
    return related

def __getRelatedFile():
    folder_path = os.path.join(os.path.dirname(__file__), "data")
    ret = []

    for filename in os.listdir(folder_path):
        if filename.endswith(".txt"):
            file_path = os.path.join(folder_path, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
                ret.append(content)
    return ret
#
#print(retrievalBugs("a"))