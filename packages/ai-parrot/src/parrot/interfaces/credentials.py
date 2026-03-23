import os
from abc import ABC
import contextlib
from typing import TypeVar
from typing_extensions import ParamSpec
from navconfig import config
from navconfig.logging import logging


P = ParamSpec("P")
T = TypeVar("T")


valid_types = {
    "<class 'str'>": str,
    "<class 'int'>": int,
    "<class 'float'>": float,
    "<class 'list'>": list,
    "<class 'tuple'>": tuple,
    "<class 'dict'>": dict
}


class CredentialsInterface(ABC):
    """
    Abstract Base Class for handling credentials and environment variables.
    This class provides methods to process and validate credentials, as well as
    retrieve values from environment variables or configuration files.
    """
    _credentials: dict = {"username": str, "password": str}

    def __init__(self, *args, **kwargs) -> None:
        # if credentials:
        self.credentials: dict = kwargs.pop('credentials', None)
        self._no_warnings = kwargs.get("no_warnings", False)
        if expected := kwargs.pop("expected_credentials", None):
            self._credentials = expected
        self._environment = config
        try:
            super().__init__(*args, **kwargs)
        except TypeError:
            super().__init__()
        # Interface not started:
        self._started: bool = False
        self.logger = logging.getLogger(__name__)

    def get_env_value(self, key, default: str = None, expected_type: object = None):
        """
        Retrieves a value from the environment variables or the configuration.

        :param key: The key for the environment variable.
        :param default: The default value to return if the key is not found.
        :return: The value of the environment variable or the default value.
        """
        if key is None:
            return default
        if expected_type is not None:
            with contextlib.suppress(TypeError):
                if expected_type in (int, float):
                    return val if (val := self._environment.getint(key)) else key
                elif expected_type == bool:
                    return val if (val := self._environment.getboolean(key)) else key
                else:
                    return val if (val := self._environment.get(key)) else key
            return default
        if val := os.getenv(str(key), default):
            return val
        return val if (val := self._environment.get(key, default)) else key

    def processing_credentials(self):
        if self.credentials:
            for key, expected_type in self._credentials.items():
                try:
                    value = self.credentials.get(key, None)
                    default = getattr(self, key, value)
                    # print('KEY ', key, 'VAL ', value, 'DEF ', default)
                    if type(value) == expected_type or isinstance(value, valid_types[str(expected_type)]):  # pylint: disable=E1136 # noqa
                        # can process the credentials, extracted from environment or variables:
                        val = self.get_env_value(
                            value, default=default, expected_type=expected_type
                        )
                        # print('VAL > ', val, 'DEFAULT > ', default, expected_type)
                        self.credentials[key] = val
                        # print('KEY: ', key, self.credentials[key])
                    elif isinstance(value, str):
                        # Use os.getenv to get the value from environment variables
                        env_value = self.get_env_value(
                            value, default=default, expected_type=expected_type
                        )
                        self.credentials[key] = env_value
                    else:
                        self.credentials[key] = default
                except KeyError as exc:
                    print(f'Failed credential {key} with value {value}: {exc}')
                    continue
                except (TypeError, ValueError) as ex:
                    self.logger.error(f"{__name__}: Wrong or missing Credentials")
                    raise RuntimeError(
                        f"{__name__}: Wrong or missing Credentials"
                    ) from ex
                except Exception as ex:
                    self.logger.exception(
                        f"Error Processing Credentials: {ex}"
                    )
                    raise RuntimeError(
                        f"Error Processing Credentials: {ex}"
                    ) from ex
        if self.credentials is None:
            if self._no_warnings is False:
                self.logger.warning(
                    "No credentials where Found."
                )
            self.credentials = {}
