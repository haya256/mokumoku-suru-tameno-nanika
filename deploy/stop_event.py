import ec2_common

def main():
    state = ec2_common.load_state()
    ec2, _ = ec2_common.get_clients(state["region"])

    instance_id = state["instance_id"]
    print(f"{instance_id} を終了しています...")
    ec2.terminate_instances(InstanceIds=[instance_id])
    ec2.get_waiter("instance_terminated").wait(InstanceIds=[instance_id])
    ec2_common.clear_state()
    print("終了しました。データはすべて破棄されました。")

if __name__ == "__main__":
    main()
