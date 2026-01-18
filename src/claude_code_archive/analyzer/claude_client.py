"""Claude SDK wrapper for pattern classification.

Provides async context manager interface with lazy API key validation.
"""

import json
import os
from typing import Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)


class AnalyzerClaudeClient:
    """Wrapper for ClaudeSDKClient for pattern classification.

    Uses async context manager pattern for session management.
    API key is validated lazily when the session starts.
    """

    def __init__(self, options: Optional[ClaudeAgentOptions] = None):
        self.options = options
        self.client: Optional[ClaudeSDKClient] = None
        self._connected = False

    async def __aenter__(self) -> "AnalyzerClaudeClient":
        """Async context manager entry - validates API key and connects."""
        await self._connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - disconnects the client."""
        await self._disconnect()

    async def _connect(self) -> None:
        """Connect to Claude SDK, validating API key."""
        if self._connected:
            return

        # Lazy API key validation
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Required for LLM classification."
            )

        self.client = ClaudeSDKClient(options=self.options)
        await self.client.connect()
        self._connected = True

    async def _disconnect(self) -> None:
        """Disconnect from Claude SDK."""
        if self.client and self._connected:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            finally:
                self.client = None
                self._connected = False

    async def query(self, prompt: str) -> str:
        """Send a query to Claude and collect the full response.

        Args:
            prompt: The prompt to send to Claude

        Returns:
            The full text response from Claude

        Raises:
            ValueError: If not connected
            RuntimeError: If query fails
        """
        if not self._connected or not self.client:
            raise ValueError("Client not connected. Use async context manager.")

        await self.client.query(prompt)
        return await self._collect_response()

    async def _collect_response(self) -> str:
        """Collect full response from Claude."""
        assert self.client is not None, "Client not connected"

        full_response = ""

        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        full_response += block.text

        return full_response

    @staticmethod
    def extract_json(response: str) -> str:
        """Extract JSON from response, handling code blocks.

        Args:
            response: Raw response text that may contain markdown code blocks

        Returns:
            Extracted JSON string
        """
        json_str = response.strip()

        # Handle markdown code blocks
        if "```json" in json_str or "```" in json_str:
            start = (
                json_str.find("```json") + len("```json")
                if "```json" in json_str
                else json_str.find("```") + 3
            )
            # Skip newline after opening fence
            if start < len(json_str) and json_str[start] == "\n":
                start += 1
            end = json_str.rfind("```")
            if end > start:
                json_str = json_str[start:end].strip()

        return json_str

    @staticmethod
    def parse_json_response(response: str) -> dict:
        """Parse JSON response with error handling.

        Args:
            response: Response text to parse

        Returns:
            Parsed JSON as dict

        Raises:
            ValueError: If JSON parsing fails
        """
        try:
            json_str = AnalyzerClaudeClient.extract_json(response)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse JSON response from Claude: {e}\n"
                f"Response:\n{response[:500]}..."
            )
