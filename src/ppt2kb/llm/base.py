# From ppt2desc (MIT, (c) 2025 Adam Łucek) - src/llm/base.py, unchanged.
from pathlib import Path
from typing import Protocol, Union, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Protocol defining the interface for LLM clients."""

    model_name: str

    def generate(self, prompt: str, image_path: Union[str, Path]) -> str:
        """Generate content using the LLM model with text + image as input."""
