

import json
import os
from typing import Dict, Any, List
class PromptDict:
    def __init__(self,prompts_dir:str="/mnt/e/workspace/uni/specialized_project/danh_agent/agent/prompts",key_pattern:str="<///KEY_HOLDER///>"):
        self.map = {}
        self.prompts_dir = prompts_dir
        self.key_pattern = key_pattern
        self.load_prompts()

    def load_prompts(self):
        for filename in os.listdir(self.prompts_dir):
            if filename.endswith(".txt"):
                with open(os.path.join(self.prompts_dir, filename), "r") as f:
                    self.map[filename] = f.read()

    def substitute(self, file_name: str, value: Dict[str, str]) -> str:
        import json
        import re
        self.load_prompts()
        
        try:
            thatstring = self.map[file_name]
            for k, v in value.items():
                # Handle complex types
                if isinstance(v, dict):
                    v = json.dumps(v)
                if isinstance(v, list):
                    v = "\n".join(str(item) for item in v)
                
                v = str(v)
                # v = re.sub(r'\d', '', v)  
                
                # print(f"Substituting {k} with {type(v)} in {file_name}")
                placeholder = self.key_pattern.replace("KEY_HOLDER", k)
                # print(f"Using placeholder: {placeholder}")
                # print(v)
                thatstring = thatstring.replace(placeholder, v)
            self.map[file_name] = thatstring
        except Exception as e:
            print(f"Error substituting values in {file_name}: {e}")
            # print(f"Error substituting values in {file_name}: {e}")
            
        return self.map[file_name]

    def get(self, key:str)->str:
        return self.map.get(key,"")
    


def main():
    prompt_dict = PromptDict()
    file_name = "planning_execution.txt"
    collected= ['{\n  "success": true,\n  "directory_path": "/home/ubuntu",\n  "items": [\n    {\n      "name": "3sum-closest",\n      "path": "/home/ubuntu/3sum-closest",\n      "type": "directory"\n    },\n    {\n      "name": "openwebui",\n      "path": "/home/ubuntu/openwebui",\n      "type": "directory"\n    },\n    {\n      "name": "phone_validator",\n      "path": "/home/ubuntu/phone_validator",\n      "type": "directory"\n    },\n    {\n      "name": "tool_server_env",\n      "path": "/home/ubuntu/tool_server_env",\n      "type": "directory"\n    },\n    {\n      "name": "~",\n      "path": "/home/ubuntu/~",\n      "type": "directory"\n    },\n    {\n      "name": "fibonacci.py",\n      "path": "/home/ubuntu/fibonacci.py",\n      "type": "file"\n    },\n    {\n      "name": "file.txt",\n      "path": "/home/ubuntu/file.txt",\n      "type": "file"\n    },\n    {\n      "name": "process_controller.py",\n      "path": "/home/ubuntu/process_controller.py",\n      "type": "file"\n    },\n    {\n      "name": "requirements.txt",\n      "path": "/home/ubuntu/requirements.txt",\n      "type": "file"\n    },\n    {\n      "name": "reverse_k_group.py",\n      "path": "/home/ubuntu/reverse_k_group.py",\n      "type": "file"\n    },\n    {\n      "name": "setup_complete.txt",\n      "path": "/home/ubuntu/setup_complete.txt",\n      "type": "file"\n    },\n    {\n      "name": "start_server.sh",\n      "path": "/home/ubuntu/start_server.sh",\n      "type": "file"\n    },\n    {\n      "name": "test_server.sh",\n      "path": "/home/ubuntu/test_server.sh",\n      "type": "file"\n    },\n    {\n      "name": "tool_server.py",\n      "path": "/home/ubuntu/tool_server.py",\n      "type": "file"\n    }\n  ],\n  "total_items": 14,\n  "vm_info": "10.29.12.23:3001"\n}']
    logs = "\n".join(collected)
    values = {
        "given_context": 'test1111adwwa11',
        "logs": logs
    }
    substituted = prompt_dict.substitute(file_name, values)
    # print(substituted)
if __name__ == "__main__":
    main()