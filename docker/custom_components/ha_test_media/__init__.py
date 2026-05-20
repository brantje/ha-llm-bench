"""HA Test Media Player — simulated media_player for conversational benchmarks."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up ha_test_media from configuration.yaml."""
    if DOMAIN not in config:
        return True

    hass.data.setdefault(DOMAIN, config[DOMAIN])

    await discovery.async_load_platform(
        hass,
        "media_player",
        DOMAIN,
        config[DOMAIN],
        config,
    )
    return True
