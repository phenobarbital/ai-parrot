from .parsers import TOMLParser


async def parse_toml_config(config_dir: str) -> dict:
    try:
        parser = TOMLParser()
        return await parser.parse(config_dir)
    except Exception as exc:
        raise ValueError(
            f"Error Parsing TOML Config on {config_dir}: {exc}"
        )
