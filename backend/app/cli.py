"""
Management commands, until the admin panel exists (Phase 5).

Run from the backend/ folder (virtualenv active):

    python -m app.cli bootstrap                 # first time: you as admin + your website
    python -m app.cli list                      # show clients, websites and users
    python -m app.cli create-client --name "Ali's Shop" --contact-email ali@shop.pk
    python -m app.cli add-website --client "Ali's Shop" --name "alishop.pk" --domain alishop.pk \
                                  --host https://us.posthog.com --project-id 12345
    python -m app.cli add-user --email ali@shop.pk --name "Ali" --client "Ali's Shop" --role owner
    python -m app.cli set-password --email ali@shop.pk
    python -m app.cli set-client-status --client "Ali's Shop" --status suspended
    python -m app.cli delete-user --email someone@example.com
    python -m app.cli run-job usage_sync        # run a background job now (see the Jobs page for the names)
    python -m app.cli generate-keys             # new JWT_SECRET / ENCRYPTION_KEY values

Passwords and API keys are typed in hidden (not shown, not saved in shell history).
For scripts, pass --password-stdin / --api-key-stdin and pipe the value in.
"""

import argparse
import getpass
import os
import re
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_sessionmaker
from app.models import ROLES, Client, ClientMember, User, Website
from app.security import (
    encrypt_secret,
    generate_encryption_key,
    generate_jwt_secret,
    hash_password,
    password_problem,
)

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CliError(Exception):
    """A problem we explain to the user (no traceback)."""


# ------------------------------------------------------------------ helpers


def read_secret(prompt: str, from_stdin: bool, confirm: bool = False) -> str:
    if from_stdin:
        # Read raw bytes and decode as "utf-8-sig": Windows PowerShell 5.1 puts an invisible
        # byte-order mark (BOM) in front of piped text, which would otherwise end up
        # inside the password. "utf-8-sig" drops it.
        value = sys.stdin.buffer.readline().decode("utf-8-sig").rstrip("\r\n")
    else:
        value = getpass.getpass(f"{prompt}: ")
        if confirm and getpass.getpass("Type it again: ") != value:
            raise CliError("The two entries don't match.")
    if not value:
        raise CliError(f"{prompt} can't be empty.")
    return value


def read_new_password(from_stdin: bool) -> str:
    password = read_secret("New password (hidden)", from_stdin, confirm=True)
    problem = password_problem(password)
    if problem:
        raise CliError(problem)
    return password


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise CliError(f"'{email}' doesn't look like an email address.")
    return email


def find_client(db: Session, ref: str) -> Client:
    """A client by id or by name (case-insensitive)."""
    try:
        client = db.get(Client, uuid.UUID(ref))
    except ValueError:
        matches = db.scalars(select(Client).where(func.lower(Client.name) == ref.strip().lower())).all()
        if len(matches) > 1:
            raise CliError(f"Several clients are called '{ref}'. Use the client id instead (see `list`).") from None
        client = matches[0] if matches else None
    if client is None:
        raise CliError(f"No client '{ref}'. See `python -m app.cli list`.")
    return client


def find_user(db: Session, email: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise CliError(f"No user with email {email}.")
    return user


def check_posthog_key(host: str, project_id: int, api_key: str) -> None:
    """Run a tiny query, so we never save a key that doesn't work."""
    try:
        response = httpx.post(
            f"{host}/api/projects/{project_id}/query/",
            json={"query": {"kind": "HogQLQuery", "query": "SELECT 1"}, "name": "portal: key check"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise CliError(f"Could not reach {host}: {exc}") from exc
    if response.status_code == 200:
        return
    hints = {
        401: "the key is wrong, or belongs to the other region (US vs EU)",
        403: "the key lacks the 'Query: Read' scope, or has no access to this project",
        404: "the project id is wrong, or the region is wrong",
    }
    hint = hints.get(response.status_code, response.text[:200])
    raise CliError(f"PostHog rejected the key check (HTTP {response.status_code}): {hint}.")


def create_user(db: Session, email: str, name: str, password: str, is_admin: bool = False) -> User:
    email = normalize_email(email)
    if db.scalar(select(User).where(User.email == email)):
        raise CliError(f"A user with email {email} already exists.")
    user = User(email=email, name=name.strip(), password_hash=hash_password(password), is_admin=is_admin)
    db.add(user)
    db.flush()  # gives the user its id
    return user


def create_website(
    db: Session, client: Client, name: str, domain: str | None, host: str, project_id: int, api_key: str, check: bool
) -> Website:
    host = host.strip().rstrip("/")
    if not host.startswith("https://"):
        raise CliError("--host must start with https:// (e.g. https://us.posthog.com)")
    if check:
        print("Checking the PostHog key... ", end="", flush=True)
        check_posthog_key(host, project_id, api_key)
        print("OK")
    website = Website(
        client_id=client.id,
        name=name.strip(),
        domain=(domain or "").strip() or None,
        posthog_host=host,
        posthog_project_id=project_id,
        posthog_api_key_encrypted=encrypt_secret(api_key),  # stored encrypted, never plain
    )
    db.add(website)
    db.flush()
    return website


# ------------------------------------------------------------------ commands


def cmd_generate_keys(args: argparse.Namespace) -> None:
    values = {"JWT_SECRET": generate_jwt_secret(), "ENCRYPTION_KEY": generate_encryption_key()}
    if not args.write_env:
        print("Add these to backend/.env (keep them secret, back up ENCRYPTION_KEY):\n")
        for key, value in values.items():
            print(f"{key}={value}")
        return
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    present = set(re.findall(r"^\s*([A-Z_][A-Z0-9_]*)\s*=", text, flags=re.M))
    added = [k for k in values if k not in present]
    if added:
        lines = "".join(f"{k}={values[k]}\n" for k in added)
        ENV_FILE.write_text(text + ("" if text.endswith("\n") or not text else "\n") + lines, encoding="utf-8")
    print(f"Added to .env: {', '.join(added) or 'nothing (already set)'}")


def cmd_bootstrap(args: argparse.Namespace, db: Session) -> None:
    """First-time setup: you as admin, your company as a client, your website from .env."""
    if db.scalar(select(func.count()).select_from(User)):
        raise CliError("The database already has users; bootstrap is only for the very first setup.")

    host = os.getenv("POSTHOG_HOST", "").strip()
    project_id = os.getenv("POSTHOG_PROJECT_ID", "").strip()
    api_key = os.getenv("POSTHOG_PERSONAL_API_KEY", "").strip()
    if not (host and project_id.isdigit() and api_key):
        raise CliError("bootstrap reads POSTHOG_HOST / POSTHOG_PROJECT_ID / POSTHOG_PERSONAL_API_KEY from .env; set them first.")

    email = args.email or input("Your email (admin login): ")
    name = args.name or input("Your name: ")
    password = read_new_password(args.password_stdin)
    client_name = args.client_name or os.getenv("WEBSITE_NAME", "") or "My Company"
    website_name = args.website_name or os.getenv("WEBSITE_NAME", "") or "My Website"

    admin = create_user(db, email, name, password, is_admin=True)
    client = Client(name=client_name, contact_email=admin.email)
    db.add(client)
    db.flush()
    website = create_website(db, client, website_name, args.domain, host, int(project_id), api_key, check=not args.skip_check)
    audit(db, "cli.bootstrap", actor_id=admin.id, target_type="website", target_id=website.id)
    db.commit()
    print(f"\nDone.\n  Admin:   {admin.email}\n  Client:  {client.name} ({client.id})\n  Website: {website.name} ({website.id})")
    print("\nThe PostHog key is now stored encrypted in the database. You can log in to the dashboard.")


def cmd_create_admin(args: argparse.Namespace, db: Session) -> None:
    user = create_user(db, args.email, args.name, read_new_password(args.password_stdin), is_admin=True)
    audit(db, "cli.admin_created", target_type="user", target_id=user.id)
    db.commit()
    print(f"Admin created: {user.email} ({user.id})")


def cmd_create_client(args: argparse.Namespace, db: Session) -> None:
    contact = normalize_email(args.contact_email) if args.contact_email else None
    client = Client(name=args.name.strip(), contact_email=contact, phone=args.phone)
    db.add(client)
    db.flush()
    audit(db, "cli.client_created", target_type="client", target_id=client.id)
    db.commit()
    print(f"Client created: {client.name} ({client.id})")


def cmd_add_website(args: argparse.Namespace, db: Session) -> None:
    client = find_client(db, args.client)
    if args.from_env:
        host = os.getenv("POSTHOG_HOST", "")
        project_id = os.getenv("POSTHOG_PROJECT_ID", "")
        api_key = os.getenv("POSTHOG_PERSONAL_API_KEY", "")
    else:
        if not (args.host and args.project_id):
            raise CliError("Give --host and --project-id (or --from-env).")
        host, project_id = args.host, str(args.project_id)
        api_key = read_secret("PostHog personal API key (hidden)", args.api_key_stdin)
    if not str(project_id).isdigit():
        raise CliError("The PostHog project id must be a number.")
    website = create_website(db, client, args.name, args.domain, host, int(project_id), api_key.strip(), not args.skip_check)
    audit(db, "cli.website_created", target_type="website", target_id=website.id, details={"client_id": str(client.id)})
    db.commit()
    print(f"Website added: {website.name} ({website.id}) for client {client.name}")


def cmd_add_user(args: argparse.Namespace, db: Session) -> None:
    client = find_client(db, args.client)
    email = normalize_email(args.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = create_user(db, email, args.name or "", read_new_password(args.password_stdin))
        print(f"User created: {user.email}")
    if db.get(ClientMember, (client.id, user.id)):
        raise CliError(f"{user.email} is already a member of {client.name}.")
    db.add(ClientMember(client_id=client.id, user_id=user.id, role=args.role))
    audit(db, "cli.member_added", target_type="user", target_id=user.id, details={"client_id": str(client.id), "role": args.role})
    db.commit()
    print(f"{user.email} can now see {client.name}'s websites (role: {args.role}).")


def cmd_set_password(args: argparse.Namespace, db: Session) -> None:
    user = find_user(db, args.email)
    user.password_hash = hash_password(read_new_password(args.password_stdin))
    user.token_version += 1  # logs them out everywhere
    audit(db, "cli.password_set", target_type="user", target_id=user.id)
    db.commit()
    print(f"Password changed for {user.email} (all their sessions were logged out).")


def cmd_set_client_status(args: argparse.Namespace, db: Session) -> None:
    client = find_client(db, args.client)
    client.status = args.status
    audit(db, "cli.client_status", target_type="client", target_id=client.id, details={"status": args.status})
    db.commit()
    print(f"{client.name} is now {args.status}.")


def cmd_delete_user(args: argparse.Namespace, db: Session) -> None:
    user = find_user(db, args.email)
    db.delete(user)  # memberships are deleted with it
    audit(db, "cli.user_deleted", target_type="user", target_id=user.id, details={"email": user.email})
    db.commit()
    print(f"Deleted {user.email}.")


def cmd_run_job(args: argparse.Namespace, db: Session) -> None:
    import asyncio

    from app import posthog_client
    from app.alerts import record_posthog_error
    from app.jobs import JOBS, run_job

    if args.name not in JOBS:
        raise CliError(f"No job '{args.name}'. Available: {', '.join(sorted(JOBS))}")

    async def go():
        await posthog_client.startup()
        posthog_client.error_listeners.append(record_posthog_error)
        try:
            return await run_job(args.name, "cli")
        finally:
            await posthog_client.shutdown()

    result = asyncio.run(go())
    print(f"{args.name}: {result['status']}. {result.get('message', '')}")
    if result["status"] == "error":
        raise CliError("The job failed (details are on the admin Jobs page).")


def cmd_list(_args: argparse.Namespace, db: Session) -> None:
    admins = db.scalars(select(User).where(User.is_admin.is_(True)).order_by(User.email)).all()
    print("ADMINS")
    for user in admins:
        print(f"  {user.email}  ({user.name or 'no name'})")
    for client in db.scalars(select(Client).order_by(Client.name)).all():
        print(f"\nCLIENT  {client.name}  [{client.status}]  id={client.id}")
        for website in sorted(client.websites, key=lambda w: w.name):
            print(f"  website  {website.name}  domain={website.domain or '-'}  project={website.posthog_project_id}  id={website.id}")
        for member in sorted(client.members, key=lambda m: m.user.email):
            print(f"  user     {member.user.email}  ({member.role})")


# ------------------------------------------------------------------ argument parsing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Manage clients, websites and users.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate-keys", help="print new JWT_SECRET / ENCRYPTION_KEY values")
    p.add_argument("--write-env", action="store_true", help="add any missing ones to backend/.env instead of printing")

    p = sub.add_parser("bootstrap", help="first setup: admin user + your website from .env")
    p.add_argument("--email")
    p.add_argument("--name")
    p.add_argument("--client-name")
    p.add_argument("--website-name")
    p.add_argument("--domain")
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--skip-check", action="store_true", help="don't test the PostHog key")

    p = sub.add_parser("create-admin", help="create another admin user")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--password-stdin", action="store_true")

    p = sub.add_parser("create-client", help="create a client (a business)")
    p.add_argument("--name", required=True)
    p.add_argument("--contact-email")
    p.add_argument("--phone")

    p = sub.add_parser("add-website", help="add a website (= a PostHog project) to a client")
    p.add_argument("--client", required=True, help="client name or id")
    p.add_argument("--name", required=True)
    p.add_argument("--domain")
    p.add_argument("--host", help="https://us.posthog.com or https://eu.posthog.com")
    p.add_argument("--project-id", type=int)
    p.add_argument("--from-env", action="store_true", help="use POSTHOG_* values from .env")
    p.add_argument("--api-key-stdin", action="store_true")
    p.add_argument("--skip-check", action="store_true", help="don't test the PostHog key")

    p = sub.add_parser("add-user", help="give a user (new or existing) access to a client")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--client", required=True, help="client name or id")
    p.add_argument("--role", choices=ROLES, default="viewer")
    p.add_argument("--password-stdin", action="store_true")

    p = sub.add_parser("set-password", help="set a user's password (logs them out everywhere)")
    p.add_argument("--email", required=True)
    p.add_argument("--password-stdin", action="store_true")

    p = sub.add_parser("set-client-status", help="suspend or re-activate a client")
    p.add_argument("--client", required=True)
    p.add_argument("--status", choices=("active", "suspended"), required=True)

    p = sub.add_parser("delete-user", help="delete a user")
    p.add_argument("--email", required=True)

    p = sub.add_parser("run-job", help="run a background job now")
    p.add_argument("name")

    sub.add_parser("list", help="show clients, websites and users")
    return parser


COMMANDS = {
    "bootstrap": cmd_bootstrap,
    "create-admin": cmd_create_admin,
    "create-client": cmd_create_client,
    "add-website": cmd_add_website,
    "add-user": cmd_add_user,
    "set-password": cmd_set_password,
    "set-client-status": cmd_set_client_status,
    "delete-user": cmd_delete_user,
    "list": cmd_list,
    "run-job": cmd_run_job,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate-keys":
            cmd_generate_keys(args)  # needs no database
            return 0
        with get_sessionmaker()() as db:
            COMMANDS[args.command](args, db)
        return 0
    except CliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
