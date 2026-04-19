import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator, Optional

from utils.logging import get_logger

logger = get_logger(__name__)


class Conversation:
    """Represents a Claude Code conversation."""

    def __init__(
        self,
        messages: list[dict],
        file_path: str,
        project_name: str = "",
        timestamp: datetime | None = None,
    ):
        self.messages = messages
        self.file_path = file_path
        self.project_name = project_name
        self.timestamp = timestamp or datetime.now(UTC)

    def get_full_text(self) -> str:
        """Get the full conversation as text."""
        return "\n\n".join(
            f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in self.messages
        )

    def get_preview(self, max_chars: int = 500) -> str:
        """Get a preview of the conversation."""
        full_text = self.get_full_text()
        if len(full_text) <= max_chars:
            return full_text
        return full_text[:max_chars] + "..."


class ClaudeLogParser:
    """Parser for Claude Code JSONL log files."""

    def __init__(self, logs_path: str):
        self.logs_path = Path(logs_path).expanduser()
        self.processed_hashes: set[str] = set()

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute a hash of the file contents."""
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _extract_project_name(self, file_path: Path) -> str:
        """Extract project name from file path."""
        # Path structure: ~/.claude/projects/-Users-username-projectname/xxx.jsonl
        try:
            relative = file_path.relative_to(self.logs_path)
            project_dir = str(relative).split("/")[0]
            # Convert -Users-username-projectname to just projectname
            parts = project_dir.split("-")
            if len(parts) > 2:
                # Skip -Users-username- prefix, get the rest
                return "-".join(parts[3:]) if len(parts) > 3 else parts[-1]
            return project_dir
        except Exception:
            return "unknown"

    def get_available_projects(self) -> list[dict]:
        """List all available projects with their conversation counts."""
        if not self.logs_path.exists():
            return []

        projects = {}
        for file_path in self.logs_path.glob("**/*.jsonl"):
            if "subagents" in str(file_path):
                continue

            project_name = self._extract_project_name(file_path)
            project_dir = file_path.parent.name

            if project_dir not in projects:
                projects[project_dir] = {
                    "dir": project_dir,
                    "name": project_name,
                    "files": 0,
                    "path": str(file_path.parent),
                }
            projects[project_dir]["files"] += 1

        return list(projects.values())

    def _parse_jsonl_file(self, file_path: Path) -> list[Conversation]:
        """Parse a single JSONL file into conversations."""
        conversations = []
        current_messages = []
        project_name = self._extract_project_name(file_path)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)

                        # Extract message based on entry type
                        if "message" in entry:
                            msg = entry["message"]
                            role = msg.get("role", "unknown")
                            content = ""

                            # Handle different content formats
                            if "content" in msg:
                                if isinstance(msg["content"], str):
                                    content = msg["content"]
                                elif isinstance(msg["content"], list):
                                    # Extract text from content blocks
                                    for block in msg["content"]:
                                        if isinstance(block, dict):
                                            if block.get("type") == "text":
                                                content += block.get("text", "")
                                            elif block.get("type") == "tool_use":
                                                content += f"[Tool: {block.get('name', 'unknown')}]"
                                        elif isinstance(block, str):
                                            content += block

                            if content:
                                current_messages.append(
                                    {
                                        "role": role,
                                        "content": content,
                                        "timestamp": entry.get("timestamp"),
                                    }
                                )

                        # Check for conversation boundaries
                        if entry.get("type") == "conversation_end" and current_messages:
                            conversations.append(
                                Conversation(
                                    messages=current_messages.copy(),
                                    file_path=str(file_path),
                                    project_name=project_name,
                                )
                            )
                            current_messages = []

                    except json.JSONDecodeError:
                        continue

            # Add remaining messages as a conversation
            if current_messages:
                conversations.append(
                    Conversation(
                        messages=current_messages,
                        file_path=str(file_path),
                        project_name=project_name,
                    )
                )

        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")

        return conversations

    async def parse_file(self, file_path: str) -> list[Conversation]:
        """Parse a single JSONL file into conversations.

        Public async wrapper for _parse_jsonl_file.

        Args:
            file_path: Path to the JSONL file

        Returns:
            List of Conversation objects
        """
        return self._parse_jsonl_file(Path(file_path))

    async def parse_all_logs(
        self,
        project_filter: Optional[str] = None,
        exclude_projects: Optional[list[str]] = None,
    ) -> AsyncIterator[tuple[Path, list[Conversation]]]:
        """Parse JSONL files with optional filtering.

        Args:
            project_filter: Only include this project (partial match on dir name)
            exclude_projects: Exclude these projects (partial match on dir names)
        """
        if not self.logs_path.exists():
            logger.warning(f"Logs path does not exist: {self.logs_path}")
            return

        exclude_projects = exclude_projects or []

        # Find all JSONL files
        pattern = "**/*.jsonl"
        files_found = list(self.logs_path.glob(pattern))
        logger.info(f"Found {len(files_found)} JSONL files in {self.logs_path}")

        for file_path in files_found:
            # Skip subagent files (they're fragments)
            if "subagents" in str(file_path):
                continue

            # Apply project filter
            project_dir = file_path.parent.name

            if project_filter:
                if project_filter.lower() not in project_dir.lower():
                    continue

            # Apply exclusion filter
            should_exclude = False
            for exclude in exclude_projects:
                if exclude.lower() in project_dir.lower():
                    should_exclude = True
                    break
            if should_exclude:
                continue

            # Check if already processed
            file_hash = self._compute_file_hash(file_path)
            if file_hash in self.processed_hashes:
                continue

            # Parse the file
            conversations = self._parse_jsonl_file(file_path)

            if conversations:
                self.processed_hashes.add(file_hash)
                yield file_path, conversations

    async def preview_logs(
        self,
        project_filter: Optional[str] = None,
        exclude_projects: Optional[list[str]] = None,
        max_conversations: int = 10,
    ) -> list[dict]:
        """Preview what would be imported without actually importing.

        Returns a list of conversation previews.
        """
        previews = []
        count = 0

        async for file_path, conversations in self.parse_all_logs(
            project_filter=project_filter,
            exclude_projects=exclude_projects,
        ):
            for conv in conversations:
                if count >= max_conversations:
                    return previews

                previews.append(
                    {
                        "file": str(file_path),
                        "project": conv.project_name,
                        "messages": len(conv.messages),
                        "preview": conv.get_preview(300),
                    }
                )
                count += 1

        return previews

    async def watch_for_changes(self) -> AsyncIterator[tuple[Path, list[Conversation]]]:
        """Watch for new or modified log files."""
        # This would use watchdog or similar for real implementation
        # For now, just yield new files
        async for result in self.parse_all_logs():
            yield result
