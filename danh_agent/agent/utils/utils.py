import re
import json
import textwrap
import xml.etree.ElementTree as ET


__all__ = ["extract_context_summary_response"]


def extract_tool_calls_from_xml(text):
    """
    Extract tool calls from XML format and convert to JSON objects using regex.
    
    Expected XML format:
    <tool_calls>
        <id>tool call number</id>
        <tool_name>name of the tool</tool_name>
        <arguments>
            <param1>value1</param1>
            <param2>value2</param2>
        </arguments>
    </tool_calls>
    
    Args:
        text (str): The input string containing XML tool calls
        
    Returns:
        list: A list of JSON objects representing the tool calls
    """
    
    # Pattern to match complete tool_calls blocks
    tool_calls_pattern = r'<tool_calls>(.*?)</tool_calls>'
    
    # Find all tool_calls blocks
    tool_calls_matches = re.findall(tool_calls_pattern, text, re.DOTALL)
    
    valid_tool_calls = []
    
    for match in tool_calls_matches:
        try:
            tool_call_obj = {}
            
            # Extract id using regex
            id_pattern = r'<id>\s*(.*?)\s*</id>'
            id_match = re.search(id_pattern, match, re.DOTALL)
            if id_match:
                tool_call_obj['id'] = id_match.group(1).strip()
            
            # Extract tool_name using regex
            tool_name_pattern = r'<tool_name>\s*(.*?)\s*</tool_name>'
            tool_name_match = re.search(tool_name_pattern, match, re.DOTALL)
            if tool_name_match:
                tool_call_obj['tool_name'] = tool_name_match.group(1).strip()
            
            # Extract arguments block
            arguments_pattern = r'<arguments>(.*?)</arguments>'
            arguments_match = re.search(arguments_pattern, match, re.DOTALL)
            
            if arguments_match:
                arguments_content = arguments_match.group(1)
                
                # Check if there are nested tags within arguments
                nested_tag_pattern = r'<(\w+)>\s*(.*?)\s*</\1>'
                nested_matches = re.findall(nested_tag_pattern, arguments_content, re.DOTALL)
                
                if nested_matches:
                    # Parse nested arguments into dictionary
                    args_dict = {}
                    for tag_name, tag_value in nested_matches:
                        # Preserve original formatting including newlines and special chars
                        args_dict[tag_name] = tag_value.strip()
                    tool_call_obj['arguments'] = args_dict
                else:
                    # Handle simple text content or JSON
                    args_text = arguments_content.strip()
                    if args_text:
                        try:
                            # Try to parse as JSON
                            parsed_args = json.loads(args_text)
                            tool_call_obj['arguments'] = parsed_args
                        except json.JSONDecodeError:
                            # Store as string if not JSON
                            tool_call_obj['arguments'] = {'value': args_text}
                    else:
                        tool_call_obj['arguments'] = {}
            else:
                tool_call_obj['arguments'] = {}
            
            # Add async_execution flag
            # if isinstance(tool_call_obj['arguments'], dict):
            #     tool_call_obj['arguments']['async_execution'] = False
            
            valid_tool_calls.append(tool_call_obj)
            
        except Exception as e:
            # Handle any exceptions
            print(f"Error processing tool call: {e}")
            continue
    
    return valid_tool_calls


def extract_json_from_string(text):
    """
    Extract all valid JSON objects and arrays from a string using regex.
    
    Args:
        text (str): The input string containing potential JSON data
        
    Returns:
        list: A list of valid JSON objects/arrays found in the string
    """
    
    # Pattern to match JSON objects and arrays with proper nesting
    json_pattern = r'''
        (
            \{                                # Start of object
            (?:
                [^{}"]                        # Non-brace, non-quote characters
                |
                "(?:[^"\\]|\\.)*"            # Quoted strings with escape handling
                |
                \{(?:[^{}"]|"(?:[^"\\]|\\.)*")*\}  # Nested objects (one level)
            )*
            \}                                # End of object
        )
        |
        (
            \[                                # Start of array
            (?:
                [^\[\]"]                      # Non-bracket, non-quote characters
                |
                "(?:[^"\\]|\\.)*"            # Quoted strings with escape handling
                |
                \[(?:[^\[\]"]|"(?:[^"\\]|\\.)*")*\]  # Nested arrays (one level)
            )*
            \]                                # End of array
        )
    '''
    
    # Find all potential JSON matches
    matches = re.findall(json_pattern, text, re.VERBOSE)
    
    valid_json_objects = []
    
    for match_tuple in matches:
        # Get the non-empty match from the tuple
        match = match_tuple[0] if match_tuple[0] else match_tuple[1]
        
        try:
            # Try to parse the matched string as JSON
            parsed_json = json.loads(match)
            
            if isinstance(parsed_json, list):
                # If it's a list, process each item
                for item in parsed_json:
                    if isinstance(item, dict) and 'arguments' in item:
                        if isinstance(item['arguments'], dict):
                            item['arguments']['async_execution'] = False
                        valid_json_objects.append(item)
            elif isinstance(parsed_json, dict):
                # If it's a dict, add async_execution flag if it has arguments
                if 'arguments' in parsed_json:
                    if isinstance(parsed_json['arguments'], dict):
                        parsed_json['arguments']['async_execution'] = False
                valid_json_objects.append(parsed_json)
                
        except json.JSONDecodeError:
            # If it's not valid JSON, skip it
            continue
    
    return valid_json_objects


def extract_context_summary_response(response: str) -> str:
    """
    Extract structured summary response from LLM output.
    
    Expected format:
    <summary>
        <context>...</context>
        <code>...</code>
        <config>...</config>
        <relevant_rate>...</relevant_rate>
    </summary>
    
    Args:
        response (str): The LLM response containing summary tags
        
    Returns:
        str: The extracted summary structure
    """
    # Pattern to match summary blocks
    pattern = r'<summary>(.*?)</summary>'
    matches = re.findall(pattern, response, re.DOTALL)
    
    # Reconstruct the structure
    structure = "".join([f"<summary>{match}</summary>\n" for match in matches])
    
    return structure

# def capture_tools_call(response: str) -> list[str]:
#     """
#     expect response from llm:
#     <tool_calls>
#         <id></id>

#         <tool_name></tool_name>

#         <arguments>
#         </arguments>
#     </tool_calls>
#     """
#     # get structured response
#     pattern = rf'<{re.escape("tool_calls")}>(.*?)</{re.escape("tool_calls")}>'
#     matches = re.findall(pattern, response, re.DOTALL)
#     tools = []

#     for match in matches:
#         pattern = rf'<{re.escape("tool_calls")}>(.*?)</{re.escape("tool_calls")}>'
#         matches = re.findall(pattern, response, re.DOTALL)

    # return structure

# test script
if __name__ == "__main__":
    state = {}
    state['context'] = [". ..", ". ... .."]
    state['chat_history'] = [". ..", ". ... .."]
    prompt = f"""You are a decision-making agent in an agent flow. Your task is to plan a list of actions based on the provided context and chat history, which can be used to perform tool calls.

    <given_context>
    {''.join(state['context'])}
    </given_context>

    <chat_history>
    {''.join(state['chat_history'])}
    </chat_history>

    To succeed in this task, follow these steps:
    1. Review the <given_context> to understand the available tools, resources, and constraints.
    2. Analyze the <chat_history> to identify the user’s intent and any relevant previous interactions.
    3. Determine the sequence of actions needed to address the user’s query or achieve the goal.
    4. For each action:
    - Specify the action clearly and concisely.
    - Provide the exact code required to execute the action.
    - Explain the purpose of the code and how it contributes to the overall plan.
    5. Ensure all actions and code are derived strictly from the information provided in <given_context>.

    Your response must follow this exact format:
    <step_i>
        <action>
            Description of the action to be performed.
        </action>
        <code>
            Code to execute the action.
        </code>
        <additional_information>
            Explanation of the code and its role in the action plan.
        </additional_information>
    </step_i>

    Include only actions and code that are supported by the <given_context>. Ensure each step is clear, actionable, and relevant to the tool call process.
    Include only actions and code that are explicitly supported by the <given_context>. Do not hallucinate or infer information not present in the context.
    Your answer:
    """

    print(prompt)