"""Panel icin basit admin girisi (email + sifre).

Panel artik yerel agin/internetin disina acilabildigi icin (bkz. panel.py
start(), varsayilan host artik 0.0.0.0) sayfaya sadece tanimli adminlerin
girmesini saglar. Disaridan bagimlilik gerektirmez: sifreler PBKDF2-HMAC ile
tuzlanip hashlenir (duz metin hicbir yerde saklanmaz), oturumlar imzali bir
cerezle (HMAC-SHA256) takip edilir - stdlib disinda hicbir sey kullanilmaz.

Bu dosya kasitli olarak panel.py'den ayri: admin ekleme/silme main.py'nin
menu komutlarindan da cagrilabilsin diye (panel.py'yi import etmeden).
"""
import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time

ADMINS_FILE = "panel_admins.json"
SESSION_SECRET_FILE = ".panel_session_secret"
SESSION_COOKIE = "ajans_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 gun
PBKDF2_ITERATIONS = 200_000


def _load_admins():
    try:
        with open(ADMINS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_admins(admins):
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump(admins, f, ensure_ascii=False, indent=2)


def _hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return salt, digest.hex()


def add_admin(email, password):
    """Yeni admin ekler, e-posta zaten varsa sifresini gunceller."""
    email = email.strip().lower()
    salt, password_hash = _hash_password(password)
    admins = [a for a in _load_admins() if a["email"] != email]
    admins.append({"email": email, "salt": salt, "hash": password_hash})
    _save_admins(admins)


def remove_admin(email):
    email = email.strip().lower()
    admins = _load_admins()
    remaining = [a for a in admins if a["email"] != email]
    _save_admins(remaining)
    return len(remaining) != len(admins)


def list_admin_emails():
    return [a["email"] for a in _load_admins()]


def verify_admin(email, password):
    email = (email or "").strip().lower()
    for admin in _load_admins():
        if admin["email"] == email:
            _, computed_hash = _hash_password(password, admin["salt"])
            return hmac.compare_digest(computed_hash, admin["hash"])
    return False


def _get_session_secret():
    try:
        with open(SESSION_SECRET_FILE, "rb") as f:
            secret = f.read()
            if secret:
                return secret
    except FileNotFoundError:
        pass
    secret = secrets.token_bytes(32)
    with open(SESSION_SECRET_FILE, "wb") as f:
        f.write(secret)
    return secret


def create_session_token(email):
    expires_at = int(time.time()) + SESSION_MAX_AGE_SECONDS
    payload = f"{email}|{expires_at}".encode()
    signature = hmac.new(_get_session_secret(), payload, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(payload).decode("ascii") + "." + signature
    return token


def verify_session_token(token):
    """Gecerliyse e-postayi, degilse None dondurur."""
    if not token or "." not in token:
        return None
    encoded_payload, _, signature = token.partition(".")
    try:
        payload = base64.urlsafe_b64decode(encoded_payload.encode("ascii"))
    except (ValueError, binascii.Error):
        return None
    expected_signature = hmac.new(_get_session_secret(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return None
    try:
        email, expires_at = payload.decode("utf-8").rsplit("|", 1)
        expires_at = int(expires_at)
    except ValueError:
        return None
    if time.time() > expires_at:
        return None
    return email


def has_any_admin():
    return bool(_load_admins())
