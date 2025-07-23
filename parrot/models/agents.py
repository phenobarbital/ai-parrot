from typing import Dict, List, Union
import time
from pathlib import Path
from langchain_core.agents import AgentAction
from datamodel import BaseModel, Field



def created_at(*args, **kwargs) -> int:
    return int(time.time()) * 1000


class AgentResponse(BaseModel):
    """AgentResponse.
    dict_keys(
        ['input', 'chat_history', 'output', 'intermediate_steps']
    )

    Response from Chatbots.
    """
    question: str = Field(required=False)
    input: Union[str, Dict[str, str]] = Field(required=False)
    output: Union[str, Dict[str, str]] = Field(required=False)
    response: str = Field(required=False)
    answer: str = Field(required=False)
    intermediate_steps: list = Field(default_factory=list)
    chat_history: list = Field(repr=True, default_factory=list)
    source_documents: list = Field(required=False, default_factory=list)
    filename: Dict[Path, str] = Field(required=False)
    documents: List[Path] = Field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.output:
            self.answer = self.output
        if self.intermediate_steps:
            steps = []
            docs: list[Path] = []
            for item, result in self.intermediate_steps:
                if isinstance(item, AgentAction):
                    # convert into dictionary:
                    steps.append(
                        {
                            "tool": item.tool,
                            "tool_input": item.tool_input,
                            "result": result,
                            # "log": str(item.log)
                        }
                    )
                # --------- look for filenames --------- #
                if isinstance(result, dict):
                    if "filename" in result:
                        file = result["filename"]
                        if isinstance(file, str):
                            # Convert to Path object
                            file = Path(file).expanduser().resolve()
                        if isinstance(file, Path) and file.exists():
                            # Ensure the file exists
                            docs.append(file)
                        elif isinstance(file, str) and Path(file).expanduser().exists():
                            # If it's a string, convert to Path and check existence
                            docs.append(Path(file).expanduser().resolve())
            if steps:
                self.intermediate_steps = steps
            self.documents = docs
