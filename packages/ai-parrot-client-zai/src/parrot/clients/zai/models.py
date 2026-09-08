from enum import Enum


class ZaiModel(str, Enum):
    """Z.ai GLM chat model identifiers.

    The ``*_FREE`` variants use Z.ai's documented ``:free`` model suffix for
    free-tier text/vision models.
    """

    GLM_5_2 = "glm-5.2"
    GLM_5_1 = "glm-5.1"
    GLM_5 = "glm-5"
    GLM_5_TURBO = "glm-5-turbo"
    GLM_5V_TURBO = "glm-5v-turbo"
    GLM_4_7 = "glm-4.7"
    GLM_4_7_FLASHX = "glm-4.7-flashx"
    GLM_4_6 = "glm-4.6"
    GLM_4_6V = "glm-4.6v"
    GLM_4_6V_FLASHX = "glm-4.6v-flashx"
    GLM_4_6V_FLASH = "glm-4.6v-flash"
    GLM_4_5 = "glm-4.5"
    GLM_4_5_X = "glm-4.5-x"
    GLM_4_5_AIR = "glm-4.5-air"
    GLM_4_5_AIRX = "glm-4.5-airx"
    GLM_4_5_FLASH = "glm-4.5-flash"
    GLM_4_5V = "glm-4.5v"
    GLM_4_32B_0414_128K = "glm-4-32b-0414-128k"

    GLM_4_7_FLASH_FREE = "glm-4.7-flash:free"
    GLM_4_5_FLASH_FREE = "glm-4.5-flash:free"
    GLM_4_6V_FLASH_FREE = "glm-4.6v-flash:free"


THINKING_CAPABLE_ZAI_MODELS = frozenset(
    {
        ZaiModel.GLM_5_2.value,
        ZaiModel.GLM_5_1.value,
        ZaiModel.GLM_5.value,
        ZaiModel.GLM_5_TURBO.value,
        ZaiModel.GLM_5V_TURBO.value,
        ZaiModel.GLM_4_7.value,
        ZaiModel.GLM_4_6.value,
        ZaiModel.GLM_4_6V.value,
        ZaiModel.GLM_4_6V_FLASHX.value,
        ZaiModel.GLM_4_6V_FLASH.value,
        ZaiModel.GLM_4_5.value,
        ZaiModel.GLM_4_5_X.value,
        ZaiModel.GLM_4_5_AIR.value,
        ZaiModel.GLM_4_5_AIRX.value,
        ZaiModel.GLM_4_5_FLASH.value,
        ZaiModel.GLM_4_5V.value,
        ZaiModel.GLM_4_5_FLASH_FREE.value,
        ZaiModel.GLM_4_6V_FLASH_FREE.value,
    }
)
