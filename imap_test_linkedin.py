import os
from pathlib import Path
from dotenv import load_dotenv
from imapclient import IMAPClient

load_dotenv(Path(__file__).with_name(".env"), override=True)

HOST = "imap.rambler.ru"
USER = os.getenv("RAMBLER_USER")
PASS = os.getenv("RAMBLER_PASS")

if not USER or not PASS:
    raise SystemExit("Нет RAMBLER_USER / RAMBLER_PASS (проверь .env)")

with IMAPClient(HOST, port=993, ssl=True) as s:
    s.login(USER, PASS)
    s.select_folder("INBOX")

    u1 = s.search(["FROM", "linkedin.com"])
    u2 = s.search(["HEADER", "From", "linkedin.com"])
    u3 = s.search(["TEXT", "linkedin.com"])

    print("FROM:", len(u1), "HEADER From:", len(u2), "TEXT:", len(u3))

    u = (u1 or u2 or u3)[:1]
    if u:
        env = s.fetch(u, ["ENVELOPE"])[u[0]][b"ENVELOPE"]
        a = env.from_[0]
        mailbox = a.mailbox.decode() if isinstance(a.mailbox, (bytes, bytearray)) else a.mailbox
        host = a.host.decode() if isinstance(a.host, (bytes, bytearray)) else a.host
        print("Envelope from:", f"{mailbox}@{host}")
    else:
        print("В INBOX не найдено писем, содержащих linkedin.com")
