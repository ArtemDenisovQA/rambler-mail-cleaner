#!/usr/bin/env python3
import os
import argparse
from collections import Counter, defaultdict
from imapclient import IMAPClient

DOMAINS = [
    "ozon.ru",
    "linkedin.com",
    "snob.ru",
    "finam.ru",
    "mvideo.ru",
    "aliexpress.ru",
    "hh.ru",
]

IMAP_HOST = "imap.rambler.ru"
IMAP_PORT = 993

def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]

def is_noselect(flags):
    # flags may be tuple/list of bytes/str
    normalized = {f.decode() if isinstance(f, (bytes, bytearray)) else str(f) for f in (flags or [])}
    return "\\Noselect" in normalized or "\\NOSELECT" in normalized

def supports_uidplus(server: IMAPClient) -> bool:
    try:
        caps = server.capabilities()
    except Exception:
        return False
    caps_norm = {c.decode() if isinstance(c, (bytes, bytearray)) else str(c) for c in (caps or [])}
    return "UIDPLUS" in caps_norm

def list_selectable_mailboxes(server: IMAPClient):
    # returns folder names (str) that can be selected
    for flags, _delim, name in server.list_folders():
        if is_noselect(flags):
            continue
        # IMAPClient typically returns str, but handle bytes just in case
        if isinstance(name, (bytes, bytearray)):
            name = name.decode("utf-8", errors="replace")
        yield name

def main():
    ap = argparse.ArgumentParser(description="Delete Rambler emails from specific sender domains via IMAP")
    ap.add_argument("--user", default=os.environ.get("RAMBLER_USER"), help="Email login, e.g. user@rambler.ru (or env RAMBLER_USER)")
    ap.add_argument("--password", default=os.environ.get("RAMBLER_PASS"), help="Password/app-password (or env RAMBLER_PASS)")
    ap.add_argument("--folders", default="*", help='Comma-separated folders to process, or "*" for all (default)')
    ap.add_argument("--delete", action="store_true", help="Actually delete messages (otherwise dry-run)")
    ap.add_argument("--batch", type=int, default=500, help="UID batch size for delete/expunge (default 500)")
    args = ap.parse_args()

    if not args.user or not args.password:
        raise SystemExit("Set credentials via --user/--password or env RAMBLER_USER / RAMBLER_PASS")

    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True) as server:
        server.login(args.user, args.password)

        # choose folders
        all_folders = list(list_selectable_mailboxes(server))
        if args.folders.strip() == "*" or not args.folders.strip():
            folders = all_folders
        else:
            want = {f.strip() for f in args.folders.split(",") if f.strip()}
            folders = [f for f in all_folders if f in want]
            missing = want - set(folders)
            if missing:
                print(f"[WARN] These folders were not found/selectable: {sorted(missing)}")

        uidplus = supports_uidplus(server)

        grand_total_per_domain = Counter()
        grand_total_matched = 0
        grand_total_deleted = 0

        print(f"Server: {IMAP_HOST}:{IMAP_PORT} SSL | Folders: {len(folders)} | Mode: {'DELETE' if args.delete else 'DRY-RUN'}")
        print(f"Domains: {', '.join(DOMAINS)}\n")

        for folder in folders:
            try:
                server.select_folder(folder, readonly=not args.delete)
            except Exception as e:
                print(f"[SKIP] Cannot select folder '{folder}': {e}")
                continue

            per_domain = Counter()
            matched_uids = set()

            # Find candidates for each domain (server-side search)
            for dom in DOMAINS:
                try:
                    # IMAP SEARCH FROM does substring match in From: header
                    uids = server.search(["FROM", dom])
                except Exception as e:
                    print(f"[WARN] Search failed in '{folder}' for FROM {dom}: {e}")
                    continue

                per_domain[dom] += len(uids)
                matched_uids.update(uids)

            folder_total = len(matched_uids)
            if folder_total == 0:
                continue

            grand_total_per_domain.update(per_domain)
            grand_total_matched += folder_total

            print(f"Folder: {folder}")
            for dom in DOMAINS:
                if per_domain[dom]:
                    print(f"  {dom:14s}: {per_domain[dom]}")
            print(f"  -> Unique matched in folder: {folder_total}")

            if args.delete:
                uids_list = sorted(matched_uids)
                deleted_here = 0

                for part in chunked(uids_list, args.batch):
                    # mark as \Deleted
                    server.delete_messages(part)

                    # safer expunge only these messages if UIDPLUS is available
                    if uidplus and hasattr(server, "uid_expunge"):
                        server.uid_expunge(part)
                    else:
                        # falls back to expunging all \Deleted in folder
                        server.expunge()

                    deleted_here += len(part)

                grand_total_deleted += deleted_here
                print(f"  Deleted: {deleted_here}\n")
            else:
                print("  (dry-run: nothing deleted)\n")

        print("=== SUMMARY ===")
        print(f"Total unique matched (across processed folders): {grand_total_matched}")
        if args.delete:
            print(f"Total deleted: {grand_total_deleted}")
        print("Counts by domain (may overlap across folders):")
        for dom in DOMAINS:
            print(f"  {dom:14s}: {grand_total_per_domain[dom]}")

if __name__ == "__main__":
    main()
