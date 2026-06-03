#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "lead_monitor.sqlite3"

DEFAULT_QUERIES = [
    '"посоветуйте впн"',
    '"какой впн"',
    '"какой vpn"',
    '"vpn не работает"',
    '"впн не работает"',
    '"vpn для iphone"',
    '"vpn для android"',
    '"обход блокировки"',
    '"youtube vpn"',
    '"best vpn russia"',
    '"vpn not working russia"',
    '"recommend vpn russia"',
]

USER_AGENT = "VOIDLeadMonitor/0.2 (+https://t.me/voidModeSupport)"


@dataclass(frozen=True)
class Lead:
    source: str
    query: str
    title: str
    url: str
    published: str
    published_ts: int
    summary: str
    subreddit: str
    author: str
    score: int
    reasons: tuple[str, ...]


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    if not path.exists():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def get_config_value(name: str, dotenv: dict[str, str], default: str = "") -> str:
    return os.getenv(name, dotenv.get(name, default)).strip()


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_leads (
                url TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                query TEXT NOT NULL,
                title TEXT NOT NULL,
                first_seen_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                sent_at INTEGER
            )
            """
        )
        conn.commit()


def already_seen(path: Path, url: str) -> bool:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_leads WHERE url = ? LIMIT 1",
            (url,),
        ).fetchone()

    return row is not None


def mark_seen(path: Path, lead: Lead, *, sent: bool) -> None:
    now = int(time.time())

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO seen_leads (
                url, source, query, title, first_seen_at, last_seen_at, sent_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                sent_at = COALESCE(seen_leads.sent_at, excluded.sent_at)
            """,
            (
                lead.url,
                lead.source,
                lead.query,
                lead.title[:500],
                now,
                now,
                now if sent else None,
            ),
        )
        conn.commit()


def fetch_url(url: str, *, timeout: int = 15) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def clean_text(value: str | None, *, limit: int = 500) -> str:
    text = html.unescape(value or "")
    text = " ".join(text.split())
    return text[:limit]


def parse_datetime_to_ts(value: str | None) -> int:
    raw = (value or "").strip()

    if not raw:
        return 0

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return int(dt.timestamp())


def is_reddit_post_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    return host.endswith("reddit.com") and "/comments/" in path


def extract_subreddit(url: str) -> str:
    path = urllib.parse.urlparse(url).path.strip("/")
    parts = path.split("/")

    if len(parts) >= 2 and parts[0].lower() == "r":
        return parts[1]

    return ""


DENY_SUBREDDITS = {
    "tor",
    "windscribe",
    "freemediaheckyeah",
    "appledatahoarding",
    "ru_epl",
    "twistedrobloxofficial",
}


def normalize_reddit_author(value: str | None) -> str:
    raw = clean_text(value or "", limit=120).strip()

    if not raw:
        return ""

    raw = raw.replace("https://www.reddit.com/user/", "")
    raw = raw.replace("https://old.reddit.com/user/", "")
    raw = raw.replace("/u/", "")
    raw = raw.replace("u/", "")
    raw = raw.strip("/ ")

    return raw


def is_bad_author_name(author: str) -> bool:
    value = author.strip().lower()

    return (
        not value
        or value in {"[deleted]", "deleted", "automoderator"}
        or "suspended" in value
    )


def reddit_author_about_url(author: str) -> str:
    return f"https://www.reddit.com/user/{urllib.parse.quote(author, safe='')}/about.json"


def reddit_author_is_available(author: str, *, timeout: int = 10) -> tuple[bool, str]:
    if is_bad_author_name(author):
        return False, "bad_author_name"

    try:
        data = fetch_url(reddit_author_about_url(author), timeout=timeout)
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        # 403 is too noisy for unauthenticated Reddit checks and may mean that
        # Reddit blocked the profile probe, not that the author is suspended.
        if exc.code in {404, 410}:
            return False, f"author_unavailable_http_{exc.code}"
        return True, f"author_check_http_{exc.code}_ignored"
    except Exception as exc:
        return True, f"author_check_failed_ignored:{type(exc).__name__}"

    if isinstance(payload, dict) and payload.get("kind") == "t2":
        return True, "author_ok"

    return False, "author_unavailable_payload"


def score_lead(title: str, summary: str, subreddit: str) -> tuple[int, tuple[str, ...]]:
    text = f"{title}\n{summary}".lower()
    score = 0
    reasons: list[str] = []

    if subreddit.lower() in DENY_SUBREDDITS:
        return -100, ("denylisted_subreddit",)

    if "впн" in text or "vpn" in text:
        score += 3
        reasons.append("mentions_vpn")
    else:
        return -50, ("no_vpn_mention",)

    intent_words = [
        "посоветуйте",
        "посоветуй",
        "какой",
        "выбрать",
        "нужен",
        "работает",
        "не работает",
        "что делать",
        "recommend",
        "best",
        "not working",
        "which",
        "need",
    ]

    if any(word in text for word in intent_words):
        score += 3
        reasons.append("intent")

    pain_words = [
        "не работает",
        "сломался",
        "блок",
        "блокировка",
        "обход",
        "заблок",
        "youtube",
        "ютуб",
        "claude",
        "clauda",
        "instagram",
        "инст",
        "not working",
        "blocked",
        "russia",
    ]

    if any(word in text for word in pain_words):
        score += 2
        reasons.append("pain_or_use_case")

    if subreddit.lower() in {"ruasska", "askarussian", "rusaskreddit", "vse_o_rabote", "amneziavpn"}:
        score += 1
        reasons.append("relevant_subreddit")

    if len(title) < 8:
        score -= 2
        reasons.append("short_title")

    return score, tuple(reasons)


def parse_reddit_rss(xml_bytes: bytes, *, query: str, min_ts: int) -> list[Lead]:
    root = ET.fromstring(xml_bytes)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    leads: list[Lead] = []

    for entry in root.findall("atom:entry", ns):
        title = clean_text(entry.findtext("atom:title", default="", namespaces=ns), limit=250)
        published = clean_text(entry.findtext("atom:updated", default="", namespaces=ns), limit=80)
        published_ts = parse_datetime_to_ts(published)
        summary = clean_text(entry.findtext("atom:content", default="", namespaces=ns), limit=500)

        author = normalize_reddit_author(
            entry.findtext("atom:author/atom:name", default="", namespaces=ns)
        )

        url = ""
        for link in entry.findall("atom:link", ns):
            href = link.attrib.get("href", "").strip()
            rel = link.attrib.get("rel", "")
            if href and rel in {"alternate", ""}:
                url = href
                break

        if not title or not url:
            continue

        if not is_reddit_post_url(url):
            continue

        if published_ts <= 0 or published_ts < min_ts:
            continue

        subreddit = extract_subreddit(url)

        if is_bad_author_name(author):
            continue

        score, reasons = score_lead(title, summary, subreddit)

        leads.append(
            Lead(
                source="reddit",
                query=query,
                title=title,
                url=url,
                published=published,
                published_ts=published_ts,
                summary=summary,
                subreddit=subreddit,
                author=author,
                score=score,
                reasons=reasons,
            )
        )

    return leads


def reddit_search_url(query: str) -> str:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "sort": "new",
            "t": "month",
            "type": "link",
        }
    )
    return f"https://www.reddit.com/search.rss?{params}"


def find_reddit_leads(
    queries: list[str],
    *,
    limit_per_query: int,
    max_age_days: int,
) -> list[Lead]:
    all_leads: list[Lead] = []
    min_ts = int(time.time()) - max_age_days * 24 * 60 * 60

    for query in queries:
        url = reddit_search_url(query)

        try:
            data = fetch_url(url)
            leads = parse_reddit_rss(data, query=query, min_ts=min_ts)
        except Exception as exc:
            print(f"WARN reddit query failed: {query!r}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

        all_leads.extend(leads[:limit_per_query])

    all_leads.sort(key=lambda lead: lead.published_ts, reverse=True)
    return all_leads


def telegram_send(token: str, chat_id: int, text: str) -> None:
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        response.read()


def format_lead_message(lead: Lead) -> str:
    title = html.escape(lead.title)
    query = html.escape(lead.query)
    source = html.escape(lead.source)
    published = html.escape(lead.published or "-")
    subreddit = html.escape(lead.subreddit or "-")
    author = html.escape(lead.author or "-")
    reasons = html.escape(",".join(lead.reasons) or "-")
    summary = html.escape(lead.summary or "-")
    url = html.escape(lead.url)

    return (
        "🧲 <b>Новый лид</b>\n\n"
        f"<b>Источник:</b> {source} / r/{subreddit}\n"
        f"<b>Автор:</b> u/{author}\n"
        f"<b>Запрос:</b> <code>{query}</code>\n"
        f"<b>Дата:</b> {published}\n"
        f"<b>Score:</b> {lead.score} <code>{reasons}</code>\n\n"
        f"<b>{title}</b>\n"
        f"{summary}\n\n"
        f"{url}"
    )


def parse_admin_ids(value: str) -> list[int]:
    result: list[int] = []

    for item in value.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue

        try:
            result.append(int(item))
        except ValueError:
            continue

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Find fresh social/search leads for VOID.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite dedupe DB path")
    parser.add_argument("--send", action="store_true", help="Send new leads to Telegram and mark as seen")
    parser.add_argument("--mark-seen", action="store_true", help="Mark fresh leads as seen without sending")
    parser.add_argument("--limit-per-query", type=int, default=5)
    parser.add_argument("--max-new", type=int, default=10)
    parser.add_argument("--max-age-days", type=int, default=3)
    parser.add_argument("--min-score", type=int, default=5)
    parser.add_argument("--check-author", action="store_true", help="Check Reddit author availability before reporting")
    parser.add_argument("--query", action="append", default=[], help="Extra query; may be repeated")
    parser.add_argument("--source", choices=["reddit"], default="reddit")
    parser.add_argument("--env-file", default=".env", help="Env file with BOT_TOKEN and ADMIN_TELEGRAM_IDS")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if not env_path.is_absolute():
        env_path = PROJECT_ROOT / env_path

    dotenv = load_dotenv(env_path)
    db_path = Path(args.db)

    init_db(db_path)

    queries = DEFAULT_QUERIES + list(args.query or [])

    if args.source == "reddit":
        leads = find_reddit_leads(
            queries,
            limit_per_query=max(1, args.limit_per_query),
            max_age_days=max(1, args.max_age_days),
        )
    else:
        leads = []

    fresh: list[Lead] = []

    for lead in leads:
        if lead.score < args.min_score:
            continue

        if args.check_author:
            author_ok, author_reason = reddit_author_is_available(lead.author)
            if not author_ok:
                print(
                    f"SKIP author unavailable: u/{lead.author} {author_reason} {lead.url}",
                    file=sys.stderr,
                )
                continue

        if already_seen(db_path, lead.url):
            continue

        fresh.append(lead)
        if len(fresh) >= args.max_new:
            break

    print(
        f"found_total={len(leads)} fresh={len(fresh)} "
        f"send={bool(args.send)} mark_seen={bool(args.mark_seen)} "
        f"max_age_days={args.max_age_days} min_score={args.min_score} db={db_path}"
    )

    token = get_config_value("BOT_TOKEN", dotenv)
    admin_ids = parse_admin_ids(get_config_value("ADMIN_TELEGRAM_IDS", dotenv))

    if args.send and (not token or not admin_ids):
        print("ERROR: --send requires BOT_TOKEN and ADMIN_TELEGRAM_IDS", file=sys.stderr)
        return 2

    sent_count = 0

    for lead in fresh:
        print()
        print(f"[{lead.source}] {lead.published} — {lead.title}")
        print(f"query={lead.query}")
        print(f"subreddit=r/{lead.subreddit} author=u/{lead.author} score={lead.score} reasons={','.join(lead.reasons)}")
        print(lead.url)

        sent = False

        if args.send:
            text = format_lead_message(lead)
            for admin_id in admin_ids:
                telegram_send(token, admin_id, text)
            sent = True
            sent_count += 1

        if args.send or args.mark_seen:
            mark_seen(db_path, lead, sent=sent)

    print(f"done fresh={len(fresh)} sent={sent_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
