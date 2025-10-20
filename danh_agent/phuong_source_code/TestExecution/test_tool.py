from mcp.server.fastmcp import FastMCP
import os
import shlex
import paramiko
from time import sleep

OFFICIAL_RPM_DIR = "/home/omni/AI/Bin/"
WORKING_DIR = "/home/omni/AI/Test/"
SIPP_DIR = "/home/omni/AI/Sipp/"
CONFIG_DIR = "/home/omni/AI/Config/"

REMOTE_HOST = '192.168.37.250'
REMOTE_USER = 'omni'
REMOTE_PASSWORD = 'omni'
REMOTE_PORT = 22 # default SSH port

def execute_remote_command(command):
    """Executes a command on the remote PC via SSH."""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # Be cautious with this in production
        ssh.connect(REMOTE_HOST, port=REMOTE_PORT, username=REMOTE_USER, password=REMOTE_PASSWORD) # or key_filename=REMOTE_KEY_PATH
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        ssh.close()
        if error:
            return f"Error executing command: {error}"
        return output
    except Exception as e:
        return f"SSH error: {e}"
def root_execute_remote_command(command):
    """Executes a command on the remote PC via SSH using root permission."""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # Be cautious with this in production
        ssh.connect(REMOTE_HOST, port=REMOTE_PORT, username="root", password="rcirkey") # or key_filename=REMOTE_KEY_PATH
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        ssh.close()
        if error:
            return f"Error executing command: {error}"
        return output
    except Exception as e:
        return f"SSH error: {e}"


def get_config_file(bianry_name: str) -> str:
    """Get config file and store in the working dir.
    Parameter:
    bianry_name: name of binary need to get the config. ex: ibcf"""
    config_path = os.path.join(CONFIG_DIR, bianry_name)

    # Check if  config file exists on remote
    command_check = f'if [ -f "{config_path}" ]; then echo "exists"; else echo "not exists"; fi'
    check_result = execute_remote_command(command_check)

    if "exists" in check_result:
        # Move to remote WORKING_DIR
        command_cp = f'cp "{config_path}".cfg /home/etc/trungHuynh/"{bianry_name}"/'
        result = execute_remote_command(command_cp)

        if "Error" in result:
            print("ERROR: ", result)
            return result
            
        command_cp = f'cp "{config_path}"_dyn.cfg /home/etc/trungHuynh/"{bianry_name}"/'
        result = execute_remote_command(command_cp)

        if "Error" in result:
            print("ERROR: ", result)
            return result
        
        print(f"Config file {bianry_name} moved to /home/etc/trungHuynh/{bianry_name}")
        return f"Config file {bianry_name} moved to /home/etc/trungHuynh/{bianry_name}"
    else:
        print(f"Config file {bianry_name} does not exist")
        return f"Config file {bianry_name} does not exist"
        
get_config_file("ibcf")