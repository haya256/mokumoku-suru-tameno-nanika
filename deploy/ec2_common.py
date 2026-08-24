import base64
import json
import os
import string
import sys

import boto3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO_ROOT, "config", "settings.json")
PASSPHRASE_FILE = os.path.join(REPO_ROOT, "config", "合言葉.txt")
STATE_FILE = os.path.join(REPO_ROOT, "deploy", ".current_instance")
USER_DATA_TEMPLATE = os.path.join(REPO_ROOT, "deploy", "user_data.sh")

REQUIRED_DEPLOY_KEYS = [
    "region", "instance_type", "ami_id",
    "security_group_id", "subnet_id", "iam_instance_profile_name",
]

def load_deploy_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            settings = json.load(f)
    except OSError:
        sys.exit(
            f"{CONFIG_FILE} が見つかりません。\n"
            "config/settings.sample.json を config/settings.json にコピーし、"
            "deploy セクションを自分のAWS環境の値で埋めてください。"
        )
    deploy = settings.get("deploy", {})
    missing = [k for k in REQUIRED_DEPLOY_KEYS if not deploy.get(k)]
    if missing:
        sys.exit(
            f"{CONFIG_FILE} の deploy セクションに未設定の項目があります: {', '.join(missing)}\n"
            "config/settings.sample.json を参考に埋めてください。"
        )
    deploy.setdefault("auto_terminate_hours", 6)
    return deploy

def load_secrets():
    try:
        with open(PASSPHRASE_FILE, encoding="utf-8") as f:
            passphrase_text = f.read()
    except OSError:
        passphrase_text = ""
    with open(CONFIG_FILE, encoding="utf-8") as f:
        settings_json_text = f.read()
    discord_webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    return passphrase_text, settings_json_text, discord_webhook_url

def render_user_data(passphrase_text, settings_json_text, discord_webhook_url, auto_terminate_hours):
    with open(USER_DATA_TEMPLATE, encoding="utf-8") as f:
        template = string.Template(f.read())
    return template.substitute(
        PASSPHRASE_B64=base64.b64encode(passphrase_text.encode()).decode(),
        SETTINGS_JSON_B64=base64.b64encode(settings_json_text.encode()).decode(),
        DISCORD_WEBHOOK_URL=discord_webhook_url,
        AUTO_TERMINATE_MINUTES=str(int(auto_terminate_hours * 60)),
    )

def get_clients(region):
    session = boto3.Session(region_name=region)
    return session.client("ec2"), session.client("ssm")

def save_state(instance_id, region):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"instance_id": instance_id, "region": region}, f)

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        sys.exit(
            f"{STATE_FILE} が見つかりません。start_event.py で起動したインスタンスがないか、"
            "すでに停止済みです。"
        )

def clear_state():
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass
