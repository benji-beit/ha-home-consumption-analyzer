"""Sensor platform for Home Consumption Analyzer.

Household consumption is reconstructed from configured cumulative energy
meters using the balance at the electrical panel:

    consumption = PV production (all inverters)
                + grid import (T1 + T2)
                + battery discharge (all batteries)
                - grid export (T1 + T2)
                - battery charge (all batteries)

Each time a source sensor reports a new value, the incremental delta since
its previous reading is computed (handling meter resets the same way Home
Assistant's own `total_increasing` statistics engine does: a decrease is
treated as a reset and the new value is counted as the increase), signed,
and fed into the total / daily / peak-window / peak-window-daily counters
below. Two rolling averages (in days) per peak window are derived from a
persisted history of completed days.
"""
from __future__ import annotations

import logging
from datetime import time as dt_time, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

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
    SOURCE_SIGNS,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
MAX_HISTORY_DAYS = 400


def _parse_time(value: str) -> dt_time:
    parts = (value.split(":") + ["0", "0"])[:3]
    hour, minute, second = (int(p) for p in parts)
    return dt_time(hour, minute, second)


def _in_window(now: dt_time, start: dt_time, end: dt_time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= now < end
    # window crosses midnight, e.g. 22:00 -> 06:00
    return now >= start or now < end


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Home Consumption Analyzer",
        manufacturer="benji-beit",
        model="Household energy balance",
    )


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    history_1 = PeakHistoryStore(hass, entry.entry_id, 1)
    history_2 = PeakHistoryStore(hass, entry.entry_id, 2)
    await history_1.async_load()
    await history_2.async_load()

    days_1 = int(entry.data.get(CONF_AVG_DAYS_1, DEFAULT_AVG_DAYS_1))
    days_2 = int(entry.data.get(CONF_AVG_DAYS_2, DEFAULT_AVG_DAYS_2))

    entities: list[SensorEntity] = [
        TotalConsumptionSensor(hass, entry),
        PeakWindowConsumptionSensor(hass, entry, 1),
        PeakWindowConsumptionSensor(hass, entry, 2),
        DailyConsumptionSensor(hass, entry),
        PeakWindowDailyConsumptionSensor(hass, entry, 1, history_1),
        PeakWindowDailyConsumptionSensor(hass, entry, 2, history_2),
        PeakWindowAverageSensor(hass, entry, 1, days_1, history_1),
        PeakWindowAverageSensor(hass, entry, 1, days_2, history_1),
        PeakWindowAverageSensor(hass, entry, 2, days_1, history_2),
        PeakWindowAverageSensor(hass, entry, 2, days_2, history_2),
    ]
    async_add_entities(entities)


# ---------------------------------------------------------------------------
# 1. Cumulative energy balance (kWh)
# ---------------------------------------------------------------------------


class PeakHistoryStore:
    """Persists the completed-day totals for one peak window.

    Backed by Home Assistant's storage helper (JSON file under
    `.storage/`), independent of entity state restore, so the rolling
    averages survive restarts even before the daily sensor's first
    midnight rollover after a restart.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str, window_number: int) -> None:
        self._store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_peak{window_number}_history"
        )
        self.days: list[dict] = []

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.days = (data or {}).get("days", [])

    async def async_add_day(self, date_str: str, value: float) -> None:
        self.days.append({"date": date_str, "value": round(value, 3)})
        self.days = self.days[-MAX_HISTORY_DAYS:]
        await self._store.async_save({"days": self.days})

    def average(self, n_days: int) -> float | None:
        if not self.days:
            return None
        subset = self.days[-n_days:]
        if not subset:
            return None
        return sum(d["value"] for d in subset) / len(subset)


class _BaseConsumptionSensor(RestoreEntity, SensorEntity):
    """Common accumulation logic shared by all derived consumption sensors."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_should_poll = False
    _id_suffix = "base"  # overridden by subclasses

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._value: float = 0.0
        self._last_raw: dict[str, float] = {}
        self._tracked: dict[str, int] = {
            entry.data[key]: sign
            for key, sign in SOURCE_SIGNS.items()
            if entry.data.get(key)
        }
        self._attr_unique_id = f"{entry.entry_id}_hca_{self._id_suffix}"
        self.entity_id = f"sensor.hca_{self._id_suffix}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float:
        return round(self._value, 3)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                self._value = float(last_state.state)
            except ValueError:
                self._value = 0.0

        for entity_id in self._tracked:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state not in ("unknown", "unavailable"):
                try:
                    self._last_raw[entity_id] = float(state.state)
                except ValueError:
                    pass

        if self._tracked:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, list(self._tracked), self._handle_source_event
                )
            )

    @callback
    def _handle_source_event(self, event) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return

        try:
            new_val = float(new_state.state)
        except ValueError:
            return

        old_val = self._last_raw.get(entity_id)
        self._last_raw[entity_id] = new_val

        if old_val is None:
            return

        delta = (new_val - old_val) if new_val >= old_val else new_val
        if delta <= 0:
            return

        sign = self._tracked.get(entity_id)
        if sign is None:
            return

        self._on_delta(sign * delta)

    def _on_delta(self, signed_delta: float) -> None:
        self._value = max(0.0, self._value + signed_delta)
        self.async_write_ha_state()


class TotalConsumptionSensor(_BaseConsumptionSensor):
    """Lifetime (since integration setup) household consumption."""

    _attr_name = "Total Household Consumption"
    _attr_icon = "mdi:home-lightning-bolt"
    _id_suffix = "total"


class DailyConsumptionSensor(_BaseConsumptionSensor):
    """Household consumption, reset every day at local midnight."""

    _attr_name = "Daily Household Consumption"
    _attr_icon = "mdi:calendar-today"
    _attr_state_class = SensorStateClass.TOTAL
    _id_suffix = "daily"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_midnight_reset, hour=0, minute=0, second=0
            )
        )

    @callback
    def _handle_midnight_reset(self, now) -> None:
        self._value = 0.0
        self.async_write_ha_state()


class PeakWindowConsumptionSensor(_BaseConsumptionSensor):
    """Lifetime household consumption accumulated only during a peak-hours window."""

    _attr_icon = "mdi:clock-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, window_number: int) -> None:
        if window_number == 1:
            self._start_key, self._end_key = CONF_PEAK1_START, CONF_PEAK1_END
        else:
            self._start_key, self._end_key = CONF_PEAK2_START, CONF_PEAK2_END
        self._attr_name = f"Peak Window {window_number} Consumption"
        self._id_suffix = f"peak{window_number}_total"
        super().__init__(hass, entry)

    def _on_delta(self, signed_delta: float) -> None:
        start = _parse_time(self._entry.data[self._start_key])
        end = _parse_time(self._entry.data[self._end_key])
        now = dt_util.now().time()
        if not _in_window(now, start, end):
            return
        self._value = max(0.0, self._value + signed_delta)
        self.async_write_ha_state()


class PeakWindowDailyConsumptionSensor(_BaseConsumptionSensor):
    """Household consumption during a peak-hours window, reset at local midnight."""

    _attr_icon = "mdi:calendar-clock"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        window_number: int,
        history_store: PeakHistoryStore,
    ) -> None:
        self._window_number = window_number
        self._history_store = history_store
        if window_number == 1:
            self._start_key, self._end_key = CONF_PEAK1_START, CONF_PEAK1_END
        else:
            self._start_key, self._end_key = CONF_PEAK2_START, CONF_PEAK2_END
        self._attr_name = f"Peak Window {window_number} Daily Consumption"
        self._id_suffix = f"peak{window_number}_daily"
        super().__init__(hass, entry)

    def _on_delta(self, signed_delta: float) -> None:
        start = _parse_time(self._entry.data[self._start_key])
        end = _parse_time(self._entry.data[self._end_key])
        now = dt_util.now().time()
        if not _in_window(now, start, end):
            return
        self._value = max(0.0, self._value + signed_delta)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_midnight_reset, hour=0, minute=0, second=0
            )
        )

    @callback
    def _handle_midnight_reset(self, now) -> None:
        completed_day_value = self._value
        completed_date = (dt_util.now() - timedelta(days=1)).date().isoformat()
        self.hass.async_create_task(
            self._history_store.async_add_day(completed_date, completed_day_value)
        )
        self._value = 0.0
        self.async_write_ha_state()


class PeakWindowAverageSensor(SensorEntity):
    """Rolling average of the last N completed days for a peak window."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False
    _attr_icon = "mdi:chart-line"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        window_number: int,
        days: int,
        history_store: PeakHistoryStore,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._days = days
        self._history_store = history_store
        self._attr_name = f"Peak Window {window_number} Average Consumption ({days}d)"
        suffix = f"peak{window_number}_avg_{days}d"
        self._attr_unique_id = f"{entry.entry_id}_hca_{suffix}"
        self.entity_id = f"sensor.hca_{suffix}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        avg = self._history_store.average(self._days)
        return round(avg, 3) if avg is not None else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_recompute, hour=0, minute=0, second=5
            )
        )

    @callback
    def _handle_recompute(self, now) -> None:
        self.async_write_ha_state()

