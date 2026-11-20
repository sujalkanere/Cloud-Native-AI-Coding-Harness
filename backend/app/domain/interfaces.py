"""
Domain Interface Contracts for Cloud-Native AI Coding Harness.

Adheres strictly to SOLID Principles:
- ISP (Interface Segregation Principle): Dedicated, thin interfaces (IExecutionTerminal, IFileAccess, ILogStreamer).
- LSP (Liskov Substitution Principle): Any ISandboxEnvironment can be substituted (Docker, LocalProcess, E2B).
- DIP (Dependency Inversion Principle): High-level orchestrators depend on these abstractions.
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Callable, Dict, List, Optional, Any
from .models import (
    CommandResult,
    FileDiff,
    ToolCallDefinition,
    ToolExecutionResult,
    AgentThoughtStep,
    AgentSession,
    SessionStatus
)


class IExecutionTerminal(ABC):
    """ISP: Thin interface dedicated exclusively to executing commands and streaming terminal I/O."""

    @abstractmethod
    async def execute_command(
        self,
        command: str,
        working_dir: Optional[str] = None,
        timeout_seconds: int = 60,
        env_vars: Optional[Dict[str, str]] = None,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        """Executes a command within the isolated sandbox environment."""
        pass

    @abstractmethod
    async def kill_process(self, process_id: Optional[str] = None) -> bool:
        """Kills any active process running in the sandbox."""
        pass


class IFileAccess(ABC):
    """ISP: Thin interface dedicated exclusively to bidirectional file and workspace operations."""

    @abstractmethod
    async def read_file(self, relative_path: str) -> str:
        """Reads content of a file within the workspace."""
        pass

    @abstractmethod
    async def write_file(self, relative_path: str, content: str) -> bool:
        """Writes content to a file in the workspace, creating intermediate directories."""
        pass

    @abstractmethod
    async def list_files(self, relative_path: str = ".", recursive: bool = True) -> List[str]:
        """Lists files within the workspace."""
        pass

    @abstractmethod
    async def file_exists(self, relative_path: str) -> bool:
        """Checks if a file exists in the workspace."""
        pass

    @abstractmethod
    async def get_workspace_diff(self) -> List[FileDiff]:
        """Computes git diff between current workspace state and original baseline."""
        pass

    @abstractmethod
    async def export_git_patch(self) -> str:
        """Exports a standard git patch of all uncommitted workspace changes."""
        pass


class ILogStreamer(ABC):
    """ISP: Thin interface for real-time telemetry and streaming log output."""

    @abstractmethod
    async def stream_logs(self) -> AsyncGenerator[str, None]:
        """Streams real-time stdout/stderr from the sandbox."""
        pass

    @abstractmethod
    def push_log(self, stream_type: str, text: str) -> None:
        """Pushes a log line to active listeners."""
        pass


class ISandboxEnvironment(IExecutionTerminal, IFileAccess, ILogStreamer, ABC):
    """
    LSP & ISP: Unified sandbox contract combining execution, file access, and log streaming.
    All providers (Docker, LocalProcess, E2B, Modal) implement this identical interface.
    """

    @abstractmethod
    async def initialize(self, repo_url_or_path: Optional[str] = None, base_commit: Optional[str] = None) -> bool:
        """Provisions the sandbox, mounts workspace, and prepares warm runtime environment."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Tears down container/micro-VM and cleans up ephemeral resources."""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Checks sandbox health and readiness."""
        pass

    @property
    @abstractmethod
    def sandbox_id(self) -> str:
        """Returns the unique identifier for this sandbox instance."""
        pass

    @property
    @abstractmethod
    def workspace_path(self) -> str:
        """Returns the absolute path to the sandbox workspace."""
        pass


class ILLMProvider(ABC):
    """
    OCP & DIP: Abstract contract for LLM inference.
    Extensible to OpenAI, Anthropic, Gemini, Local LLMs, or Mock simulation runners.
    """

    @abstractmethod
    async def generate_thought_and_action(
        self,
        system_prompt: str,
        task_description: str,
        context_summary: str,
        history: List[AgentThoughtStep],
        available_tools: List[Dict[str, Any]],
        injected_guidance: Optional[str] = None
    ) -> AgentThoughtStep:
        """Generates reasoning, plan update, and next tool action."""
        pass

    @abstractmethod
    async def evaluate_test_results(
        self,
        test_output: str,
        exit_code: int,
        attempted_fix: str,
        history: List[AgentThoughtStep]
    ) -> Dict[str, Any]:
        """Evaluates whether tests passed, failed, or require self-correction."""
        pass


class ISessionRepository(ABC):
    """DIP: Repository contract for session metadata persistence."""

    @abstractmethod
    async def create_session(self, session: AgentSession) -> AgentSession:
        pass

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[AgentSession]:
        pass

    @abstractmethod
    async def list_sessions(self) -> List[AgentSession]:
        pass

    @abstractmethod
    async def update_session(self, session: AgentSession) -> AgentSession:
        pass

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        pass


class IArtifactStore(ABC):
    """DIP: Object storage abstraction for patch files, logs, and repo snapshots."""

    @abstractmethod
    async def store_patch(self, session_id: str, patch_content: str) -> str:
        """Stores patch file and returns download URI or identifier."""
        pass

    @abstractmethod
    async def get_patch(self, session_id: str) -> Optional[str]:
        """Retrieves raw patch content."""
        pass

    @abstractmethod
    async def store_logs(self, session_id: str, logs: str) -> str:
        """Stores execution log bundle."""
        pass


class IEventBus(ABC):
    """DIP: Real-time event bus for decoupled event emission to WebSocket and SSE handlers."""

    @abstractmethod
    async def publish(self, topic: str, event: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def subscribe(self, topic: str) -> AsyncGenerator[Dict[str, Any], None]:
        pass
