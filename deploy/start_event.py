import base64
import re
import time

import botocore.exceptions

import ec2_common

SSM_WAIT_TIMEOUT_SEC = 180
SSM_POLL_INTERVAL_SEC = 5
URL_PATTERN = re.compile(r"https://[a-zA-Z0-9.-]*\.trycloudflare\.com")

def wait_for_ssm_online(ssm, instance_id, timeout=SSM_WAIT_TIMEOUT_SEC):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
        )
        infos = res.get("InstanceInformationList", [])
        if infos and infos[0].get("PingStatus") == "Online":
            return
        time.sleep(SSM_POLL_INTERVAL_SEC)
    raise SystemExit(
        "SSM Agent がオンラインになりませんでした。IAMインスタンスプロフィールに "
        "AmazonSSMManagedInstanceCore がアタッチされているか確認してください。"
    )

def fetch_tunnel_url(ssm, instance_id, timeout=SSM_WAIT_TIMEOUT_SEC):
    deadline = time.time() + timeout
    while time.time() < deadline:
        send_res = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": ["cat /var/log/tunnel_url.log 2>/dev/null || true"]},
        )
        command_id = send_res["Command"]["CommandId"]
        output = ""
        for _ in range(10):
            time.sleep(1)
            try:
                inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
            except botocore.exceptions.ClientError:
                continue
            if inv["Status"] in ("Pending", "InProgress", "Delayed"):
                continue
            output = inv.get("StandardOutputContent", "")
            break
        match = URL_PATTERN.search(output)
        if match:
            return match.group(0)
        time.sleep(SSM_POLL_INTERVAL_SEC)
    raise SystemExit(
        "トンネルURLの取得がタイムアウトしました。`aws ssm start-session --target "
        f"{instance_id}` で接続し、/var/log/mokumoku_userdata.log と "
        "/var/log/tunnel_raw.log を確認してください。"
    )

def main():
    deploy = ec2_common.load_deploy_config()
    passphrase_text, settings_json_text, discord_webhook_url = ec2_common.load_secrets()
    user_data = ec2_common.render_user_data(
        passphrase_text, settings_json_text, discord_webhook_url,
        deploy["auto_terminate_hours"],
    )

    ec2, ssm = ec2_common.get_clients(deploy["region"])

    print("インスタンスを起動しています...")
    image = ec2.describe_images(ImageIds=[deploy["ami_id"]])["Images"][0]
    root_device_name = image["RootDeviceName"]

    run_res = ec2.run_instances(
        ImageId=deploy["ami_id"],
        InstanceType=deploy["instance_type"],
        MinCount=1,
        MaxCount=1,
        SubnetId=deploy["subnet_id"],
        SecurityGroupIds=[deploy["security_group_id"]],
        IamInstanceProfile={"Name": deploy["iam_instance_profile_name"]},
        UserData=base64.b64encode(user_data.encode()).decode(),
        BlockDeviceMappings=[{
            "DeviceName": root_device_name,
            "Ebs": {"DeleteOnTermination": True},
        }],
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": "mokumoku-event"}],
        }],
    )
    instance_id = run_res["Instances"][0]["InstanceId"]
    ec2_common.save_state(instance_id, deploy["region"])
    print(f"起動中: {instance_id}")

    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
    print("起動完了。セットアップとトンネル接続を待っています(数分かかることがあります)...")

    wait_for_ssm_online(ssm, instance_id)
    url = fetch_tunnel_url(ssm, instance_id)

    print()
    print(f"参加者に共有するURL: {url}")
    print("イベント終了後は `python3 deploy/stop_event.py` を実行してください。")

if __name__ == "__main__":
    main()
