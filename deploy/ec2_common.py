import base64
import json
import os
import string
import sys

import boto3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO_ROOT, "config", "settings.json")
# 合言葉ファイルの既定の場所(リポジトリのルートからの相対パス)。mokumoku/settings.py の既定値と同じ。
# インスタンス上では user_data.sh が必ずこの場所に書く
DEFAULT_PASSPHRASE_FILE = "config/合言葉.txt"
DEFAULT_ADMIN_PASSPHRASE_FILE = "config/管理者合言葉.txt"
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

def read_optional(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""

# 手元の合言葉は、サーバーと同じく settings.json の security.passphrase_file / admin_passphrase_file が
# 指す場所から読む(未指定なら既定の場所)。インスタンスに渡す settings.json では、この2つを既定の場所に
# 書き換える。user_data.sh が合言葉を書くのは既定の場所なので、そのまま渡すと場所が食い違って
# 合言葉なしで入室できる状態になってしまう
def load_secrets():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        settings = json.load(f)
    security = settings.get("security") if isinstance(settings.get("security"), dict) else {}
    passphrase_text = read_optional(
        os.path.join(REPO_ROOT, security.get("passphrase_file") or DEFAULT_PASSPHRASE_FILE))
    admin_passphrase_text = read_optional(
        os.path.join(REPO_ROOT, security.get("admin_passphrase_file") or DEFAULT_ADMIN_PASSPHRASE_FILE))
    shipped = {**settings, "security": {**security, "passphrase_file": DEFAULT_PASSPHRASE_FILE,
                                        "admin_passphrase_file": DEFAULT_ADMIN_PASSPHRASE_FILE}}
    settings_json_text = json.dumps(shipped, ensure_ascii=False, indent=2)
    discord_webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    return passphrase_text, admin_passphrase_text, settings_json_text, discord_webhook_url

def render_user_data(passphrase_text, admin_passphrase_text, settings_json_text, discord_webhook_url,
                     auto_terminate_hours):
    with open(USER_DATA_TEMPLATE, encoding="utf-8") as f:
        template = string.Template(f.read())
    return template.substitute(
        PASSPHRASE_B64=base64.b64encode(passphrase_text.encode()).decode(),
        ADMIN_PASSPHRASE_B64=base64.b64encode(admin_passphrase_text.encode()).decode(),
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
