from mcp.server.fastmcp import FastMCP
import os
import shlex
import paramiko
from time import sleep
from typing import Optional

# Auto open port 8000
mcp = FastMCP(
    name="mcp_test_run",
    port=8001
)

# Step 0: Prepare by create directory Test_2xxxx
# Step 1: Get the ibcf binary version 7.2.65
# Step 2: Get the basic call sipp scenarial
# Step 3: Modify header initial INVITE the same as provided INVITE message
#"INVITE ..."
# Step 4: Using basic config with HMR to enforce TO tag presence
# Step 5: Make the basic call between ibcf
# Step 6: Checking error log:
# "W0 Apply matching rule HAS_TO_TAG : false"
# We need to write 6 tools to handle this
OFFICIAL_BIN_DIR = "/home/omni/AI/Bin/"
WORKING_DIR = "/home/omni/AI/Test/"
SIPP_DIR = "/home/omni/AI/Sipp/"
CONFIG_DIR = "/home/omni/AI/Config/"

REMOTE_HOST = '192.168.37.250'
REMOTE_USER = 'omni'
REMOTE_PASSWORD = 'omni'
REMOTE_PORT = 22 # default SSH port

@mcp.tool()
def execute_remote_command(
    command: str,
    art: str=None
):
    """
    Executes a Linux shell command.

    Parameter:
        command (str): The shell command to execute. 

    Returns:
        The standard output from the command execution.
    """
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REMOTE_HOST, port=REMOTE_PORT, username=REMOTE_USER, password=REMOTE_PASSWORD)

        _, stdout, stderr = ssh.exec_command(command)
        result = {
            "cmd": command,
            "stdout": stdout.read().decode(),
            "stderr": stderr.read().decode() or None,
            "artifacts": art
        }
        ssh.close()
        return result

    except Exception as e:
        return {"cmd": command, "stdout": None, "stderr": str(e), "artifacts": None}

@mcp.tool() 
def root_execute_remote_command(
    command: str,
    art: str=None
):
    """
    Executes a Linux shell command with root privileges using 'sudo'.

    Parameters:
        command (str): The shell command to execute as root.

    Returns:
        The standard output from the command execution.
    """
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REMOTE_HOST, port=REMOTE_PORT, username="root", password="rcirkey")

        _, stdout, stderr = ssh.exec_command(command)
        result = {
            "cmd": command,
            "stdout": stdout.read().decode(),
            "stderr": stderr.read().decode() or None,
            "artifacts": art
        }
        ssh.close()
        return result

    except Exception as e:
        return {"cmd": command, "stdout": None, "stderr": str(e), "artifacts": None}

@mcp.tool()
def copy_binary(
    binary_name: str,
    version: Optional[str]
):
    """
    Copies the specified binary (optionally with a specific version) to the current location

    Parameters:
        binary_name (str): The name of the binary to copy.
        version (Optional[str]): The version of the binary to copy. If None, the default or latest version is used.

    Returns:
        The standard output from the copy command execution.
    """   
    offical_bin = os.path.join(OFFICIAL_BIN_DIR, f"{binary_name}{version}")
    working_bin = os.path.join("/home/omni/bin", f"trung_{binary_name}")
    cmd = f'cp "{offical_bin}" "{working_bin}"'
    
    result = execute_remote_command(cmd, art={"type": "text", "path": working_bin})
    
    return {"actions": [result]}

@mcp.tool()
def get_sipp_scenario(scenario_name: str):
    """
    Get the specified sipp scenario

    Parameter:
    scenario_name: The name of sipp scenario ["basic_call", "reinvite"]
    """
    res = {"actions": []}
    
    remote_path = os.path.join(SIPP_DIR, scenario_name)
    check_cmd = f'[ -e "{remote_path}" ] && echo "exists" || echo "not exists"'
    check_result = execute_remote_command(check_cmd)
    
    res["actions"].append(check_result)

    if "exists" in check_result.get("stdout", "").strip():
        copy_cmd = f'cp -r "{remote_path}"/* "{WORKING_DIR}"'
        copy_result = execute_remote_command(copy_cmd, art={"type": "text", "path": WORKING_DIR})
        
        res["actions"].append(copy_result)
    return res

@mcp.tool()
def add_value_to_header(scenario_name: str, message_type: str, header: str, value: str) -> str:
    """Modify sipp message in a specific message with header and value
    Parameter:
    scenario_name: name of Sipp scenario ex: "A_basic_call.xml"
    message_type: SIP message type ex: INVITE
    header: header type ex: From
    value: value of header ex: tag=1-1-1
    """
    remote_scenario_path = os.path.join(WORKING_DIR, scenario_name)

    # Check if scenario exists on remote
    command_check = f'if [ -e "{remote_scenario_path}" ]; then echo "exists"; else echo "not exists"; fi'
    check_result = execute_remote_command(command_check)

    if "exists" in check_result:
        # Read the scenario content from the remote file
        command_read = f'cat "{remote_scenario_path}"'
        content = execute_remote_command(command_read)

        if content["stderr"]:
            print(f"DEBUG: Error reading file: {content}")
            return content  # Return the error from reading

        # Modify the scenario content
        first_message = content.find(message_type)
        if first_message != -1:
            header_index = content.find(header, first_message)
            if header_index != -1:
                header_end = content.find("\n", header_index)
                content = content[:header_end-1] + "; " + value + content[header_end-1:]

                # Escape the value using shlex.quote()
                escaped_value = shlex.quote(content)

                # Write the modified content back to the remote file
                command_write = f'echo -n {escaped_value} > "{remote_scenario_path}"'
                write_result = execute_remote_command(command_write)

                if "Error" in write_result:
                    print(f"DEBUG: Error writing file: {write_result}")
                    return write_result

                print(f"DEBUG: Sipp scenario {scenario_name} modified")
                return f"Sipp scenario {scenario_name} modified"
            else:
                print(f"DEBUG: Header {header} not found in message type {message_type} on scenario {scenario_name}.")
                return f"Header {header} not found in message type {message_type} on scenario {scenario_name}."
        else:
            print(f"DEBUG: Message type {message_type} not found in scenario {scenario_name}.")
            return f"Message type {message_type} not found in scenario {scenario_name}."
    else:
        print(f"DEBUG: Sipp scenario {scenario_name} does not exist")
        return f"Sipp scenario {scenario_name} does not exist"

@mcp.tool()
def get_config(binary_name: str):
    """
    Retrieves the configuration files (.cfg and _dyn.cfg) for a specific binary.

    Parameters:
        binary_name (str): The name of the binary (e.g., "ibcf").

    Returns:
        dict: A dictionary containing the executed actions and results.
    """
    res = {"actions": []}
    
    base_path = os.path.join(CONFIG_DIR, binary_name)
    dest_path = f"/home/etc/trungHuynh/{binary_name}"

    # Check if the main config file exists
    check_cmd = f'[ -f "{base_path}.cfg" ] && echo "exists" || echo "not exists"'
    check_result = execute_remote_command(check_cmd)
    
    res["actions"].append(check_result)

    if "exists" in check_result.get("stdout", "").strip():
        # Copy .cfg file
        cfg_cmd = f'cp "{base_path}.cfg" "{dest_path}/"'
        cfg_result = execute_remote_command(cfg_cmd, {"type": "text", "path": f"{dest_path}/{binary_name}.cfg"})
        res["actions"].append(cfg_result)

        # Copy _dyn.cfg file
        dyn_cmd = f'cp "{base_path}_dyn.cfg" "{dest_path}/"'
        dyn_result = execute_remote_command(dyn_cmd, {"type": "text", "path": f"{dest_path}/{binary_name}_dyn.cfg"})
        res["actions"].append(dyn_result)
    return res

@mcp.tool()
def modify_HMR_config_file(binary_name: str, header: str, operater: str) -> str:
    """
    Modifies the HMR configuration file for the specified binary by adding or deleting a given header.

    Parameters:
        binary_name (str): The name of the binary (e.g., "ibcf").
        header (str): The header value to add or delete in the configuration file.
        operater (str): The operation to perform — either 'add' or 'delete'.
    """
    #remote_config_path = os.path.join(WORKING_DIR, config_file)
    remote_config_path = "/home/etc/trungHuynh/ibcf/ibcf_dyn.cfg"
    value = """
[ MATCHING_RULE_Detect_Allow ]
Header_Name = Allow
Element_Type = HEADER-NAME
Condition_Type = NONE
Min_Occurrence = 1
Instance = "*"

[ MATCHING_RULE_HAS_FROM_TAG ]
Header_Name = FROM
Element_Type = HEADER-PARAM
Condition_Type = NONE
Instance = "^"
Min_Occurrence = 1
Matching_Value = "(tag)(.*)"

[SIP_MANIPULATION_PROFILE_Check_From_Tag]
Strategy = OUT
Message_Type = BOTH
Method_Type = "*"
Applicability = BOTH
Matching_Rules = (HAS_FROM_TAG)
Manipulation[] = AddALLOW

[PEER_Test2]
Max_in = 65550
Max_out = 65550
Hiding = NO_HIDING
Media_Profile = 19
Authorization_profile = 3
Routing_profile = 0
Trusted = TRUE
Privacy = FALSE
Fields_Filtering = NONE
Domain[] = 192.168.37.94
SIP_MANIPULATION[] = Check_From_Tag
"""
    res = {"actions": []}
    # Check if config exists on remote
    command_check = f'if [ -f "{remote_config_path}" ]; then echo "exists"; else echo "not exists"; fi'
    check_result = execute_remote_command(command_check)
    res["actions"].append(check_result)

    if "exists" in check_result:
        # Read the config content from the remote file
        command_read = f'cat "{remote_config_path}"'
        read_result = execute_remote_command(command_read)

        res["actions"].append(read_result)
        if read_result["stderr"]:
            return res

        content = read_result["stdout"]
        content += value

        # Escape the value using shlex.quote()
        escaped_value = shlex.quote(content)

        # Write the modified content back to the remote file
        command_write = f'echo -n {escaped_value} > "{remote_config_path}"'
        write_result = execute_remote_command(command_write)
        write_result["cmd"] = f'echo -n ... > "{remote_config_path}"'
        res["actions"].append(write_result)
        
    return res


@mcp.tool()
def make_call(binary_name: str, scenario_name: str) -> str:
    """
    Initiates a SIP call using the specified binary and SIPp scenario.

    Parameters:
        binary_name (str): The name of the binary to use (e.g., "ibcf").
        scenario_name (str): The name of the SIPp scenario to execute (e.g., "basic_call", "reinvite").

    Returns:
        str: A message indicating the result of the call initiation.
    """
    command = f'/home/omni/AI/Cmd/make_call.sh "{scenario_name}"'
    result = root_execute_remote_command(command)
    sleep(3)
    return {"actions": result}
        
@mcp.tool()
def get_executed_binary_log(binary_name: str):
    """
    Retrieves the execution log for the specified binary.

    Parameters:
        binary_name (str): The name of the binary (e.g., "ibcf").

    Returns:
        dict: A dictionary with actions, including command, stdout, stderr, and artifacts.
    """
    res = {"actions": []}

    if binary_name != "ibcf":
        msg = f"Binary '{binary_name}' is not supported yet"
        res["actions"].append({
            "cmd": None,
            "stdout": "",
            "stderr": msg,
            "artifacts": None
        })
        return res

    log_path = "/home/log/ibcf41.1"
    check_cmd = f'[ -f "{log_path}" ] && echo "exists" || echo "not exists"'
    check_result = execute_remote_command(check_cmd)

    res["actions"].append(check_result)

    if "exists" in check_result.get("stdout", "").strip():
        read_cmd = f'cat "{log_path}"'
        read_result = execute_remote_command(read_cmd)

        local_log_path = "/home/omni/phuongTran/Test/log/testResult.txt"
        try:
            with open(local_log_path, "w") as f:
                f.write(read_result.get("stdout", ""))
        except Exception as e:
            res["actions"].append({
                "cmd": "write log file",
                "stdout": "",
                "stderr": str(e),
                "artifacts": None
            })
            return res

        res["actions"].append({
            "cmd": read_cmd,
            "stdout": "",
            "stderr": read_result.get("stderr", ""),
            "artifacts": {"type": "text", "path": local_log_path}
        })

    return res

if __name__ == "__main__":
    mcp.run(transport='sse')