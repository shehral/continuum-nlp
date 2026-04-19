"""Robust JSON extraction from LLM responses.

Handles various LLM output formats including:
- Pure JSON
- Markdown code blocks (```json...``` or ```...```)
- JSON embedded in text
"""

import json
import re
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


def extract_json_from_response(response: str) -> Any | None:
    """Extract JSON from an LLM response using multiple strategies.

    Tries the following strategies in order:
    1. Parse as pure JSON
    2. Extract from ```json code blocks
    3. Extract from ``` code blocks (untyped)
    4. Regex fallback for embedded JSON objects/arrays

    Args:
        response: The raw LLM response text

    Returns:
        Parsed JSON data (dict or list), or None if parsing fails
    """
    if not response:
        return None

    text = response.strip()

    # Strategy 1: Try pure JSON first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from ```json code blocks
    json_block_match = re.search(
        r"```json\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE
    )
    if json_block_match:
        try:
            return json.loads(json_block_match.group(1).strip())
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse ```json block: {e}")

    # Strategy 3: Extract from untyped ``` code blocks
    generic_block_match = re.search(r"```\s*\n?(.*?)\n?```", text, re.DOTALL)
    if generic_block_match:
        try:
            return json.loads(generic_block_match.group(1).strip())
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse ``` block: {e}")

    # Strategy 4: Regex fallback - find JSON object or array in text
    # Look for JSON objects
    json_object_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if json_object_match:
        try:
            return json.loads(json_object_match.group(0))
        except json.JSONDecodeError:
            pass

    # Look for JSON arrays
    json_array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if json_array_match:
        try:
            return json.loads(json_array_match.group(0))
        except json.JSONDecodeError:
            pass

    # All strategies failed
    logger.warning(
        f"Failed to extract JSON from response. "
        f"Response length: {len(text)}, "
        f"First 100 chars: {text[:100]!r}"
    )
    return None


def extract_json_or_default(response: str, default: Any) -> Any:
    """Extract JSON from response, returning default on failure.

    Args:
        response: The raw LLM response text
        default: Value to return if extraction fails

    Returns:
        Parsed JSON data or the default value
    """
    result = extract_json_from_response(response)
    if result is None:
        return default
    return result
