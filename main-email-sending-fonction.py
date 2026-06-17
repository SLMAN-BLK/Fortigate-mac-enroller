from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import uvicorn
import re
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.core.exceptions import LDAPException, LDAPBindError

import requests as http_requests
import urllib3
import pymysql
from jose import jwt, JWTError


import smtplib
from email.message import EmailMessage

# Suppress SSL warnings for FortiGate (no cert in lab)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────
SECRET_KEY       = os.getenv("SECRET_KEY", "change-me")
ALGORITHM        = "HS256"
TOKEN_EXPIRE_MIN = int(os.getenv("TOKEN_EXPIRE_MIN", 30))

AD_PORT        = int(os.getenv("AD_PORT", 389))
AD_DOMAIN      = os.getenv("AD_DOMAIN")
AD_BASE_DN     = os.getenv("AD_BASE_DN")
AD_SERVERS     = [s.strip() for s in os.getenv("AD_SERVERS", "").split(",") if s.strip()]
AD_READER_USER = os.getenv("AD_READER_USER")
AD_READER_PASS = os.getenv("AD_READER_PASS")

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")

# ── FortiGate routing map ─────────────────────────────────────
# Key = normalised company value from AD (lowercase)
# Each entry: ip, api_key, group (address group name)
FORTIGATE_MAP: dict[str, dict] = {
    "tfc": {
        "ip":    os.getenv("FG_TFC_IP"),
        "user":  os.getenv("FG_TFC_USER"),
        "key":   os.getenv("FG_TFC_KEY"),
        "group": os.getenv("FG_TFC_GROUP"),
    },
    "dfc": {
        "ip":    os.getenv("FG_DFC_IP"),
        "user":  os.getenv("FG_DFC_USER"),
        "key":   os.getenv("FG_DFC_KEY"),
        "group": os.getenv("FG_DFC_GROUP"),
    },
    "rmc": {
        "ip":    os.getenv("FG_RMC_IP"),
        "user":  os.getenv("FG_RMC_USER"),
        "key":   os.getenv("FG_RMC_KEY"),
        "group": os.getenv("FG_RMC_GROUP"),
    },
}

# ──────────────────────────────────────────────────────────────
# APP SETUP
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ──────────────────────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────────────────────
def get_db():
    return pymysql.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASS,
        database=DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )

def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mac_registrations (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    ad_username   VARCHAR(100) NOT NULL,
                    ad_email      VARCHAR(200),
                    ad_ou_path    TEXT,
                    ad_company    VARCHAR(100),
                    mac_owner     VARCHAR(150) NOT NULL,
                    mac_address   VARCHAR(17)  NOT NULL,
                    fortigate_ip  VARCHAR(50),
                    fg_group      VARCHAR(100),
                    registered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_mac     (mac_address),
                    INDEX idx_user    (ad_username),
                    INDEX idx_company (ad_company)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            conn.commit()
        log.info("DB table ready.")
    finally:
        conn.close()

def db_save(user: dict, owner: str, mac: str, fg: dict):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO mac_registrations
                    (ad_username, ad_email, ad_ou_path, ad_company,
                     mac_owner, mac_address, fortigate_ip, fg_group)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                user["username"],
                user["email"],
                " > ".join(user["ou_path"]),
                user.get("company", ""),
                owner,
                mac,
                fg["ip"],
                fg["group"],
            ))
            conn.commit()
    finally:
        conn.close()

# ──────────────────────────────────────────────────────────────
# JWT
# ──────────────────────────────────────────────────────────────
def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MIN)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

# ──────────────────────────────────────────────────────────────
# LDAP — multi-DC failover
# ──────────────────────────────────────────────────────────────
def ldap_authenticate(username: str, password: str) -> dict:
    """
    Try each AD server in sequence until one responds.
    Step 1 — bind with user credentials (authentication).
    Step 2 — rebind as reader to fetch attributes (least privilege).
    """
    if not username or not password:
        raise ValueError("Username and password required")

    bare   = username.split("@")[0].split("\\")[-1]
    user_dn = f"{bare}@{AD_DOMAIN}"

    if not AD_SERVERS:
        raise ValueError("No AD servers configured")

    last_error = "Cannot reach any directory server"

    for ad_ip in AD_SERVERS:
        log.info("Trying AD server: %s", ad_ip)
        try:
            server = Server(ad_ip, port=AD_PORT, get_info=ALL, connect_timeout=4)

            # ── Step 1: authenticate ──
            try:
                auth_conn = Connection(
                    server, user=user_dn, password=password,
                    auto_bind=True, receive_timeout=6
                )
                auth_conn.unbind()
            except LDAPBindError:
                # Wrong password — stop trying other DCs immediately
                raise ValueError("Invalid username or password")

            # ── Step 2: fetch attributes via reader ──
            reader = Connection(
                server,
                user=AD_READER_USER,
                password=AD_READER_PASS,
                auto_bind=True,
                receive_timeout=6,
            )
            reader.search(
                search_base=AD_BASE_DN,
                search_filter=f"(sAMAccountName={bare})",
                search_scope=SUBTREE,
                attributes=[
                    "cn", "mail", "distinguishedName",
                    "sAMAccountName", "company",
                ],
            )

            if not reader.entries:
                reader.unbind()
                raise ValueError("User not found in directory")

            entry = reader.entries[0]
            reader.unbind()

            dn      = str(entry.distinguishedName)
            company = str(entry.company).strip() if entry.company else ""

            log.info(
                "Authenticated %s via %s | company=%s",
                bare, ad_ip, company
            )

            return {
                "username":  str(entry.sAMAccountName),
                "full_name": str(entry.cn),
                "email":     str(entry.mail) if entry.mail else "",
                "dn":        dn,
                "ou_path":   parse_ou_path(dn),
                "company":   company,
                "ad_server": ad_ip,
            }

        except ValueError:
            raise   # wrong password or user-not-found — don't retry
        except LDAPException as e:
            log.warning("AD %s unreachable: %s", ad_ip, e)
            last_error = f"AD server {ad_ip} unreachable"
            continue    # try next DC

    raise ValueError(last_error)


def parse_ou_path(dn: str) -> list[str]:
    parts = [p.strip() for p in dn.split(",")]
    ous   = [p[3:] for p in parts if p.upper().startswith("OU=")]
    ous.reverse()
    return ous


def resolve_fortigate(company: str) -> dict:
    """
    Return the FortiGate config dict for the given company value.
    Raises ValueError if unknown / not configured.
    """
    key = company.strip().lower()
    fg  = FORTIGATE_MAP.get(key)
    if not fg or not fg.get("ip"):
        known = ", ".join(FORTIGATE_MAP.keys())
        raise ValueError(
            f"Organisation '{company}' is not mapped to any FortiGate. "
            f"Known organisations: {known}"
        )
    return fg

# ──────────────────────────────────────────────────────────────
# INPUT SANITISATION
# ──────────────────────────────────────────────────────────────
MAC_RE = re.compile(
    r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$"
    r"|^[0-9A-Fa-f]{12}$"
)
OWNER_RE = re.compile(r"^[A-Za-z0-9 _\-\.]{2,80}$")

def normalize_mac(raw: str) -> str:
    raw = raw.strip()
    if not MAC_RE.match(raw):
        raise ValueError("Invalid MAC address format")
    clean = re.sub(r"[:\-]", "", raw).upper()
    return ":".join(clean[i:i+2] for i in range(0, 12, 2))

def sanitize_owner(raw: str) -> str:
    raw = raw.strip()
    if not OWNER_RE.match(raw):
        raise ValueError(
            "Owner name must be 2–80 characters "
            "(letters, numbers, spaces, hyphens, dots allowed)"
        )
    return raw

# ──────────────────────────────────────────────────────────────
# FORTIGATE HELPERS
# ──────────────────────────────────────────────────────────────
def fg_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

def fg_base(ip: str) -> str:
    return f"https://{ip}/api/v2/cmdb"



def fg_create_mac_address(fg: dict, obj_name: str, mac: str, owner: str, user: dict):
    headers = fg_headers(fg["key"])
    base_url = fg_base(fg["ip"])

    # ── Check if object already exists ──
    check = http_requests.get(
        f"{base_url}/firewall/address/{obj_name}",
        headers=headers,
        timeout=10,
        verify=False
    )

    if check.status_code == 200:
        existing = check.json().get("results", [{}])[0]
        if existing.get("name") == obj_name:
            log.info(
                "FortiGate [%s] address '%s' already exists, skipping create.",
                fg["ip"], obj_name
            )
            return

    # ── Create MAC address object ──
    payload = {
        "name": obj_name,   # ✅ MUST be obj_name (FortiGate ID)
        "type": "mac",
        "sub-type": "ems",  # required for FGT 7.6 MAC objects
        "macaddr": [{"macaddr": mac}],
        "comment": f"Owner: {owner} | Added By: {user.get('username', 'unknown')}",
        "color": 0,
    }

    r = http_requests.post(
        f"{base_url}/firewall/address",
        headers=headers,
        json=payload,
        timeout=10,
        verify=False
    )

    if r.status_code not in (200, 201):
        raise RuntimeError(
            f"FortiGate [{fg['ip']}] address create failed: "
            f"{r.status_code} {r.text[:300]}"
        )

    # ── Verify creation ──
    verify = http_requests.get(
        f"{base_url}/firewall/address/{obj_name}",
        headers=headers,
        timeout=10,
        verify=False
    )

    if verify.status_code != 200:
        raise RuntimeError(
            f"FortiGate [{fg['ip']}] address '{obj_name}' not found after create"
        )

    result = verify.json().get("results", [{}])[0]

    if not result.get("macaddr"):
        log.warning(
            "FortiGate [%s] address '%s' created but macaddr empty, retrying with sub-type=sdn",
            fg["ip"], obj_name
        )

        http_requests.delete(
            f"{base_url}/firewall/address/{obj_name}",
            headers=headers,
            timeout=10,
            verify=False
        )

        payload["sub-type"] = "sdn"

        r2 = http_requests.post(
            f"{base_url}/firewall/address",
            headers=headers,
            json=payload,
            timeout=10,
            verify=False
        )

        verify2 = http_requests.get(
            f"{base_url}/firewall/address/{obj_name}",
            headers=headers,
            timeout=10,
            verify=False
        )

        result2 = verify2.json().get("results", [{}])[0]

        if not result2.get("macaddr"):
            raise RuntimeError(
                f"FortiGate [{fg['ip']}] address '{obj_name}' macaddr still empty after retry"
            )

    log.info(
        "FortiGate [%s] address object '%s' created with MAC %s (owner=%s).",
        fg["ip"], obj_name, mac, owner
    )



def fg_add_to_group(fg: dict, obj_name: str ,user: dict,owner: str ,mac:str):
    headers = fg_headers(fg["key"])
    group   = fg["group"]
    url     = f"{fg_base(fg['ip'])}/firewall/addrgrp/{group}"

    # GET current group object
    r = http_requests.get(url, headers=headers, timeout=10, verify=False)
    if r.status_code != 200:
        raise RuntimeError(
            f"FortiGate [{fg['ip']}] group '{group}' fetch failed: "
            f"{r.status_code} {r.text[:300]}"
        )

    result = r.json().get("results", [{}])[0]

    # Strip members to name-only (FortiGate rejects q_origin_key etc. on write)
    clean_members = [{"name": m["name"]} for m in result.get("member", []) if m.get("name")]
    clean_members.append({"name": obj_name})

    # FortiGate 7.6 requires the full group object in the PUT body —
    # sending only {"member": [...]} returns 424.
    payload = {
        "name":           result.get("name", group),
        "member":         clean_members,
        "comment":        result.get("comment", ""),
        "allow-routing":  result.get("allow-routing", "disable"),
        "color":          result.get("color", 0),
        "exclude":        result.get("exclude", "disable"),
        "exclude-member": [],
        "fabric-object":  result.get("fabric-object", "disable"),
    }

    log.info(
        "FortiGate [%s] PUT group '%s' — %d members — adding '%s'",
        fg["ip"], group, len(clean_members), obj_name
    )

    r2 = http_requests.put(
        url, headers=headers, json=payload,
        timeout=10, verify=False,
    )
    if r2.status_code != 200:
        log.error(
            "FortiGate [%s] group PUT failed — %s — %s",
            fg["ip"], r2.status_code, r2.text[:500]
        )
        raise RuntimeError(
            f"FortiGate [{fg['ip']}] group '{group}' update failed: "
            f"{r2.status_code} {r2.text[:300]}"
        )
    log.info(
        "FortiGate [%s] successfully added '%s' to group '%s'.",
        fg["ip"], obj_name, group
    )

    try:
        with smtplib.SMTP('localhost', 25) as server:
            print("Connected to Postfix. Sending notification...\n")

            msg = EmailMessage()

            # Removed the undefined {slimane} and {name} variables
            # Using the variables already passed into your function
#            email_body = f"""Hello,
#FortiGate {fg["ip"]} in {user.get("company", "")} successfully added mac : {mac} To {owner} This MAC Was added By {user["username"]}   .
#"""
            email_body = f"""
Bonjour,

Nous vous informons que l'adresse MAC suivante a été ajoutée avec succès sur le pare-feu FortiGate :

- Adresse IP du FortiGate : {fg["ip"]}
- Société : {user.get("company", "")}
- Adresse MAC ajoutée : {mac}
- Propriétaire / Utilisateur concerné : {owner}
- Ajout effectué par : {user["username"]}

L'opération a été réalisée avec succès et la nouvelle adresse MAC est désormais autorisée selon la configuration en vigueur sur l'équipement.

Cordialement,

Système de gestion des accès réseau
"""
            msg.set_content(email_body)
            msg['Subject'] = f"FortiGate Update: {obj_name} added to {group}"
            msg['From'] = "Put-your-email-here"
            msg['To'] = "put-resiver-email-here"

            # Send the email
            server.send_message(msg)
            print("Email successfully handed off to Postfix!")

    except ConnectionRefusedError:
        print("Error: Connection refused. Is Postfix running on localhost port 25?")
    except Exception as e:
        # If something fails, this will tell you exactly what it was
        print(f"An email error occurred: {e}")







# ──────────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": None}
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    try:
        user_info = ldap_authenticate(username, password)
    except ValueError as e:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": str(e)}
        )

    token = create_token(user_info)
    resp  = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(
        key="session", value=token,
        httponly=True, samesite="lax",
        max_age=TOKEN_EXPIRE_MIN * 60,
    )
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    # Resolve FortiGate for display (non-blocking — just for the UI badge)
    fg_info = None
    fg_error = None
    try:
        fg_info = resolve_fortigate(user.get("company", ""))
    except ValueError as e:
        fg_error = str(e)

    return templates.TemplateResponse("dashboard.html", {
        "request":  request,
        "user":     user,
        "fg_info":  fg_info,
        "fg_error": fg_error,
        "error":    None,
        "success":  None,
    })


@app.post("/submit", response_class=HTMLResponse)
async def submit_mac(
    request: Request,
    mac_owner:   str = Form(...),
    mac_address: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    error   = None
    success = None
    fg_info = None
    fg_error = None

    try:
        # ── resolve FortiGate from company field ──
        fg       = resolve_fortigate(user.get("company", ""))
        fg_info  = fg

        owner    = sanitize_owner(mac_owner)
        mac      = normalize_mac(mac_address)
        obj_name = owner

        fg_create_mac_address(fg, obj_name, mac, owner,user)
        fg_add_to_group(fg, obj_name ,user ,owner ,mac )
        db_save(user, owner, mac, fg)

        log.info(
            "Registered MAC %s (owner: %s) by %s → FG %s group %s",
            mac, owner, user["username"], fg["ip"], fg["group"]
        )
        success = (
            f"MAC address {mac} registered successfully "
            f"to group '{fg['group']}' on FortiGate {fg['ip']}."
        )

    except ValueError as e:
        error = str(e)
        try:
            fg_info = resolve_fortigate(user.get("company", ""))
        except ValueError as fe:
            fg_error = str(fe)
    except RuntimeError as e:
        log.error("FortiGate error: %s", e)
        error = str(e)
        try:
            fg_info = resolve_fortigate(user.get("company", ""))
        except ValueError as fe:
            fg_error = str(fe)
    except Exception as e:
        log.error("Unexpected error: %s", e)
        error = "An unexpected error occurred. Please contact your administrator."

    return templates.TemplateResponse("dashboard.html", {
        "request":  request,
        "user":     user,
        "fg_info":  fg_info,
        "fg_error": fg_error,
        "error":    error,
        "success":  success,
    })


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("session")
    return resp


# ──────────────────────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    log.info("AD servers configured: %s", AD_SERVERS)
    log.info("FortiGate map: %s", {k: v["ip"] for k, v in FORTIGATE_MAP.items()})
    try:
        init_db()
    except Exception as e:
        log.error("DB init failed: %s", e)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
