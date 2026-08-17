"""Config flow for Home Consumption Analyzer.

Single-step form covering the cumulative energy balance (kWh): the
required/optional energy sensors, the two Peak Hours windows, and the two
rolling-average periods.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AVG_DAYS_1,
    CONF_AVG_DAYS_2,
    CONF_PEAK1_END,
    CONF_PEAK1_START,
    CONF_PEAK2_END,
    CONF_PEAK2_START,
    DEFAULT_AVG_DAYS_1,
    DEFAULT_AVG_DAYS_2,
    DOMAIN,
    OPTIONAL_ENERGY_KEYS,
    REQUIRED_ENERGY_KEYS,
)


def _energy_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="energy")
    )


def _days_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1, max=365, step=1, mode=selector.NumberSelectorMode.BOX
        )
    )


def _build_schema(defaults: dict | None = None) -> vol.Schema:
    """Build the config/options schema.

    IMPORTANT: optional entity fields must NOT get a `default=""` -- an
    empty string is not a valid EntitySelector value and Home Assistant's
    frontend then treats the field as if it needed a value before the form
    can be submitted. Pre-filling on re-edit is done via
    `description.suggested_value` instead, which leaves the field
    genuinely optional.
    """
    defaults = defaults or {}
    energy = _energy_selector()
    time_sel = selector.TimeSelector()
    days_sel = _days_selector()

    schema: dict = {}

    for key in REQUIRED_ENERGY_KEYS:
        if defaults.get(key):
            schema[vol.Required(key, description={"suggested_value": defaults[key]})] = energy
        else:
            schema[vol.Required(key)] = energy

    for key in OPTIONAL_ENERGY_KEYS:
        schema[vol.Optional(key, description={"suggested_value": defaults.get(key)})] = energy

    for key, default_time in (
        (CONF_PEAK1_START, "07:00:00"),
        (CONF_PEAK1_END, "22:00:00"),
        (CONF_PEAK2_START, "00:00:00"),
        (CONF_PEAK2_END, "00:00:00"),
    ):
        schema[vol.Required(key, default=defaults.get(key, default_time))] = time_sel

    schema[
        vol.Required(CONF_AVG_DAYS_1, default=defaults.get(CONF_AVG_DAYS_1, DEFAULT_AVG_DAYS_1))
    ] = days_sel
    schema[
        vol.Required(CONF_AVG_DAYS_2, default=defaults.get(CONF_AVG_DAYS_2, DEFAULT_AVG_DAYS_2))
    ] = days_sel

    return vol.Schema(schema)


def _clean(user_input: dict) -> dict:
    """Drop empty/unset optional selections so they read as 'not configured'."""
    return {k: v for k, v in user_input.items() if v not in ("", None)}


class HomeConsumptionAnalyzerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Home Consumption Analyzer."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(
                title="Home Consumption Analyzer", data=_clean(user_input)
            )

        return self.async_show_form(
            step_id="user", data_schema=_build_schema(), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HomeConsumptionAnalyzerOptionsFlow(config_entry)


class HomeConsumptionAnalyzerOptionsFlow(config_entries.OptionsFlow):
    """Re-edit the energy balance sensors, time windows, and averages."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            cleaned = _clean(user_input)
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=cleaned
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init", data_schema=_build_schema(dict(self._config_entry.data))
        )
