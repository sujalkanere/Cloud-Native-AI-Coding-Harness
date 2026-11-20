"""
Domain Models and Data Transfer Objects for Cloud-Native AI Coding Harness.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    INSPECTING = "INSPECTING"
    EDITING = "EDITING"
    TESTING = "TESTING"
    EVALUATING = "EVALUATING"
    SELF_CORRECTING = "SELF_CORRECTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"


class AgentStepPhase(str, Enum):
    CONTEXT_MAPPING = "CONTEXT_MAPPING"
    PLANNING = "PLANNING"
    FILE_INSPECTION = "FILE_INSPECTION"
    FILE_EDIT = "FILE_EDIT"
    COMMAND_EXEC = "COMMAND_EXEC"
    TEST_EVALUATION = "TEST_EVALUATION"
    SELF_CORRECTION = "SELF_CORRECTION"
    FINAL_VERIFICATION = "FINAL_VERIFICATION"


class ToolType(str, Enum):
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    LIST_FILES = "list_files"
    EXECUTE_COMMAND = "execute_command"
    GET_DIFF = "get_diff"
    GENERATE_PATCH = "generate_patch"


class CommandResult(BaseModel):
    """Result of running a command inside an isolated sandbox."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FileDiff(BaseModel):
    """Represents a visual diff of a modified file."""
    file_path: str
    status: str = "modified"  # added, modified, deleted
    additions: int = 0
    deletions: int = 0
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    diff_patch: str


class ToolCallDefinition(BaseModel):
    """Represents a tool call initiated by the agent."""
    tool_name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None


class ToolExecutionResult(BaseModel):
    """Result after executing a tool call inside the environment."""
    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    output: Any
    error: Optional[str] = None
    execution_time_ms: float = 0.0


class AgentThoughtStep(BaseModel):
    """Single step in the agent's thought chain, action, and feedback loop."""
    step_number: int
    phase: AgentStepPhase
    thought: str
    action_plan: List[str] = Field(default_factory=list)
    tool_call: Optional[ToolCallDefinition] = None
    tool_result: Optional[ToolExecutionResult] = None
    reflection: Optional[str] = None
    injected_guidance: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentSession(BaseModel):
    """The complete autonomous agent session representation."""
    id: str
    title: str
    task_description: str
    repo_url_or_path: str
    status: SessionStatus = SessionStatus.PENDING
    sandbox_provider: str = "process"  # docker, process, e2b
    llm_provider: str = "mock"  # openai, anthropic, gemini, mock
    current_phase: AgentStepPhase = AgentStepPhase.CONTEXT_MAPPING
    iteration_count: int = 0
    max_iterations: int = 15
    thoughts: List[AgentThoughtStep] = Field(default_factory=list)
    active_diffs: List[FileDiff] = Field(default_factory=list)
    patch_artifact_path: Optional[str] = None
    guidance_queue: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = None
    test_runs_passed: bool = False


# API Request / Response Schemas
class SessionCreateRequest(BaseModel):
    title: str
    task_description: str
    repo_url_or_path: Optional[str] = "./sample_repo"
    sandbox_provider: Optional[str] = "process"  # "docker" or "process"
    llm_provider: Optional[str] = "mock"  # "openai", "anthropic", "mock"
    max_iterations: Optional[int] = 12


class SessionGuidanceRequest(BaseModel):
    guidance: str
    resume_immediately: bool = True


class SystemMetrics(BaseModel):
    active_sandboxes: int
    total_sessions: int
    cpu_usage_pct: float
    memory_usage_pct: float
    sandbox_boot_avg_ms: float
