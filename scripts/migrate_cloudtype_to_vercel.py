#!/usr/bin/env python3
"""Run the Cloudtype -> Vercel + Supabase migration steps.

This script intentionally reads secrets from the environment or an ignored
env file. It never writes secret values into the repository.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT_DIR / ".secrets" / "migration.env"
DEFAULT_SUPABASE_REGION = "ap-northeast-2"
DEFAULT_SUPABASE_SIZE = "nano"
DEFAULT_SUPABASE_PROJECT = "soulib"
DEFAULT_VERCEL_PROJECT = "soulib"
DEFAULT_PUBLIC_BASE_URL = "https://www.soulib.kr"
DEFAULT_GITHUB_ISSUE_REPO = "pkkong/library_crawler"
SENSITIVE_KEYS = {
    "DATABASE_URL",
    "GITHUB_ISSUE_TOKEN",
    "SUPABASE_ACCESS_TOKEN",
    "SUPABASE_DB_PASSWORD",
    "VERCEL_TOKEN",
}


def mask(value):
    text = str(value)
    if not text:
        return ""
    if len(text) <= 10:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def display_command(cmd):
    rendered = []
    skip_next = False
    for index, part in enumerate(cmd):
        if skip_next:
            skip_next = False
            continue
        if part in {"--token", "--db-password", "--password", "-p", "--value"} and index + 1 < len(cmd):
            rendered.extend([part, "***"])
            skip_next = True
        elif any(secret and secret in part for secret in (os.environ.get(k, "") for k in SENSITIVE_KEYS)):
            rendered.append("***")
        else:
            rendered.append(shlex.quote(str(part)))
    return " ".join(rendered)


def load_env_file(path):
    path = Path(path)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def optional_env(name, default=""):
    return os.environ.get(name, default).strip()


def run(cmd, *, cwd=ROOT_DIR, capture=True, env=None):
    print(f"+ {display_command(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env or os.environ.copy(),
        text=True,
        capture_output=capture,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    if capture and result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.stdout.strip() if capture else ""


def find_command(name, env_name=None):
    if env_name and optional_env(env_name):
        path = optional_env(env_name)
        if Path(path).exists():
            return path
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(f"{name} CLI was not found. Install it or set {env_name}.")


def parse_json_or_fail(text, label):
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} did not return JSON: {text[:500]}") from exc


def vercel_base_cmd(vercel_cli, token):
    cmd = [vercel_cli]
    scope = optional_env("VERCEL_SCOPE") or optional_env("VERCEL_TEAM")
    if scope:
        cmd.extend(["--scope", scope])
    cmd.extend(["--token", token])
    return cmd


def supabase_base_env():
    env = os.environ.copy()
    token = optional_env("SUPABASE_ACCESS_TOKEN")
    if token:
        env["SUPABASE_ACCESS_TOKEN"] = token
    return env


def list_supabase_orgs(supabase_cli):
    output = run(
        [supabase_cli, "orgs", "list", "--output", "json"],
        env=supabase_base_env(),
    )
    data = parse_json_or_fail(output, "supabase orgs list")
    if isinstance(data, dict) and "organizations" in data:
        data = data["organizations"]
    if not isinstance(data, list):
        raise SystemExit("supabase orgs list returned an unexpected shape.")
    return data


def choose_supabase_org(supabase_cli):
    org_id = optional_env("SUPABASE_ORG_ID")
    if org_id:
        return org_id
    orgs = list_supabase_orgs(supabase_cli)
    if len(orgs) == 1:
        org = orgs[0]
        return str(org.get("id") or org.get("slug") or org.get("name"))
    names = []
    for org in orgs:
        names.append(f"{org.get('id') or org.get('slug')} ({org.get('name')})")
    raise SystemExit(
        "SUPABASE_ORG_ID is required because the token can access multiple organizations: "
        + ", ".join(names)
    )


def create_supabase_project_if_needed(supabase_cli):
    project_ref = optional_env("SUPABASE_PROJECT_REF")
    if project_ref:
        return project_ref

    require_env("SUPABASE_ACCESS_TOKEN")
    org_id = choose_supabase_org(supabase_cli)
    project_name = optional_env("SUPABASE_PROJECT_NAME", DEFAULT_SUPABASE_PROJECT)
    region = optional_env("SUPABASE_REGION", DEFAULT_SUPABASE_REGION)
    size = optional_env("SUPABASE_SIZE", DEFAULT_SUPABASE_SIZE)
    password = ensure_supabase_db_password()

    output = run(
        [
            supabase_cli,
            "projects",
            "create",
            project_name,
            "--org-id",
            org_id,
            "--db-password",
            password,
            "--region",
            region,
            "--size",
            size,
            "--output",
            "json",
        ],
        env=supabase_base_env(),
    )
    data = parse_json_or_fail(output, "supabase projects create")
    project_ref = str(data.get("id") or data.get("ref") or data.get("project_ref") or "")
    if not project_ref:
        project_ref = wait_for_supabase_project_ref(supabase_cli, project_name)
    os.environ["SUPABASE_PROJECT_REF"] = project_ref
    return project_ref


def wait_for_supabase_project_ref(supabase_cli, project_name):
    for _ in range(30):
        output = run([supabase_cli, "projects", "list", "--output", "json"], env=supabase_base_env())
        data = parse_json_or_fail(output, "supabase projects list")
        if isinstance(data, dict) and "projects" in data:
            data = data["projects"]
        for project in data or []:
            if project.get("name") == project_name:
                return str(project.get("id") or project.get("ref") or project.get("project_ref"))
        time.sleep(10)
    raise SystemExit("Created Supabase project was not found in project list.")


def ensure_supabase_db_password():
    password = optional_env("SUPABASE_DB_PASSWORD")
    if password:
        return password
    generated = secrets.token_urlsafe(32)
    secrets_dir = ROOT_DIR / ".secrets"
    secrets_dir.mkdir(exist_ok=True)
    password_file = secrets_dir / "supabase_db_password.generated"
    password_file.write_text(generated + "\n", encoding="utf-8")
    os.chmod(password_file, 0o600)
    os.environ["SUPABASE_DB_PASSWORD"] = generated
    print(f"Generated SUPABASE_DB_PASSWORD and wrote it to {password_file}.")
    return generated


def build_supabase_database_url(project_ref):
    existing = optional_env("DATABASE_URL")
    if existing:
        return existing
    password = ensure_supabase_db_password()
    region = optional_env("SUPABASE_REGION", DEFAULT_SUPABASE_REGION)
    user = f"postgres.{project_ref}"
    encoded_user = urllib.parse.quote(user, safe="")
    encoded_password = urllib.parse.quote(password, safe="")
    host = optional_env("SUPABASE_POOLER_HOST", f"aws-1-{region}.pooler.supabase.com")
    return f"postgres://{encoded_user}:{encoded_password}@{host}:6543/postgres?sslmode=require"


def apply_supabase_migrations(database_url):
    try:
        import psycopg2
    except Exception as exc:
        raise SystemExit("psycopg2 is required. Run this script with the project .venv Python.") from exc

    migration_dir = ROOT_DIR / "supabase" / "migrations"
    migration_files = sorted(migration_dir.glob("*.sql"))
    if not migration_files:
        raise SystemExit(f"No Supabase migrations found in {migration_dir}.")

    print("+ apply Supabase migrations")
    conn = None
    last_error = None
    for _ in range(30):
        try:
            conn = psycopg2.connect(database_url)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    if conn is None:
        raise SystemExit(f"Could not connect to Supabase Postgres: {last_error}")
    try:
        with conn.cursor() as cur:
            for migration in migration_files:
                print(f"  - {migration.relative_to(ROOT_DIR)}")
                cur.execute(migration.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def configure_vercel_project(vercel_cli, database_url):
    token = require_env("VERCEL_TOKEN")
    project = optional_env("VERCEL_PROJECT", DEFAULT_VERCEL_PROJECT)

    link_cmd = [vercel_cli, "link", "--yes", "--project", project, "--token", token]
    team = optional_env("VERCEL_SCOPE") or optional_env("VERCEL_TEAM")
    if team:
        link_cmd.extend(["--team", team])
    run(link_cmd)

    env_values = {
        "PUBLIC_BASE_URL": optional_env("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL),
        "GITHUB_ISSUE_TOKEN": require_env("GITHUB_ISSUE_TOKEN"),
        "GITHUB_ISSUE_REPO": optional_env("GITHUB_ISSUE_REPO", DEFAULT_GITHUB_ISSUE_REPO),
        "DATABASE_URL": database_url,
        "SHARED_SHELVES_STORAGE": optional_env("SHARED_SHELVES_STORAGE", "auto"),
    }
    passthrough = [
        "API_CORS_ALLOWED_ORIGINS",
        "GITHUB_ISSUE_LABELS",
        "GITHUB_ISSUE_TIMEOUT",
        "LIVE_DETAIL_CACHE_SIZE",
        "LIVE_SEARCH_CACHE_SIZE",
        "LIVE_SEARCH_LIBRARY_TIMEOUT",
        "LIVE_SEARCH_MAX_WORKERS",
        "LIVE_SEARCH_PER_LIBRARY_LIMIT",
        "LIVE_SEARCH_TOTAL_TIMEOUT",
        "LIVE_SEARCH_TTL_SEC",
        "SITEMAP_BASE_URL",
    ]
    for name in passthrough:
        value = optional_env(name)
        if value:
            env_values[name] = value

    for name, value in env_values.items():
        run(
            vercel_base_cmd(vercel_cli, token)
            + ["env", "add", name, "production", "--value", value, "--yes", "--force"]
        )


def add_vercel_domain_if_requested(vercel_cli):
    domain = optional_env("VERCEL_DOMAIN")
    if not domain:
        return
    token = require_env("VERCEL_TOKEN")
    project = optional_env("VERCEL_PROJECT", DEFAULT_VERCEL_PROJECT)
    run(vercel_base_cmd(vercel_cli, token) + ["domains", "add", domain, project])


def deploy_to_vercel(vercel_cli):
    token = require_env("VERCEL_TOKEN")
    output = run(
        vercel_base_cmd(vercel_cli, token)
        + ["deploy", "--prod", "--yes", "--format", "json"]
    )
    try:
        data = json.loads(output)
        url = data.get("url") or data.get("deploymentUrl") or data.get("alias", [None])[0]
    except Exception:
        url = output.splitlines()[-1].strip()
    if not url:
        raise SystemExit("Vercel deploy did not return a deployment URL.")
    if not url.startswith("http"):
        url = f"https://{url}"
    print(f"deployment_url={url}")
    return url


def run_live_smoke(url, *, skip_shared=False):
    cmd = [sys.executable, str(ROOT_DIR / "scripts" / "live_smoke.py"), url]
    if skip_shared:
        cmd.append("--skip-shared")
    run(cmd, capture=False)


def main():
    parser = argparse.ArgumentParser(description="Migrate Soulib from Cloudtype to Vercel + Supabase.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Ignored env file with migration secrets.")
    parser.add_argument("--skip-supabase-create", action="store_true", help="Require DATABASE_URL or SUPABASE_PROJECT_REF instead of creating a Supabase project.")
    parser.add_argument("--skip-db-migration", action="store_true", help="Skip applying SQL migrations.")
    parser.add_argument("--skip-vercel-deploy", action="store_true", help="Configure env but do not deploy.")
    parser.add_argument("--skip-live-smoke", action="store_true", help="Skip smoke test against the deployment URL.")
    parser.add_argument("--skip-shared-smoke", action="store_true", help="Skip shared shelf checks in live smoke.")
    args = parser.parse_args()

    load_env_file(args.env_file)

    vercel_cli = find_command("vercel", "VERCEL_CLI")
    supabase_cli = None
    project_ref = optional_env("SUPABASE_PROJECT_REF")
    if optional_env("DATABASE_URL"):
        database_url = optional_env("DATABASE_URL")
    else:
        supabase_cli = find_command("supabase", "SUPABASE_CLI")
        if args.skip_supabase_create and not project_ref:
            raise SystemExit("DATABASE_URL or SUPABASE_PROJECT_REF is required with --skip-supabase-create.")
        if not args.skip_supabase_create:
            project_ref = create_supabase_project_if_needed(supabase_cli)
        database_url = build_supabase_database_url(project_ref)

    print(f"Using DATABASE_URL={mask(database_url)}")

    if not args.skip_db_migration:
        apply_supabase_migrations(database_url)

    configure_vercel_project(vercel_cli, database_url)
    add_vercel_domain_if_requested(vercel_cli)

    if args.skip_vercel_deploy:
        print("Skipped Vercel deploy.")
        return

    deployment_url = deploy_to_vercel(vercel_cli)
    if not args.skip_live_smoke:
        run_live_smoke(deployment_url, skip_shared=args.skip_shared_smoke)


if __name__ == "__main__":
    main()
