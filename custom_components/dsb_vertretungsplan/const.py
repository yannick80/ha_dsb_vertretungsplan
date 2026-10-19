"""Constants for the DSB Vertretungsplan integration."""

from __future__ import annotations

DOMAIN = "dsb_vertretungsplan"

CONF_DAYS_AHEAD = "days_ahead"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

DEFAULT_DAYS_AHEAD = 3
MIN_DAYS_AHEAD = 1
MAX_DAYS_AHEAD = 14
DEFAULT_SCAN_INTERVAL_MINUTES = 30
MIN_SCAN_INTERVAL_MINUTES = 5
MAX_SCAN_INTERVAL_MINUTES = 24 * 60

ATTR_DATE = "date"
ATTR_DAY_LABEL = "day_label"
ATTR_ENTRIES = "entries"
ATTR_DAYS = "days"
ATTR_INFO = "info"
ATTR_PLAN_DAYS = "plan_days"
ATTR_PLANS = "plans"
ATTR_NEWS = "news"
ATTR_DOCUMENTS = "documents"
ATTR_DAYS_AHEAD = "days_ahead"

SERVICE_GET_ENTRIES = "get_entries"
ATTR_CLASS = "class_name"
ATTR_CONFIG_ENTRY = "config_entry"

MANUFACTURER = "heinekingmedia GmbH"
MODEL_ACCOUNT = "DSBmobile Zugang"
