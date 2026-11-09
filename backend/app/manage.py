"""Operator commands, for whoever has shell access to the server (not reachable over HTTP).

    python -m app.manage create-user --email a@b.edu --role FACULTY [--name "A B"] [--alumni-id 12]
    python -m app.manage set-password --email a@b.edu      # also ends that user's sessions and clears any lockout
    python -m app.manage unlock --email a@b.edu

Passwords are always prompted for (never passed as arguments, so they stay out of shell history).
Every command writes an audit row with the actor "cli".
"""
import argparse
import getpass
import sys

from . import accounts, audit, rbac
from .db import db, init
from .security import hash_password, ts


def _password(confirm=True):
    pw = getpass.getpass("New password: ")
    if confirm and getpass.getpass("Repeat password: ") != pw:
        sys.exit("Passwords do not match")
    return pw


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-user")
    a.add_argument("--email", required=True)
    a.add_argument("--role", required=True, choices=list(rbac.ROLES))
    a.add_argument("--name")
    a.add_argument("--alumni-id", type=int)
    for name in ("set-password", "unlock"):
        sub.add_parser(name).add_argument("--email", required=True)
    args = ap.parse_args(argv)

    init()
    try:
        with db() as c:
            if args.cmd == "create-user":
                uid = accounts.create_user(c, email=args.email, password=_password(), role=args.role,
                                           full_name=args.name, alumni_id=args.alumni_id)
                audit.record(c, "user.create", None, actor_email="cli", entity_type="user", entity_id=uid,
                             detail={"email": accounts.normalize_email(args.email), "role": args.role})
                print(f"Created {args.role} user #{uid}")
            else:
                u = accounts.get_by_email(c, args.email)
                if not u:
                    sys.exit("No such user")
                if args.cmd == "set-password":
                    pw = _password()
                    accounts.validate_password(pw, u["email"])
                    c.execute("UPDATE users SET password_hash=?, password_changed_at=?, failed_logins=0, locked_until=NULL WHERE id=?",
                              (hash_password(pw), ts(), u["id"]))
                    accounts.revoke_user_sessions(c, u["id"])
                    audit.record(c, "auth.password_set_cli", None, actor_email="cli", entity_type="user", entity_id=u["id"])
                    print("Password updated; all sessions for that user were ended.")
                else:
                    c.execute("UPDATE users SET failed_logins=0, locked_until=NULL WHERE id=?", (u["id"],))
                    audit.record(c, "auth.unlock_cli", None, actor_email="cli", entity_type="user", entity_id=u["id"])
                    print("Account unlocked.")
    except accounts.AccountError as e:
        sys.exit(e.message)


if __name__ == "__main__":
    main()
