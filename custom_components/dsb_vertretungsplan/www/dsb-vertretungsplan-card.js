/**
 * DSB Vertretungsplan Card
 *
 * Lovelace card for the dsb_vertretungsplan integration. Shows the
 * substitution entries of one class for the coming days, read from the
 * school-wide sensor. Two cards with different classes share one sensor and
 * therefore one data fetch.
 *
 * The card is served by the integration itself; no manual resource entry
 * is needed. Vanilla web components, no build step, no dependencies.
 */

const CARD_TAG = "dsb-vertretungsplan-card";
const EDITOR_TAG = "dsb-vertretungsplan-card-editor";
const CARD_VERSION = "1.2.2";

const CLASS_RE = /^(\d{1,2})([a-zäöü]*)$/;
const WEEKDAYS = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];

// Colour per "Art" (type). Keys are matched case-insensitively by prefix so
// that "Raum-Vtr." and "Raumvertretung" both hit "raum".
const TYPE_STYLES = [
  { match: ["entfall", "entfällt", "ausfall"], color: "var(--error-color, #db4437)", icon: "mdi:close-circle-outline" },
  { match: ["vertretung", "vertr", "sondereins"], color: "var(--info-color, #4285f4)", icon: "mdi:account-switch-outline" },
  { match: ["verlegung", "verleg", "tausch"], color: "var(--warning-color, #ffa600)", icon: "mdi:swap-horizontal" },
  { match: ["raum"], color: "#ff7043", icon: "mdi:door-open" },
  { match: ["betreuung", "aufsicht"], color: "var(--success-color, #43a047)", icon: "mdi:account-child-outline" },
  { match: ["statt", "ersatz"], color: "#8e24aa", icon: "mdi:book-open-variant" },
  { match: ["klausur", "prüfung"], color: "#5c6bc0", icon: "mdi:file-document-edit-outline" },
];
const DEFAULT_STYLE = { color: "var(--secondary-text-color, #727272)", icon: "mdi:information-outline" };

function normalizeClass(value) {
  const v = String(value || "").trim().toLowerCase();
  const m = CLASS_RE.exec(v);
  if (!m) return v;
  return `${m[1].padStart(2, "0")}${m[2]}`;
}

/** Parse "5", "5 - 6", "5-6", "5./6." into [first, last] or null. */
function lessonRange(lesson) {
  const nums = String(lesson || "").match(/\d+/g);
  if (!nums || nums.length === 0) return null;
  const first = parseInt(nums[0], 10);
  const last = parseInt(nums[nums.length - 1], 10);
  return last >= first ? [first, last] : [last, first];
}

function sameSubstitution(a, b) {
  const fields = ["type", "classes", "subject", "room", "substitute", "teacher", "text"];
  if (fields.some((f) => String(a[f] || "") !== String(b[f] || ""))) return false;
  return JSON.stringify(a.changes || {}) === JSON.stringify(b.changes || {});
}

/**
 * Merge consecutive lessons with identical content ("5. Std En", "6. Std En")
 * into one row ("5-6"). Entries are expected in lesson order per day.
 */
function mergeConsecutive(entries) {
  const result = [];
  for (const entry of entries) {
    const range = lessonRange(entry.lesson);
    const last = result[result.length - 1];
    if (last && range && last._range && sameSubstitution(last, entry) && range[0] === last._range[1] + 1) {
      last._range = [last._range[0], range[1]];
      last.lesson = `${last._range[0]}-${last._range[1]}`;
      continue;
    }
    result.push({ ...entry, _range: range, lesson: range ? (range[0] === range[1] ? String(range[0]) : `${range[0]}-${range[1]}`) : entry.lesson });
  }
  return result;
}

function typeStyle(type) {
  const t = String(type || "").toLowerCase();
  for (const style of TYPE_STYLES) {
    if (style.match.some((m) => t.startsWith(m) || t.includes(m))) return style;
  }
  return DEFAULT_STYLE;
}

function escapeHtml(value) {
  return String(value === null || value === undefined ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** True once the local clock has passed "HH:MM" (empty string = never). */
function pastTime(hhmm) {
  const m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm || "").trim());
  if (!m) return false;
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  return minutes >= parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

function relativeLabel(isoDate) {
  const today = new Date(localToday());
  const day = new Date(isoDate);
  const diff = Math.round((day - today) / 86400000);
  if (diff === 0) return "Heute";
  if (diff === 1) return "Morgen";
  if (diff === 2) return "Übermorgen";
  return "";
}

function formatDay(isoDate, label) {
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return label || isoDate;
  const weekday = WEEKDAYS[d.getDay()];
  return `${weekday}, ${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`;
}

function changeMarkup(entry, field) {
  const value = entry[field];
  const old = entry.changes && entry.changes[field];
  if (!value && !old) return "";
  if (old && value) return `<s>${escapeHtml(old)}</s> ${escapeHtml(value)}`;
  if (old && !value) return `<s>${escapeHtml(old)}</s>`;
  return escapeHtml(value);
}

const CARD_STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .header {
    display: flex; align-items: center; gap: 12px;
    padding: 16px 16px 8px 16px;
  }
  .header .icon {
    width: 40px; height: 40px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: var(--state-icon-color, var(--primary-color));
    color: var(--text-primary-color, #fff);
    flex: none;
  }
  .header .icon ha-icon { --mdc-icon-size: 22px; }
  .header .titles { flex: 1; min-width: 0; }
  .header .title { font-size: 1.1em; font-weight: 500; line-height: 1.3; }
  .header .subtitle { color: var(--secondary-text-color); font-size: 0.9em; }
  .badge {
    flex: none; min-width: 28px; height: 28px; padding: 0 9px; border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 0.9em;
    background: var(--success-color, #43a047); color: #fff;
  }
  .badge.alert { background: var(--error-color, #db4437); }
  .badge.muted { background: var(--disabled-color, #bdbdbd); }
  .day { padding: 4px 16px 10px 16px; }
  .day + .day { border-top: 1px solid var(--divider-color); padding-top: 10px; }
  .day-head {
    display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px;
  }
  .day-head .name { font-weight: 500; }
  .day-head .rel {
    font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--primary-color); font-weight: 600;
  }
  .day-head .count { margin-left: auto; color: var(--secondary-text-color); font-size: 0.85em; }
  .empty {
    display: flex; align-items: center; gap: 8px;
    color: var(--secondary-text-color); font-size: 0.95em; padding: 2px 0 2px 2px;
  }
  .empty ha-icon { --mdc-icon-size: 18px; color: var(--success-color, #43a047); }
  .row {
    display: grid; grid-template-columns: 44px 1fr; gap: 10px; align-items: start;
    padding: 6px 0;
  }
  .row + .row { border-top: 1px dashed var(--divider-color); }
  .lesson {
    border-radius: 8px; padding: 6px 0; text-align: center; font-weight: 600;
    background: var(--secondary-background-color); line-height: 1.1; font-size: 0.95em;
  }
  .lesson small { display: block; font-weight: 400; font-size: 0.7em; color: var(--secondary-text-color); }
  .main { min-width: 0; }
  .line1 { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; }
  .chip {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 8px; border-radius: 10px; font-size: 0.78em; font-weight: 600;
    color: #fff; white-space: nowrap;
  }
  .chip ha-icon { --mdc-icon-size: 14px; }
  .subject { font-weight: 500; }
  .line2 {
    display: flex; flex-wrap: wrap; gap: 4px 14px;
    color: var(--secondary-text-color); font-size: 0.88em; margin-top: 3px;
  }
  .line2 span { display: inline-flex; align-items: center; gap: 4px; }
  .line2 ha-icon { --mdc-icon-size: 15px; opacity: 0.8; }
  .note { margin-top: 3px; font-size: 0.88em; font-style: italic; }
  s { opacity: 0.6; }
  .info {
    display: flex; gap: 8px; align-items: flex-start;
    margin: 6px 0 2px 0; padding: 8px 10px; border-radius: 8px;
    background: var(--secondary-background-color); font-size: 0.88em;
  }
  .info ha-icon { --mdc-icon-size: 16px; flex: none; margin-top: 1px; color: var(--primary-color); }
  .warning {
    display: flex; gap: 8px; align-items: center;
    margin: 0 16px 16px 16px; padding: 10px 12px; border-radius: 8px;
    background: rgba(219, 68, 55, 0.12); color: var(--error-color, #db4437);
  }
  .footer {
    padding: 6px 16px 12px 16px; color: var(--secondary-text-color); font-size: 0.75em;
  }
  .compact .row { padding: 4px 0; }
  .compact .line2, .compact .note { display: none; }
`;

class DsbVertretungsplanCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  static getStubConfig(hass) {
    const states = (hass && hass.states) || {};
    const entity = Object.keys(states).find(
      (id) => id.startsWith("sensor.") && states[id].attributes && states[id].attributes.days_ahead !== undefined,
    );
    return { entity: entity || "", class: "", show_empty_days: true, show_info: true };
  }

  constructor() {
    super();
    this._requestId = 0;
    this._data = null;
    this._error = null;
    this._timer = null;
    this._todayHidden = false;
  }

  connectedCallback() {
    // Re-render once a minute so that hide_today_after (and the "Heute"
    // labels after midnight) take effect without a page reload.
    if (!this._timer) {
      this._timer = setInterval(() => {
        if (this._config && this._todayHidden !== this._hideToday()) this._render();
      }, 60 * 1000);
    }
  }

  disconnectedCallback() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  _hideToday() {
    return pastTime(this._config && this._config.hide_today_after);
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Bitte den Sensor „Vertretungsplan“ als entity angeben.");
    }
    this._config = {
      class: "",
      title: "",
      days: 0,
      show_empty_days: true,
      show_info: true,
      show_footer: true,
      compact: false,
      merge_lessons: true,
      ...config,
    };
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._data = null;
    this._render();
    this._fetch();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass && hass.states && this._config ? hass.states[this._config.entity] : undefined;
    if (state !== this._state) {
      this._state = state;
      this._render();
      this._fetch();
    }
  }

  async _fetch() {
    const cfg = this._config;
    const state = this._state;
    if (!this._hass || !state || state.state === "unavailable" || state.state === "unknown") {
      this._data = null;
      return;
    }
    const request = ++this._requestId;
    try {
      const msg = { type: "dsb_vertretungsplan/entries", entity_id: cfg.entity, class_name: cfg.class || "" };
      if (cfg.days > 0) msg.days_ahead = cfg.days;
      const data = await this._hass.callWS(msg);
      if (request !== this._requestId) return;
      this._data = data;
      this._error = null;
    } catch (err) {
      if (request !== this._requestId) return;
      this._data = null;
      this._error = (err && err.message) || String(err);
    }
    this._render();
  }

  getCardSize() {
    const days = this._days();
    return 1 + days.reduce((n, d) => n + 1 + d.entries.length, 0);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 2 };
  }

  _days() {
    if (!this._data || !this._config) return [];
    let days = Array.isArray(this._data.days) ? this._data.days : [];
    days = days.map((d) => ({
      ...d,
      entries: Array.isArray(d.entries) ? d.entries : [],
      info: Array.isArray(d.info) ? d.info : [],
    }));
    if (!this._hideToday()) return days;
    const today = localToday();
    return days.filter((d) => d.date !== today);
  }

  _render() {
    try {
      this._renderUnsafe();
    } catch (err) {
      if (!this.shadowRoot) return;
      const message = (err && err.message) || String(err);
      this.shadowRoot.innerHTML = `<style>${CARD_STYLE}</style><ha-card>
        <div class="warning" style="margin:16px"><ha-icon icon="mdi:bug-outline"></ha-icon>
        <div>Fehler in der Karte: ${escapeHtml(message)}</div></div></ha-card>`;
      console.error("dsb-vertretungsplan-card render failed", err);
    }
  }

  _renderUnsafe() {
    if (!this.shadowRoot || !this._config) return;
    const cfg = this._config;
    const state = this._state;
    const klasse = String(cfg.class || "").trim();
    const title = cfg.title || (klasse ? `Klasse ${klasse}` : "Vertretungsplan");

    let body = "";
    let badge = "";
    let subtitle = "";

    if (!state) {
      body = `<div class="warning"><ha-icon icon="mdi:help-circle-outline"></ha-icon>
        <div>Entität <code>${escapeHtml(cfg.entity)}</code> nicht gefunden.</div></div>`;
      badge = `<div class="badge muted">?</div>`;
    } else if (state.state === "unavailable" || state.state === "unknown") {
      body = `<div class="warning"><ha-icon icon="mdi:cloud-off-outline"></ha-icon>
        <div>DSBmobile ist gerade nicht erreichbar.</div></div>`;
      badge = `<div class="badge muted">–</div>`;
    } else if (this._error) {
      body = `<div class="warning"><ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div>Daten konnten nicht geladen werden: ${escapeHtml(this._error)}</div></div>`;
      badge = `<div class="badge muted">!</div>`;
    } else if (!this._data) {
      body = `<div class="day"><div class="empty"><ha-icon icon="mdi:timer-sand"></ha-icon>Lade …</div></div>`;
      badge = `<div class="badge muted">…</div>`;
    } else {
      const days = this._days();
      this._todayHidden = this._hideToday();
      const total = days.reduce((n, d) => n + d.entries.length, 0);
      badge = `<div class="badge ${total > 0 ? "alert" : ""}">${total}</div>`;
      subtitle = total === 0 ? "Keine Vertretungen" : total === 1 ? "1 Vertretung" : `${total} Vertretungen`;
      if (days.length === 0) {
        const hadToday = this._todayHidden && Array.isArray(this._data.days) && this._data.days.length > 0;
        body = `<div class="day"><div class="empty"><ha-icon icon="mdi:calendar-blank-outline"></ha-icon>
          ${hadToday ? "Heute ausgeblendet, kein weiterer Plantag." : "Kein Plan veröffentlicht."}</div></div>`;
      } else {
        body = days
          .filter((d) => d.entries.length > 0 || cfg.show_empty_days || (cfg.show_info && d.info && d.info.length))
          .map((d) => this._renderDay(d))
          .join("");
      }
      const known = Array.isArray(this._data.classes) ? this._data.classes : [];
      if (total === 0 && klasse && known.length > 0 && !known.includes(normalizeClass(klasse))) {
        body += `<div class="info" style="margin:0 16px 12px 16px"><ha-icon icon="mdi:help-circle-outline"></ha-icon>
          <div>Für „${escapeHtml(klasse)}“ gibt es keine Einträge. Klassen im Plan: ${escapeHtml(known.join(", "))}</div></div>`;
      }
      if (cfg.show_footer) {
        const raw = this._data.plan_updated;
        const stamp = raw && !Number.isNaN(Date.parse(raw))
          ? new Date(raw).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" })
          : "";
        if (stamp) body += `<div class="footer">Planstand ${escapeHtml(stamp)}</div>`;
      }
    }

    this.shadowRoot.innerHTML = `
      <style>${CARD_STYLE}</style>
      <ha-card class="${cfg.compact ? "compact" : ""}">
        <div class="header">
          <div class="icon"><ha-icon icon="${escapeHtml(cfg.icon || "mdi:school-outline")}"></ha-icon></div>
          <div class="titles">
            <div class="title">${escapeHtml(title)}</div>
            ${subtitle ? `<div class="subtitle">${escapeHtml(subtitle)}</div>` : ""}
          </div>
          ${badge}
        </div>
        ${body}
      </ha-card>`;
  }

  _renderDay(day) {
    const cfg = this._config;
    const rel = relativeLabel(day.date);
    const infos = cfg.show_info && Array.isArray(day.info) ? day.info : [];
    const entries = cfg.merge_lessons === false ? day.entries : mergeConsecutive(day.entries);
    const rows = entries.map((e) => this._renderEntry(e)).join("");
    const empty = day.entries.length === 0
      ? `<div class="empty"><ha-icon icon="mdi:check-circle-outline"></ha-icon>Keine Vertretungen</div>`
      : "";
    return `
      <div class="day">
        <div class="day-head">
          <span class="name">${escapeHtml(formatDay(day.date, day.day_label))}</span>
          ${rel ? `<span class="rel">${rel}</span>` : ""}
          ${day.entries.length ? `<span class="count">${day.entries.length}</span>` : ""}
        </div>
        ${infos.map((t) => `<div class="info"><ha-icon icon="mdi:information-outline"></ha-icon><div>${escapeHtml(t)}</div></div>`).join("")}
        ${empty}${rows}
      </div>`;
  }

  _renderEntry(e) {
    const style = typeStyle(e.type);
    const lesson = escapeHtml(e.lesson || "–");
    const subject = changeMarkup(e, "subject");
    const room = changeMarkup(e, "room");
    const teacher = changeMarkup(e, "teacher");
    const substitute = escapeHtml(e.substitute || "");
    const showClasses = !this._config.class && e.classes;
    const details = [
      room ? `<span><ha-icon icon="mdi:door"></ha-icon>${room}</span>` : "",
      substitute ? `<span><ha-icon icon="mdi:account-arrow-right-outline"></ha-icon>${substitute}</span>` : "",
      teacher ? `<span><ha-icon icon="mdi:account-outline"></ha-icon>${teacher}</span>` : "",
      showClasses ? `<span><ha-icon icon="mdi:account-group-outline"></ha-icon>${escapeHtml(e.classes)}</span>` : "",
    ].filter(Boolean).join("");
    return `
      <div class="row">
        <div class="lesson">${lesson}<small>Std.</small></div>
        <div class="main">
          <div class="line1">
            <span class="chip" style="background:${style.color}"><ha-icon icon="${style.icon}"></ha-icon>${escapeHtml(e.type || "Änderung")}</span>
            ${subject ? `<span class="subject">${subject}</span>` : ""}
          </div>
          ${details ? `<div class="line2">${details}</div>` : ""}
          ${e.text ? `<div class="note">${escapeHtml(e.text)}</div>` : ""}
        </div>
      </div>`;
  }
}

const EDITOR_SCHEMA = [
  {
    name: "entity",
    required: true,
    selector: { entity: { domain: "sensor", integration: "dsb_vertretungsplan" } },
  },
  { name: "class", selector: { text: {} } },
  { name: "title", selector: { text: {} } },
  {
    type: "grid",
    name: "",
    schema: [
      { name: "days", selector: { number: { min: 0, max: 14, mode: "box" } } },
      { name: "hide_today_after", selector: { time: {} } },
      { name: "icon", selector: { icon: {} } },
    ],
  },
  {
    type: "grid",
    name: "",
    schema: [
      { name: "show_empty_days", selector: { boolean: {} } },
      { name: "show_info", selector: { boolean: {} } },
      { name: "show_footer", selector: { boolean: {} } },
      { name: "compact", selector: { boolean: {} } },
      { name: "merge_lessons", selector: { boolean: {} } },
    ],
  },
];

const EDITOR_LABELS = {
  entity: "Sensor „Vertretungsplan“",
  class: "Klasse (z. B. 08b, leer = alle)",
  title: "Titel (leer = „Klasse …“)",
  days: "Tage (0 = wie Integration)",
  hide_today_after: "Heute ausblenden ab (Uhrzeit)",
  icon: "Icon",
  show_empty_days: "Tage ohne Einträge zeigen",
  show_info: "Tageshinweise zeigen",
  show_footer: "Planstand zeigen",
  compact: "Kompakt",
  merge_lessons: "Folgestunden zusammenfassen",
};

class DsbVertretungsplanCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) => EDITOR_LABELS[schema.name] || schema.name;
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        const value = { ...ev.detail.value };
        Object.keys(value).forEach((k) => {
          if (value[k] === "" || value[k] === undefined) delete value[k];
        });
        this._config = value;
        this.dispatchEvent(
          new CustomEvent("config-changed", { detail: { config: value }, bubbles: true, composed: true }),
        );
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = {
      show_empty_days: true,
      show_info: true,
      show_footer: true,
      compact: false,
      merge_lessons: true,
      ...this._config,
    };
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, DsbVertretungsplanCard);
  customElements.define(EDITOR_TAG, DsbVertretungsplanCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TAG,
    name: "DSB Vertretungsplan",
    description: "Vertretungen einer Klasse für die kommenden Tage (Integration DSB Vertretungsplan).",
    preview: true,
    documentationURL: "https://github.com/yann-karl/dsb_vertretungsplan",
  });
  console.info(`%c DSB-VERTRETUNGSPLAN-CARD %c ${CARD_VERSION} `, "background:#1b2838;color:#fff;font-weight:bold", "background:#ffa600;color:#000");
}
