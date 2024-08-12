
def agent_config(
    provider: str = 'vertexai',
    model: str = 'gemini-pro',
    temperature: float = 0.4,
    top_p: int = 0.5,
    stream: bool = True
    ) -> dict:
    agent_config ={
        # "llm": {
        #     "provider": provider,
        #     "config": {
        #         "model": model,
        #         "temperature": temperature,
        #         "top_p": top_p,
        #         "stream": stream
        #     }
        # },
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": "sentence-transformers/sentence-t5-large",
            }
        }
    }
    return agent_config


def agent_embedder(
    provider: str = 'huggingface',
    model: str = 'sentence-transformers/sentence-t5-large',
    **kwargs
    ) -> dict:
    agent_config ={
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": "sentence-transformers/sentence-t5-large",
                **kwargs
            }
        }
    }
    return agent_config
