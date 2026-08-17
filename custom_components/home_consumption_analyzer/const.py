"""Constants for the Home Consumption Analyzer integration."""

DOMAIN = "home_consumption_analyzer"

# --- Config keys: cumulative energy (kWh) sources for the energy balance ---
CONF_EXPORT_T1 = "export_grid_t1"
CONF_EXPORT_T2 = "export_grid_t2"
CONF_IMPORT_T1 = "import_grid_t1"
CONF_IMPORT_T2 = "import_grid_t2"

CONF_PV_1 = "pv_inverter_1"
CONF_PV_2 = "pv_inverter_2"
CONF_PV_3 = "pv_inverter_3"

CONF_BATT_CHARGE_1 = "battery_charge_1"
CONF_BATT_CHARGE_2 = "battery_charge_2"
CONF_BATT_CHARGE_3 = "battery_charge_3"

CONF_BATT_DISCHARGE_1 = "battery_discharge_1"
CONF_BATT_DISCHARGE_2 = "battery_discharge_2"
CONF_BATT_DISCHARGE_3 = "battery_discharge_3"

CONF_EV_CHARGE = "ev_charge"

# --- Config keys: "peak hours" time windows ---
CONF_PEAK1_START = "peak1_start"
CONF_PEAK1_END = "peak1_end"
CONF_PEAK2_START = "peak2_start"
CONF_PEAK2_END = "peak2_end"

# --- Config keys: rolling-average windows (in days) for each peak window ---
CONF_AVG_DAYS_1 = "avg_days_1"
CONF_AVG_DAYS_2 = "avg_days_2"

DEFAULT_AVG_DAYS_1 = 15
DEFAULT_AVG_DAYS_2 = 30

REQUIRED_ENERGY_KEYS = (CONF_EXPORT_T1, CONF_IMPORT_T1, CONF_PV_1)

OPTIONAL_ENERGY_KEYS = (
    CONF_EXPORT_T2,
    CONF_IMPORT_T2,
    CONF_PV_2,
    CONF_PV_3,
    CONF_BATT_CHARGE_1,
    CONF_BATT_CHARGE_2,
    CONF_BATT_CHARGE_3,
    CONF_BATT_DISCHARGE_1,
    CONF_BATT_DISCHARGE_2,
    CONF_BATT_DISCHARGE_3,
    CONF_EV_CHARGE,
)

# Sign applied to a source's increase when folding it into the household
# energy balance:
#   consumption = PV production + grid import + battery discharge
#                 - grid export - battery charge
SOURCE_SIGNS = {
    CONF_EXPORT_T1: -1,
    CONF_EXPORT_T2: -1,
    CONF_IMPORT_T1: 1,
    CONF_IMPORT_T2: 1,
    CONF_PV_1: 1,
    CONF_PV_2: 1,
    CONF_PV_3: 1,
    CONF_BATT_CHARGE_1: -1,
    CONF_BATT_CHARGE_2: -1,
    CONF_BATT_CHARGE_3: -1,
    CONF_BATT_DISCHARGE_1: 1,
    CONF_BATT_DISCHARGE_2: 1,
    CONF_BATT_DISCHARGE_3: 1,
}

PLATFORMS = ["sensor"]
