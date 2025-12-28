#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import fnmatch
import argparse
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Set, Tuple
from email.parser import BytesParser
from email.policy import default as email_policy
from email.utils import getaddresses

from dotenv import load_dotenv
from imapclient import IMAPClient

# Всегда подхватываем .env рядом со скриптом
load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)

IMAP_HOST = "imap.rambler.ru"
IMAP_PORT = 993

# Правила по умолчанию:
# - обычный домен (ozon.ru) матчится как ozon.ru и *.ozon.ru (поддомены тоже)
# - маска с '@' матчится по полному адресу отправителя (для Apple private relay)
RULES_DEFAULT = [
    "ozon.ru",
    "linkedin.com",
    "snob.ru",
    "finam.ru",
    "mvideo.ru",
    "aliexpress.ru",
    "hh.ru",
    "letu.ru",
    "afisha.ru",
    "cdek.shopping",
    "alltime.ru",
    "avito.ru",
    "onetwotrip.com",
    "tricolortv.ru",
    "flocktory.com",
    "pobeda.aero",
    "mail.ivd.ru",
    "skyeng.ru",
    "globalsources.com",
    "artromost.ru",
    "livejournal.com",
    "sportmaster.ru",
    "medium.com",
    "litres.ru",
    "mos.ru",
    "ticketsold.ru",
    "sdelaimebel.ru",
    "electronix.ru",
    "smart-t.ru",
    "rusconcert.net",
    "vigoda.ru",
    "forumhouse.ru",
    "*reddit*@privaterelay.appleid.com",

]


def _to_str(x) -> str:
    if x is None:
        return ""
    return x.decode() if isinstance(x, (bytes, bytearray)) else str(x)


def chunked(seq: List[int], size: int) -> Iterable[List[int]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def supports_uidplus(server: IMAPClient) -> bool:
    try:
        caps = server.capabilities()
    except Exception:
        return False
    caps_norm = {_to_str(c).upper() for c in (caps or [])}
    return "UIDPLUS" in caps_norm


def is_inuse_error(e: Exception) -> bool:
    s = str(e).upper()
    return ("INUSE" in s) or ("INDEXING" in s) or ("TIMEOUT WHILE WAITING FOR INDEXING" in s)


def with_retries(fn, attempts: int = 4, base_delay: float = 2.0):
    delay = base_delay
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if is_inuse_error(e) and i < attempts - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last  # pragma: no cover


def is_noselect(flags) -> bool:
    normalized = {_to_str(f) for f in (flags or [])}
    return "\\Noselect" in normalized or "\\NOSELECT" in normalized


def list_selectable_mailboxes(server: IMAPClient) -> List[str]:
    folders: List[str] = []
    for flags, _delim, name in server.list_folders():
        if is_noselect(flags):
            continue
        folders.append(_to_str(name))
    return folders


def envelope_from_parts(envelope) -> Tuple[str, str, str]:
    """
    Returns (mailbox, host, full_email) from ENVELOPE.From[0]
    full_email is "mailbox@host" lowercased.
    """
    if not envelope or not getattr(envelope, "from_", None):
        return "", "", ""
    a = envelope.from_[0]
    mailbox = _to_str(getattr(a, "mailbox", "")) or ""
    host = _to_str(getattr(a, "host", "")) or ""
    full = f"{mailbox}@{host}".lower() if mailbox and host else ""
    return mailbox.lower(), host.lower(), full


def parse_from_header(header_bytes: bytes) -> Tuple[str, str]:
    """
    Parse header block containing From: ...
    Returns (host, full_email) lowercase, or ("","") if not found.
    """
    if not header_bytes:
        return "", ""
    msg = BytesParser(policy=email_policy).parsebytes(header_bytes)
    from_value = msg.get("From", "")
    if not from_value:
        return "", ""
    addrs = getaddresses([from_value])
    if not addrs:
        return "", ""
    email_addr = (addrs[0][1] or "").strip().lower()
    if "@" not in email_addr:
        return "", ""
    _local, host = email_addr.rsplit("@", 1)
    return host.strip().lower(), email_addr


def rule_kind(rule: str) -> str:
    r = rule.strip().lower()
    if "@" in r:
        return "email_mask"
    if any(ch in r for ch in ("*", "?", "[", "]")):
        return "host_mask"
    return "domain"


def match_rule(rule: str, host: str, full_email: str) -> bool:
    r = rule.strip().lower()
    kind = rule_kind(r)

    if kind == "email_mask":
        return bool(full_email) and fnmatch.fnmatch(full_email, r)

    if kind == "host_mask":
        return bool(host) and fnmatch.fnmatch(host.lower(), r)

    # domain: host == dom OR host endswith ".dom"
    if not host:
        return False
    h = host.lower()
    return h == r or h.endswith("." + r)


def delete_uids(server: IMAPClient, uids: List[int], batch: int, uidplus: bool) -> int:
    if not uids:
        return 0

    deleted = 0
    for part in chunked(uids, max(1, batch)):
        server.delete_messages(part)
        if uidplus and hasattr(server, "uid_expunge"):
            server.uid_expunge(part)
        else:
            server.expunge()
        deleted += len(part)
    return deleted


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Rambler IMAP cleaner (scan all UIDs, match by rules)")
    ap.add_argument("--user", default=None, help="Login (or env RAMBLER_USER)")
    ap.add_argument("--password", default=None, help="Password/app-password (or env RAMBLER_PASS)")
    ap.add_argument("--folders", default="INBOX", help='Folders: "INBOX" or "*" or comma-separated')
    ap.add_argument("--skip-folders", default="", help='Comma-separated folders to skip (e.g. "Sent Messages")')
    ap.add_argument("--list-folders", action="store_true", help="List IMAP folders and exit")
    ap.add_argument("--rules", default=",".join(RULES_DEFAULT),
                    help="Comma-separated rules (domains/masks). Example: ozon.ru,*.mvideo.ru,*reddit*@privaterelay.appleid.com")
    ap.add_argument("--delete", action="store_true", help="Actually delete (otherwise dry-run)")
    ap.add_argument("--batch", type=int, default=500, help="Batch size for fetch/delete (default 500)")
    ap.add_argument("--retries", type=int, default=4, help="Retries on [INUSE]/indexing (default 4)")
    ap.add_argument("--retry-delay", type=float, default=2.0, help="Base retry delay seconds (default 2.0)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    user = args.user or os.getenv("RAMBLER_USER")
    password = args.password or os.getenv("RAMBLER_PASS")
    if not user or not password:
        raise SystemExit("Set credentials via --user/--password or env RAMBLER_USER / RAMBLER_PASS")

    rules = [r.strip() for r in (args.rules or "").split(",") if r.strip()]
    if not rules:
        raise SystemExit("No rules provided")

    skip = {f.strip() for f in (args.skip_folders or "").split(",") if f.strip()}

    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as server:
        server.login(user, password)

        selectable = list_selectable_mailboxes(server)
        if args.list_folders:
            print("Selectable folders:")
            for f in selectable:
                print(" -", f)
            return

        if args.folders.strip() == "*" or not args.folders.strip():
            folders = [f for f in selectable if f not in skip]
        else:
            want = [f.strip() for f in args.folders.split(",") if f.strip()]
            folders = [f for f in selectable if f in want and f not in skip]

        uidplus = supports_uidplus(server)

        print(f"Server: {IMAP_HOST}:{IMAP_PORT} SSL | Folders: {len(folders)} | Mode: {'DELETE' if args.delete else 'DRY-RUN'}")
        print("Rules:")
        for r in rules:
            print(f"  {r} ({rule_kind(r)})")
        print()

        grand_per_rule = Counter()
        grand_unique = 0
        grand_deleted = 0

        for folder in folders:
            try:
                server.select_folder(folder, readonly=not args.delete)
            except Exception as e:
                print(f"[SKIP] Cannot select folder '{folder}': {e}")
                continue

            try:
                all_uids = with_retries(lambda: server.search(["NOT", "DELETED"]),
                                        attempts=args.retries, base_delay=args.retry_delay)
            except Exception as e:
                print(f"[WARN] UID listing failed in '{folder}': {e}")
                continue

            per_rule = Counter()
            matched_uids: Set[int] = set()

            for part in chunked(all_uids, max(1, args.batch)):
                fetched = with_retries(lambda: server.fetch(part, ["ENVELOPE"]),
                                      attempts=args.retries, base_delay=args.retry_delay)

                need_header: List[int] = []

                for uid, item in fetched.items():
                    env = item.get(b"ENVELOPE") or item.get("ENVELOPE")
                    if env is None:
                        need_header.append(uid)
                        continue

                    _mb, host, full_email = envelope_from_parts(env)
                    if not host and not full_email:
                        need_header.append(uid)
                        continue

                    hit = False
                    for r in rules:
                        if match_rule(r, host=host, full_email=full_email):
                            per_rule[r] += 1
                            hit = True
                    if hit:
                        matched_uids.add(uid)

                if need_header:
                    hdr = with_retries(
                        lambda: server.fetch(need_header, ["BODY.PEEK[HEADER.FIELDS (FROM)]"]),
                        attempts=args.retries, base_delay=args.retry_delay
                    )
                    for uid, item in hdr.items():
                        raw = (
                            item.get(b"BODY[HEADER.FIELDS (FROM)]")
                            or item.get(b"BODY.PEEK[HEADER.FIELDS (FROM)]")
                            or b""
                        )
                        host, full_email = parse_from_header(raw)
                        if not host and not full_email:
                            continue

                        hit = False
                        for r in rules:
                            if match_rule(r, host=host, full_email=full_email):
                                per_rule[r] += 1
                                hit = True
                        if hit:
                            matched_uids.add(uid)

            folder_unique = len(matched_uids)
            if folder_unique == 0:
                continue

            print(f"Folder: {folder}")
            for r in rules:
                if per_rule[r]:
                    print(f"  {r:55s}: {per_rule[r]}")
            print(f"  -> Unique matched in folder: {folder_unique}")

            grand_per_rule.update(per_rule)
            grand_unique += folder_unique

            if args.delete:
                deleted_here = delete_uids(server, sorted(matched_uids), batch=args.batch, uidplus=uidplus)
                grand_deleted += deleted_here
                print(f"  Deleted: {deleted_here}\n")
            else:
                print("  (dry-run: nothing deleted)\n")

        print("=== SUMMARY ===")
        print(f"Total unique matched (across processed folders): {grand_unique}")
        if args.delete:
            print(f"Total deleted: {grand_deleted}")
        print("Counts by rule (may overlap across folders):")
        for r in rules:
            print(f"  {r:55s}: {grand_per_rule[r]}")


if __name__ == "__main__":
    main()
