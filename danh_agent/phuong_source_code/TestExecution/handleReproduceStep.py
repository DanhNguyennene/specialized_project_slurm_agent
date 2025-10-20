import subprocess
def run_command(command: str) -> str:
    """
    Run a shell command and return the output.
    """
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}")
        return ""

def handleReproduceSuggestion(reproduceSuggestion: str) -> str:
    """
    Handle the reproduce suggestion and return the test result.
    """
# Extract the step from the reproduce suggestion
# Example:
# Step 0: Prepare by create directory Test_2xxxx
# Step 1: Get the ibcf binary version 7.2.65
# Step 2: Get the basic call sipp scenarial
# Step 3: Modify header initial INVITE the same as provided INVITE message
#"INVITE ..."
# Step 4: Using basic config with HMR to enforce TO tag presence
# Step 5: Make the basic call between ibcf
# Step 6: Checking error log:
# "W0 Apply matching rule HAS_TO_TAG : false"
    # Write reproduceSuggestion to a file
    with open("reproduceSuggestion.txt", "w") as f:
        f.write(reproduceSuggestion)

    command = f"python3 /home/omni/phuongTran/Test/TestExecution/mcpClient.py"
    result = run_command(command)
    return result

#reproduceSuggestion = '''Step 1: Create directory Test_2xxxx
#Step 2: Get the ibcf binary version 7.2.65'''

#handleReproduceSuggestion(reproduceSuggestion)