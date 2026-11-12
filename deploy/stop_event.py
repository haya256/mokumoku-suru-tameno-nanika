import botocore.exceptions

import ec2_common

def main():
    state = ec2_common.load_state()
    ec2, _ = ec2_common.get_clients(state["region"])

    instance_id = state["instance_id"]
    print(f"{instance_id} を終了しています...")
    try:
        ec2.terminate_instances(InstanceIds=[instance_id])
        ec2.get_waiter("instance_terminated").wait(InstanceIds=[instance_id])
    except botocore.exceptions.ClientError as e:
        # 自動シャットダウンで破棄されてから時間がたつと、AWS側の記録からも消えてこのエラーになる
        if e.response["Error"]["Code"] != "InvalidInstanceID.NotFound":
            raise
        ec2_common.clear_state()
        print("インスタンスはすでに破棄されていました(自動シャットダウンで終了済み)。")
        return
    ec2_common.clear_state()
    print("終了しました。データはすべて破棄されました。")

if __name__ == "__main__":
    main()
