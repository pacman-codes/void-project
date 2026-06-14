import logging

from aiohttp import web

from config.config import settings
from services.admin_miniapp_auth import (
    AdminMiniAppAuthError,
    AdminMiniAppIdentity,
    authenticate_admin_init_data,
)
from services.admin_miniapp_service import (
    get_admin_servers,
    get_admin_stats,
    get_admin_traffic_summary,
    get_admin_user_detail,
    get_admin_user_events,
    get_admin_users,
)
from services.yookassa_webhook_service import process_yookassa_notification


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


ADMIN_MINIAPP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VOID Admin</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0f14;
      --panel: #121922;
      --panel-soft: #17212b;
      --line: #263341;
      --text: #edf3f8;
      --muted: #95a3b1;
      --accent: #5dc4ff;
      --danger: #ff6b7a;
      --ok: #74d99f;
      --warn: #f0bc62;
      --radius: 8px;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    button, input, textarea {
      font: inherit;
    }

    button {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px 12px;
      background: var(--panel-soft);
      color: var(--text);
      cursor: pointer;
    }

    button.primary {
      border-color: #2e7aa4;
      background: #155f84;
    }

    button:disabled {
      cursor: default;
      opacity: 0.55;
    }

    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      background: #0f151d;
      color: var(--text);
    }

    textarea {
      min-height: 92px;
      resize: vertical;
      word-break: break-all;
    }

    .page {
      width: min(1120px, 100%);
      margin: 0 auto;
      padding: 14px;
    }

    .topbar {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      padding: 8px 0 14px;
    }

    .title {
      min-width: 0;
    }

    .title h1 {
      margin: 0;
      font-size: 22px;
      letter-spacing: 0;
    }

    .title p {
      margin: 3px 0 0;
      color: var(--muted);
      font-size: 13px;
    }

    .grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }

    .panel {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--panel);
      padding: 12px;
    }

    .panel h2 {
      margin: 0 0 10px;
      font-size: 15px;
      letter-spacing: 0;
    }

    .banner {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px 12px;
      margin-bottom: 12px;
      background: var(--panel-soft);
      white-space: pre-wrap;
    }

    .banner.ok { border-color: #2b6846; color: var(--ok); }
    .banner.error { border-color: #7a2f3b; color: var(--danger); }
    .banner.warn { border-color: #74613a; color: var(--warn); }

    .cards {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .card {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      background: var(--panel-soft);
      min-width: 0;
    }

    .card .label {
      display: block;
      color: var(--muted);
      font-size: 12px;
    }

    .card .value {
      display: block;
      margin-top: 3px;
      font-size: 19px;
      font-weight: 650;
      word-break: break-word;
    }

    .card .hint {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
      word-break: break-word;
    }

    .form-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: end;
      margin-bottom: 10px;
    }

    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 7px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 720px;
    }

    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }

    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      background: #101720;
    }

    tr:last-child td { border-bottom: 0; }

    .kv {
      display: grid;
      grid-template-columns: minmax(110px, 0.42fr) 1fr;
      gap: 8px;
      padding: 6px 0;
      border-bottom: 1px solid rgba(38, 51, 65, 0.65);
    }

    .kv:last-child { border-bottom: 0; }
    .kv .key { color: var(--muted); }
    .kv .val { min-width: 0; overflow-wrap: anywhere; }

    .stack {
      display: grid;
      gap: 8px;
    }

    .list-item {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 9px;
      background: var(--panel-soft);
    }

    pre {
      margin: 8px 0 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--muted);
    }

    details {
      margin-top: 8px;
      color: var(--muted);
    }

    details > div {
      margin-top: 8px;
      color: var(--text);
    }

    .muted { color: var(--muted); }
    .status-ok { color: var(--ok); }
    .status-bad { color: var(--danger); }

    @media (min-width: 840px) {
      .grid.two {
        grid-template-columns: 1.1fr 0.9fr;
      }

      .cards {
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }
    }
  </style>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
</head>
<body>
  <main class="page">
    <header class="topbar">
      <div class="title">
        <h1>VOID Admin</h1>
        <p>Read-only internal Mini App v0</p>
      </div>
      <button id="refreshButton" class="primary" type="button">Refresh</button>
    </header>

    <section id="authBanner" class="banner warn" hidden></section>

    <section class="panel">
      <h2>Auth</h2>
      <div id="meBlock" class="stack"></div>
      <details id="devAuthFallback">
        <summary>Local initData fallback</summary>
        <div class="stack">
          <textarea id="manualInitData" spellcheck="false" autocomplete="off" placeholder="Paste Telegram WebApp initData for local testing"></textarea>
          <button id="useManualInitData" type="button">Use pasted initData</button>
          <p class="muted">Not stored. Cleared on reload.</p>
        </div>
      </details>
    </section>

    <section class="panel">
      <h2>Stats</h2>
      <div id="statsCards" class="cards"></div>
    </section>

    <section class="grid two">
      <section class="panel">
        <h2>Users</h2>
        <form id="userSearchForm" class="form-row">
          <input id="userSearchInput" type="search" placeholder="Telegram ID or username" autocomplete="off">
          <button type="submit">Search</button>
        </form>
        <div id="usersTable"></div>
      </section>

      <section class="panel">
        <h2>Selected User</h2>
        <div id="userDetail" class="stack">
          <p class="muted">Select a user from the table.</p>
        </div>
      </section>
    </section>

    <section class="grid two">
      <section class="panel">
        <h2>Recent User Events</h2>
        <div id="eventsList" class="stack">
          <p class="muted">No user selected.</p>
        </div>
      </section>

      <section class="panel">
        <h2>Traffic Summary</h2>
        <div id="trafficSummary" class="stack"></div>
      </section>
    </section>

    <section class="panel">
      <h2>Servers</h2>
      <div id="serversBlock" class="stack"></div>
    </section>
  </main>

  <script>
    (function () {
      "use strict";

      var state = {
        initData: "",
        selectedTelegramId: null
      };

      function byId(id) {
        return document.getElementById(id);
      }

      function text(value) {
        if (value === null || value === undefined || value === "") {
          return "-";
        }
        if (typeof value === "boolean") {
          return value ? "yes" : "no";
        }
        return String(value);
      }

      function node(tag, className, value) {
        var item = document.createElement(tag);
        if (className) {
          item.className = className;
        }
        if (value !== undefined) {
          item.textContent = text(value);
        }
        return item;
      }

      function clear(element) {
        element.replaceChildren();
      }

      function setBanner(type, message) {
        var banner = byId("authBanner");
        banner.className = "banner " + type;
        banner.textContent = message || "";
        banner.hidden = !message;
      }

      function addKv(parent, label, value) {
        var row = node("div", "kv");
        row.appendChild(node("div", "key", label));
        row.appendChild(node("div", "val", value));
        parent.appendChild(row);
      }

      function addCard(parent, label, value, hint) {
        var card = node("div", "card");
        card.appendChild(node("span", "label", label));
        card.appendChild(node("span", "value", value));
        if (hint) {
          card.appendChild(node("span", "hint", hint));
        }
        parent.appendChild(card);
      }

      function getInitDataFromUrl() {
        var sources = [window.location.hash, window.location.search];

        for (var i = 0; i < sources.length; i += 1) {
          var source = sources[i] || "";
          if (!source) {
            continue;
          }

          if (source.charAt(0) === "#" || source.charAt(0) === "?") {
            source = source.slice(1);
          }

          try {
            var params = new URLSearchParams(source);
            var value = params.get("tgWebAppData");
            if (value) {
              return value;
            }
          } catch (error) {
            // Ignore malformed local/dev URLs.
          }
        }

        return "";
      }

      function getTelegramInitData() {
        var urlInitData = getInitDataFromUrl();
        var telegram = window.Telegram && window.Telegram.WebApp;

        if (!telegram) {
          return urlInitData;
        }

        try {
          if (telegram.ready) {
            telegram.ready();
          }
          if (telegram.expand) {
            telegram.expand();
          }
        } catch (error) {
          // The UI still works with URL/manual initData fallback.
        }

        return telegram.initData || urlInitData;
      }

      function authHeaders() {
        return {
          "X-Telegram-Init-Data": state.initData
        };
      }

      async function api(path) {
        if (!state.initData) {
          setBanner("warn", "Telegram initData is missing. Open from Telegram or paste initData for local testing.");
          throw new Error("missing initData");
        }

        var response = await fetch("/miniapp/admin" + path, {
          method: "GET",
          headers: authHeaders(),
          cache: "no-store",
          credentials: "same-origin"
        });

        var raw = await response.text();
        var data = {};
        if (raw) {
          try {
            data = JSON.parse(raw);
          } catch (error) {
            data = { message: raw };
          }
        }

        if (!response.ok) {
          var message = data.message || data.error || response.statusText || "Request failed";
          if (response.status === 401) {
            setBanner("error", "Authentication failed (401): " + message);
          } else if (response.status === 403) {
            setBanner("error", "Access denied (403): this Telegram ID is not allowlisted.");
          } else {
            setBanner("error", "Request failed (" + response.status + "): " + message);
          }
          throw new Error(message);
        }

        return data;
      }

      function renderMe(me) {
        var block = byId("meBlock");
        clear(block);
        addKv(block, "telegram_id", me.telegram_id);
        addKv(block, "username", me.username);
        addKv(block, "first_name", me.first_name);
        addKv(block, "last_name", me.last_name);
        addKv(block, "read_only", me.read_only);
        addKv(block, "auth_date", me.auth_date);
      }

      function renderStats(stats) {
        var cards = byId("statsCards");
        clear(cards);
        addCard(cards, "Users", stats.users && stats.users.total, "active " + text(stats.users && stats.users.active));
        addCard(cards, "Paid", stats.users && stats.users.paid, "expired " + text(stats.users && stats.users.expired_paid));
        addCard(cards, "Free", stats.users && stats.users.free, "trial " + text(stats.users && stats.users.trial));
        addCard(cards, "Access rows", stats.access && stats.access.active_access_rows, "links " + text(stats.access && stats.access.active_subscription_links));
        addCard(cards, "Traffic used", stats.traffic && stats.traffic.total_used_mb, "MB total");
        addCard(cards, "Generated", stats.generated_at, "");
      }

      function renderUsers(payload) {
        var target = byId("usersTable");
        clear(target);

        var users = payload.users || [];
        if (!users.length) {
          target.appendChild(node("p", "muted", "No users found."));
          return;
        }

        var wrap = node("div", "table-wrap");
        var table = document.createElement("table");
        var thead = document.createElement("thead");
        var headRow = document.createElement("tr");
        ["telegram_id", "username", "access", "active", "expiry", "traffic", "rows", "last event", ""].forEach(function (label) {
          headRow.appendChild(node("th", "", label));
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        var tbody = document.createElement("tbody");
        users.forEach(function (user) {
          var row = document.createElement("tr");
          row.appendChild(node("td", "", user.telegram_id));
          row.appendChild(node("td", "", user.username));
          row.appendChild(node("td", "", user.access_type));
          row.appendChild(node("td", user.is_active ? "status-ok" : "status-bad", user.is_active));
          row.appendChild(node("td", "", user.subscription_expiry));
          row.appendChild(node("td", "", text(user.traffic_used) + " / " + text(user.traffic_limit)));
          row.appendChild(node("td", "", user.active_access_row_count));
          row.appendChild(node("td", "", user.last_event ? text(user.last_event.event_type) + " " + text(user.last_event.created_at) : "-"));

          var actionCell = document.createElement("td");
          var button = node("button", "", "Open");
          button.type = "button";
          button.addEventListener("click", function () {
            selectUser(user.telegram_id);
          });
          actionCell.appendChild(button);
          row.appendChild(actionCell);
          tbody.appendChild(row);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        target.appendChild(wrap);
      }

      function renderUserDetail(detail) {
        var target = byId("userDetail");
        clear(target);

        var user = detail.user || {};
        var profile = node("div", "stack");
        addKv(profile, "telegram_id", user.telegram_id);
        addKv(profile, "username", user.username);
        addKv(profile, "name", [user.first_name, user.last_name].filter(Boolean).join(" "));
        addKv(profile, "access_type", user.access_type);
        addKv(profile, "is_active", user.is_active);
        addKv(profile, "subscription_expiry", user.subscription_expiry);
        addKv(profile, "traffic", text(user.traffic_used) + " / " + text(user.traffic_limit));
        addKv(profile, "device_limit", user.device_limit);
        addKv(profile, "created_at", user.created_at);
        target.appendChild(profile);

        var accessTitle = node("h2", "", "Active Access");
        target.appendChild(accessTitle);
        var accessList = node("div", "stack");
        (detail.active_accesses || []).forEach(function (access) {
          var item = node("div", "list-item");
          addKv(item, "server_name", access.server_name);
          addKv(item, "device_name", access.device_name);
          addKv(item, "is_active", access.is_active);
          accessList.appendChild(item);
        });
        if (!accessList.childNodes.length) {
          accessList.appendChild(node("p", "muted", "No active access rows."));
        }
        target.appendChild(accessList);

        var linksTitle = node("h2", "", "Subscription Links");
        target.appendChild(linksTitle);
        var linksBlock = node("div", "stack");
        addKv(linksBlock, "exists", detail.subscription_links && detail.subscription_links.exists);
        addKv(linksBlock, "active_count", detail.subscription_links && detail.subscription_links.active_count);
        (detail.subscription_links && detail.subscription_links.items || []).forEach(function (link) {
          var item = node("div", "list-item");
          addKv(item, "is_active", link.is_active);
          addKv(item, "token_masked", link.token_masked);
          addKv(item, "last_used_at", link.last_used_at);
          linksBlock.appendChild(item);
        });
        target.appendChild(linksBlock);
      }

      function renderEvents(payload) {
        var target = byId("eventsList");
        clear(target);

        var events = payload.events || [];
        if (!events.length) {
          target.appendChild(node("p", "muted", "No recent events."));
          return;
        }

        events.forEach(function (event) {
          var item = node("div", "list-item");
          addKv(item, "created_at", event.created_at);
          addKv(item, "event_type", event.event_type);
          addKv(item, "status", event.status);
          addKv(item, "source", event.source);
          addKv(item, "actor", event.actor_telegram_id);
          addKv(item, "message", event.message);
          if (event.details) {
            var pre = document.createElement("pre");
            pre.textContent = JSON.stringify(event.details, null, 2);
            item.appendChild(pre);
          }
          target.appendChild(item);
        });
      }

      function renderTraffic(summary) {
        var target = byId("trafficSummary");
        clear(target);
        addKv(target, "total_users", summary.total_users);
        addKv(target, "total_used_mb", summary.total_used_mb);
        addKv(target, "total_limit_mb", summary.total_limit_mb);

        (summary.by_access_type || []).forEach(function (row) {
          var item = node("div", "list-item");
          addKv(item, "access_type", row.access_type);
          addKv(item, "users", row.users);
          addKv(item, "traffic_used_mb", row.traffic_used_mb);
          addKv(item, "traffic_limit_mb", row.traffic_limit_mb);
          target.appendChild(item);
        });
      }

      function renderServers(payload) {
        var target = byId("serversBlock");
        clear(target);
        addKv(target, "registry_available", payload.registry_available);
        if (payload.error) {
          addKv(target, "error", payload.error.type + ": " + payload.error.message);
        }

        var servers = payload.servers || [];
        if (!servers.length) {
          target.appendChild(node("p", "muted", "No servers returned."));
          return;
        }

        var wrap = node("div", "table-wrap");
        var table = document.createElement("table");
        var thead = document.createElement("thead");
        var headRow = document.createElement("tr");
        ["code", "name", "enabled", "protocol", "network", "endpoint", "provider"].forEach(function (label) {
          headRow.appendChild(node("th", "", label));
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        var tbody = document.createElement("tbody");
        servers.forEach(function (server) {
          var row = document.createElement("tr");
          row.appendChild(node("td", "", server.code));
          row.appendChild(node("td", "", server.display_name));
          row.appendChild(node("td", server.enabled ? "status-ok" : "status-bad", server.enabled));
          row.appendChild(node("td", "", server.protocol));
          row.appendChild(node("td", "", server.network));
          row.appendChild(node("td", "", server.public_endpoint));
          row.appendChild(node("td", "", server.provider));
          tbody.appendChild(row);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        target.appendChild(wrap);
      }

      async function loadUsers(query) {
        var params = new URLSearchParams();
        params.set("limit", "50");
        if (query) {
          params.set("q", query);
        }
        renderUsers(await api("/users?" + params.toString()));
      }

      async function selectUser(telegramId) {
        state.selectedTelegramId = telegramId;
        var detail = await api("/users/" + encodeURIComponent(telegramId));
        var events = await api("/users/" + encodeURIComponent(telegramId) + "/events?limit=20");
        renderUserDetail(detail);
        renderEvents(events);
      }

      async function loadDashboard() {
        byId("refreshButton").disabled = true;
        try {
          var me = await api("/me");
          setBanner("ok", "Authenticated as Telegram ID " + text(me.telegram_id) + ". Read-only mode.");
          renderMe(me);

          var results = await Promise.all([
            api("/stats"),
            api("/users?limit=50"),
            api("/traffic/summary"),
            api("/servers")
          ]);

          renderStats(results[0]);
          renderUsers(results[1]);
          renderTraffic(results[2]);
          renderServers(results[3]);

          if (state.selectedTelegramId) {
            await selectUser(state.selectedTelegramId);
          }
        } catch (error) {
          if (!state.initData) {
            renderMe({});
          }
        } finally {
          byId("refreshButton").disabled = false;
        }
      }

      byId("refreshButton").addEventListener("click", function () {
        loadDashboard();
      });

      byId("useManualInitData").addEventListener("click", function () {
        state.initData = byId("manualInitData").value.trim();
        loadDashboard();
      });

      byId("userSearchForm").addEventListener("submit", function (event) {
        event.preventDefault();
        loadUsers(byId("userSearchInput").value.trim());
      });

      state.initData = getTelegramInitData();
      byId("devAuthFallback").open = !state.initData;

      if (state.initData) {
        loadDashboard();
      } else {
        setBanner("warn", "Telegram initData was not found. Open from Telegram or paste initData for local testing.");
      }
    }());
  </script>
</body>
</html>
"""


async def health_handler(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def admin_miniapp_page_handler(request: web.Request) -> web.Response:
    return web.Response(
        text=ADMIN_MINIAPP_HTML,
        content_type="text/html",
        charset="utf-8",
    )


async def yookassa_webhook_handler(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.Response(text="invalid json", status=400)

    status_code, message = await process_yookassa_notification(payload)
    logger.info("YooKassa webhook processed: status=%s message=%s", status_code, message)
    return web.Response(text=message, status=status_code)


def _extract_admin_init_data(request: web.Request) -> str:
    init_data = request.headers.get("X-Telegram-Init-Data", "").strip()
    if init_data:
        return init_data

    auth_header = request.headers.get("Authorization", "").strip()
    scheme, _, value = auth_header.partition(" ")
    if scheme.lower() in {"tma", "telegramwebapp"}:
        return value.strip()

    return ""


def _auth_error_response(exc: AdminMiniAppAuthError) -> web.Response:
    return web.json_response(
        {
            "error": exc.code,
            "message": exc.message,
        },
        status=exc.status,
    )


def _require_admin(request: web.Request) -> AdminMiniAppIdentity:
    return authenticate_admin_init_data(_extract_admin_init_data(request))


def _parse_int_query(
    request: web.Request,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = request.query.get(name)
    if raw is None or raw == "":
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    return max(minimum, min(value, maximum))


def _parse_telegram_id(request: web.Request) -> int:
    try:
        telegram_id = int(request.match_info["telegram_id"])
    except (KeyError, ValueError) as exc:
        raise web.HTTPBadRequest(text="invalid telegram_id") from exc

    if telegram_id <= 0:
        raise web.HTTPBadRequest(text="invalid telegram_id")

    return telegram_id


async def admin_me_handler(request: web.Request) -> web.Response:
    try:
        admin = _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(
        {
            "telegram_id": admin.telegram_id,
            "username": admin.username,
            "first_name": admin.first_name,
            "last_name": admin.last_name,
            "auth_date": admin.auth_date,
            "read_only": True,
        }
    )


async def admin_stats_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(await get_admin_stats())


async def admin_users_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    payload = await get_admin_users(
        limit=_parse_int_query(request, "limit", default=50, minimum=1, maximum=100),
        offset=_parse_int_query(request, "offset", default=0, minimum=0, maximum=10000),
        access_type=request.query.get("access_type"),
        query=request.query.get("q"),
    )
    return web.json_response(payload)


async def admin_user_detail_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
        telegram_id = _parse_telegram_id(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    payload = await get_admin_user_detail(telegram_id)
    if payload is None:
        return web.json_response({"error": "not_found"}, status=404)

    return web.json_response(payload)


async def admin_user_events_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
        telegram_id = _parse_telegram_id(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(
        await get_admin_user_events(
            telegram_id,
            limit=_parse_int_query(request, "limit", default=20, minimum=1, maximum=50),
        )
    )


async def admin_traffic_summary_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(await get_admin_traffic_summary())


async def admin_servers_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(await get_admin_servers())


def create_app() -> web.Application:
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app.router.add_get("/health", health_handler)
    app.router.add_post("/yookassa/webhook", yookassa_webhook_handler)
    app.router.add_get("/miniapp/admin", admin_miniapp_page_handler)
    app.router.add_get("/miniapp/admin/me", admin_me_handler)
    app.router.add_get("/miniapp/admin/stats", admin_stats_handler)
    app.router.add_get("/miniapp/admin/users", admin_users_handler)
    app.router.add_get("/miniapp/admin/users/{telegram_id}/events", admin_user_events_handler)
    app.router.add_get("/miniapp/admin/users/{telegram_id}", admin_user_detail_handler)
    app.router.add_get("/miniapp/admin/traffic/summary", admin_traffic_summary_handler)
    app.router.add_get("/miniapp/admin/servers", admin_servers_handler)
    return app


if __name__ == "__main__":
    web.run_app(
        create_app(),
        host=settings.webhook_host,
        port=settings.webhook_port,
    )
