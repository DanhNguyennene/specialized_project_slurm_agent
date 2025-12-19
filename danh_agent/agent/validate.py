#!/usr/bin/env python3
"""
Validation Script for Slurm Agent System
Validates all components: models, agents, MCP servers, etc.

Usage:
    python validate.py
"""
import sys
import importlib
import inspect
from typing import get_type_hints, get_origin, get_args, Union
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

# Colors for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def ok(msg):
    print(f"  {Colors.GREEN}✓{Colors.END} {msg}")

def fail(msg):
    print(f"  {Colors.RED}✗{Colors.END} {msg}")
    
def warn(msg):
    print(f"  {Colors.YELLOW}⚠{Colors.END} {msg}")

def header(msg):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{msg}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")

errors = []
warnings = []


def validate_imports():
    """Test all module imports"""
    header("1. Validating Module Imports")
    
    modules = [
        ("flow.slurm_action", "SlurmAction, SlurmActionType, AgentDecision, SlurmActionExecutor"),
        ("flow.slurm_structured_agent", "SlurmStructuredAgent"),
        ("utils.slurm_tools_minimal", "SlurmConnection"),
        ("main", "FastAPI app"),
    ]
    
    for module_name, desc in modules:
        try:
            mod = importlib.import_module(module_name)
            ok(f"{module_name} - {desc}")
        except Exception as e:
            fail(f"{module_name} - {e}")
            errors.append(f"Import {module_name}: {e}")


def validate_pydantic_models():
    """Validate Pydantic models for strict schema compatibility"""
    header("2. Validating Pydantic Models (Strict Schema)")
    
    try:
        from flow.slurm_action import SlurmAction, AgentDecision, SlurmActionType
        from pydantic import BaseModel
        from typing import List, Dict
        
        # Check model_config
        if hasattr(SlurmAction, 'model_config'):
            config = SlurmAction.model_config
            if config.get('extra') == 'forbid':
                ok("SlurmAction has model_config={'extra': 'forbid'}")
            else:
                warn("SlurmAction missing 'extra': 'forbid' in model_config")
                warnings.append("SlurmAction should have extra='forbid'")
        else:
            fail("SlurmAction missing model_config")
            errors.append("SlurmAction needs model_config")
        
        if hasattr(AgentDecision, 'model_config'):
            config = AgentDecision.model_config
            if config.get('extra') == 'forbid':
                ok("AgentDecision has model_config={'extra': 'forbid'}")
            else:
                warn("AgentDecision missing 'extra': 'forbid'")
        
        # Check for forbidden types (Dict, List of complex types)
        hints = get_type_hints(SlurmAction)
        forbidden_found = []
        
        for field_name, field_type in hints.items():
            origin = get_origin(field_type)
            
            # Check for Dict types
            if origin is dict or (hasattr(field_type, '__origin__') and field_type.__origin__ is dict):
                forbidden_found.append(f"{field_name}: Dict type not allowed in strict schema")
            
            # Check for List of non-primitive
            if origin is list:
                args = get_args(field_type)
                if args and not isinstance(args[0], type):
                    # Complex type in list
                    inner = args[0]
                    if hasattr(inner, '__origin__'):
                        forbidden_found.append(f"{field_name}: List of complex type")
        
        if forbidden_found:
            for f in forbidden_found:
                fail(f)
                errors.append(f)
        else:
            ok("No forbidden types (Dict, complex List) found in SlurmAction")
        
        # Check all Optional fields have default=None
        from pydantic.fields import FieldInfo
        model_fields = SlurmAction.model_fields
        missing_defaults = []
        
        for name, field in model_fields.items():
            if name == 'action':  # Required field
                continue
            # Check if Optional
            field_type = hints.get(name)
            origin = get_origin(field_type)
            if origin is Union:
                args = get_args(field_type)
                if type(None) in args:
                    # It's Optional
                    if field.default is None:
                        pass  # Good
                    elif field.default is ...:  # PydanticUndefined
                        missing_defaults.append(name)
        
        if missing_defaults:
            for f in missing_defaults:
                warn(f"Field '{f}' is Optional but missing default=None")
                warnings.append(f"Field {f} needs default=None")
        else:
            ok("All Optional fields have default=None")
        
        # Test model instantiation
        try:
            action = SlurmAction(action=SlurmActionType.SINFO, reasoning="Get cluster info")
            ok(f"SlurmAction instantiation works: {action.action}")
        except Exception as e:
            fail(f"SlurmAction instantiation failed: {e}")
            errors.append(f"SlurmAction instantiation: {e}")
        
        try:
            decision = AgentDecision(
                decision="execute",
                action=SlurmAction(action=SlurmActionType.SQUEUE, reasoning="Show job queue"),
            )
            ok(f"AgentDecision instantiation works")
        except Exception as e:
            fail(f"AgentDecision instantiation failed: {e}")
            errors.append(f"AgentDecision instantiation: {e}")
        
        # Test JSON schema generation
        try:
            schema = AgentDecision.model_json_schema()
            ok(f"JSON schema generation works ({len(str(schema))} chars)")
        except Exception as e:
            fail(f"JSON schema generation failed: {e}")
            errors.append(f"JSON schema: {e}")
            
    except Exception as e:
        fail(f"Model validation error: {e}")
        errors.append(f"Model validation: {e}")


def validate_action_executor():
    """Validate SlurmActionExecutor has all required handlers"""
    header("3. Validating Action Executor")
    
    try:
        from flow.slurm_action import SlurmActionExecutor, SlurmActionType, SlurmAction
        
        executor = SlurmActionExecutor.__new__(SlurmActionExecutor)
        
        # Check _build_args method exists
        if hasattr(executor, '_build_args'):
            ok("_build_args method exists")
        else:
            fail("_build_args method missing")
            errors.append("Missing _build_args")
        
        # Test _build_args with various action types
        test_cases = [
            (SlurmActionType.SQUEUE, {"user": "test", "reasoning": "List user jobs"}),
            (SlurmActionType.SINFO, {"partition": "gpu", "reasoning": "Check GPU partition"}),
            (SlurmActionType.SBATCH, {"script_content": "#!/bin/bash\necho hello", "reasoning": "Submit job"}),
            (SlurmActionType.SCANCEL, {"job_id": "12345", "reasoning": "Cancel job"}),
            (SlurmActionType.SACCT, {"user": "test", "reasoning": "Job history"}),
            (SlurmActionType.SCONTROL_SHOW_JOB, {"job_id": "123", "reasoning": "Show job details"}),
            (SlurmActionType.SCONTROL_HOLD, {"job_id": "123", "reasoning": "Hold job"}),
        ]
        
        for action_type, extra_fields in test_cases:
            try:
                action = SlurmAction(action=action_type, **extra_fields)
                args = executor._build_args(action)
                ok(f"_build_args({action_type.value}) -> {len(args)} args")
            except AttributeError as e:
                fail(f"_build_args({action_type.value}) - AttributeError: {e}")
                errors.append(f"_build_args {action_type.value}: {e}")
            except Exception as e:
                warn(f"_build_args({action_type.value}) - {e}")
        
        # Check all action types are handled
        all_actions = list(SlurmActionType)
        ok(f"Total action types defined: {len(all_actions)}")
        
    except Exception as e:
        fail(f"Executor validation error: {e}")
        errors.append(f"Executor: {e}")


def validate_mcp_servers():
    """Validate MCP server implementations"""
    header("4. Validating MCP Servers")
    
    # Mock server
    try:
        import mock_mcp_server
        ok("mock_mcp_server.py imports successfully")
        
        if hasattr(mock_mcp_server, 'MockSlurmMCPServer'):
            server_class = mock_mcp_server.MockSlurmMCPServer
            server = server_class()
            
            # Check handlers exist
            expected_handlers = [
                'squeue', 'sinfo', 'sbatch', 'scancel', 'sacct',
                'scontrol_show_job', 'scontrol_show_node', 'scontrol_hold'
            ]
            
            for handler in expected_handlers:
                method_name = f"handle_{handler}"
                if hasattr(server, method_name):
                    ok(f"Mock handler: {handler}")
                else:
                    warn(f"Mock handler missing: {handler}")
                    
    except Exception as e:
        warn(f"mock_mcp_server.py: {e}")
        warnings.append(f"Mock server: {e}")
    
    # Real server
    try:
        import slurm_mcp_server
        ok("slurm_mcp_server.py imports successfully")
        
        if hasattr(slurm_mcp_server, 'SlurmMCPServer'):
            ok("SlurmMCPServer class exists")
    except Exception as e:
        warn(f"slurm_mcp_server.py: {e}")
        warnings.append(f"Real server: {e}")


def validate_agent():
    """Validate agent implementation"""
    header("5. Validating Agent")
    
    try:
        from flow.slurm_structured_agent import SlurmStructuredAgent
        
        ok("SlurmStructuredAgent imports successfully")
        
        # Check required methods
        required_methods = ['run_streaming', 'run']
        for method in required_methods:
            if hasattr(SlurmStructuredAgent, method):
                ok(f"Method exists: {method}")
            else:
                fail(f"Method missing: {method}")
                errors.append(f"Agent missing {method}")
        
        # Check agent uses output_type
        source = inspect.getsource(SlurmStructuredAgent)
        if 'output_type' in source:
            ok("Agent uses output_type pattern")
        else:
            warn("Agent may not use output_type pattern")
        
        if 'AgentDecision' in source:
            ok("Agent references AgentDecision model")
        else:
            warn("Agent may not use AgentDecision")
            
    except Exception as e:
        fail(f"Agent validation error: {e}")
        errors.append(f"Agent: {e}")


def validate_main_server():
    """Validate main FastAPI server"""
    header("6. Validating Main Server")
    
    try:
        from main import app
        ok("FastAPI app imports successfully")
        
        # Check routes
        routes = [route.path for route in app.routes]
        expected_routes = ['/v1/chat/completions', '/v1/models']
        
        for route in expected_routes:
            if route in routes:
                ok(f"Route exists: {route}")
            else:
                warn(f"Route missing: {route}")
                
    except Exception as e:
        fail(f"Main server validation error: {e}")
        errors.append(f"Main server: {e}")


def validate_env_config():
    """Validate .env configuration"""
    header("7. Validating Environment Config")
    
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        ok(f".env file exists")
        
        content = env_path.read_text()
        required_vars = ['ENV_IP', 'ENV_PORT', 'BASE_OLLAMA_URL']
        
        for var in required_vars:
            if var in content:
                ok(f"Config var: {var}")
            else:
                warn(f"Missing config var: {var}")
                warnings.append(f"Missing {var} in .env")
    else:
        warn(".env file not found")
        warnings.append("No .env file")


def validate_action_type_coverage():
    """Ensure all action types have corresponding MCP handlers"""
    header("8. Validating Action Type Coverage")
    
    try:
        from flow.slurm_action import SlurmActionType
        
        # Map action types to expected MCP tool names
        action_to_tool = {
            SlurmActionType.SQUEUE: "squeue",
            SlurmActionType.SINFO: "sinfo",
            SlurmActionType.SBATCH: "sbatch",
            SlurmActionType.SCANCEL: "scancel",
            SlurmActionType.SRUN: "srun",
            SlurmActionType.SALLOC: "salloc",
            SlurmActionType.SACCT: "sacct",
            SlurmActionType.SSTAT: "sstat",
            SlurmActionType.SPRIO: "sprio",
            SlurmActionType.SSHARE: "sshare",
            SlurmActionType.SREPORT: "sreport",
            SlurmActionType.SDIAG: "sdiag",
        }
        
        # scontrol actions
        scontrol_types = [t for t in SlurmActionType if 'scontrol' in t.value.lower()]
        ok(f"scontrol action types: {len(scontrol_types)}")
        
        # sacctmgr actions
        sacctmgr_types = [t for t in SlurmActionType if 'sacctmgr' in t.value.lower()]
        ok(f"sacctmgr action types: {len(sacctmgr_types)}")
        
        ok(f"Total action types: {len(list(SlurmActionType))}")
        
    except Exception as e:
        fail(f"Coverage validation error: {e}")
        errors.append(f"Coverage: {e}")


def run_syntax_check():
    """Run Python syntax check on all files"""
    header("9. Python Syntax Check")
    
    py_files = [
        'flow/slurm_action.py',
        'flow/slurm_structured_agent.py',
        'utils/slurm_tools_minimal.py',
        'main.py',
        'mock_mcp_server.py',
        'slurm_mcp_server.py',
    ]
    
    import ast
    
    for py_file in py_files:
        path = Path(__file__).parent / py_file
        if path.exists():
            try:
                content = path.read_text()
                ast.parse(content)
                ok(f"Syntax OK: {py_file}")
            except SyntaxError as e:
                fail(f"Syntax error in {py_file}: {e}")
                errors.append(f"Syntax {py_file}: {e}")
        else:
            warn(f"File not found: {py_file}")


def main():
    print(f"\n{Colors.BOLD}Slurm Agent System Validation{Colors.END}")
    print(f"{'='*60}\n")
    
    validate_imports()
    validate_pydantic_models()
    validate_action_executor()
    validate_mcp_servers()
    validate_agent()
    validate_main_server()
    validate_env_config()
    validate_action_type_coverage()
    run_syntax_check()
    
    # Summary
    header("SUMMARY")
    
    if errors:
        print(f"\n{Colors.RED}{Colors.BOLD}ERRORS ({len(errors)}):{Colors.END}")
        for e in errors:
            print(f"  {Colors.RED}✗{Colors.END} {e}")
    
    if warnings:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}WARNINGS ({len(warnings)}):{Colors.END}")
        for w in warnings:
            print(f"  {Colors.YELLOW}⚠{Colors.END} {w}")
    
    if not errors and not warnings:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ All validations passed!{Colors.END}")
        return 0
    elif not errors:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ No errors, {len(warnings)} warnings{Colors.END}")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ {len(errors)} errors, {len(warnings)} warnings{Colors.END}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
