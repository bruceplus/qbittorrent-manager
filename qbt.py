import math
import qbittorrentapi
import csv
import sys
import datetime
from collections import defaultdict
import yaml
import os

# 读取主配置文件
with open("config.yml", "r", encoding="utf-8") as f:  # 添加 encoding="utf-8"
    main_config = yaml.safe_load(f)
env_name = main_config["use_env"]

# 读取环境特定的配置文件
config_path = os.path.join("config", f"{env_name}.yaml")
with open(config_path, "r", encoding="utf-8") as f:  # 添加 encoding="utf-8"
    config = yaml.safe_load(f)
    
# 从配置文件中提取配置
qb_host = config["qbittorrent"]["host"]
qb_port = config["qbittorrent"]["port"]
qb_username = config["qbittorrent"]["username"]
qb_password = config["qbittorrent"]["password"]
delete_files_on_remove = config["delete_files_on_remove"]
required_trackers = config["required_trackers"]
required_summer = config["required_summer"]
upload_speed_limits_by_tracker = config["upload_speed_limits_by_tracker"]
export_deduplicate = config.get("export_options", {}).get("deduplicate", True)

# 登录客户端

client = qbittorrentapi.Client(
    host=qb_host, port=qb_port, username=qb_username, password=qb_password
)
try:
    client.auth_log_in()
    print("登录成功！")
except qbittorrentapi.LoginFailed as e:
    print(f"登录失败: {e}")
    exit(1)
    
def convert_size(size_bytes):
    """
    将字节大小转换为合适的单位
    :param size_bytes: 字节大小
    :return: 转换后的字符串，如 "1.23 GB"
    """
    if size_bytes == 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    i = min(int(math.log(size_bytes, 1024)), len(units) - 1)
    size = round(size_bytes / (1024 ** i), 2)
    return f"{size} {units[i]}"


def check_missing_trackers():
    torrents = client.torrents.info()
    grouped = defaultdict(list)
    for torrent in torrents:
        key = (torrent.name, torrent.total_size)
        grouped[key].append(torrent)
    results = []
    for (name, size), torrent_group in grouped.items():
        all_trackers = set()
        tracker_comment_pairs = set()
        hashes = []
        for t in torrent_group:
            hashes.append(t.hash)
            trackers = client.torrents.trackers(t.hash)
            valid_trackers = [
                tracker.url
                for tracker in trackers
                if not any(x in tracker.url for x in ["[DHT]", "[PeX]", "[LSD]"])
            ]
            for tracker_url in valid_trackers:
                all_trackers.add(tracker_url)
            try:
                properties = client.torrents_properties(t.hash)
                comment = properties.comment or ""
                if comment:  # Only create tracker-comment pairs for non-empty comments
                    for tracker_url in valid_trackers:
                        pair = f"站点tracker：{tracker_url}-->>>注释：{comment}"
                        tracker_comment_pairs.add(pair)
            except Exception as e:
                print(f"警告: 无法获取种子 {name} 的评论: {e}")

        # If ANY of the torrent's trackers match ANY of the required trackers, skip it.
        if any(any(req in url for req in required_trackers) for url in all_trackers):
            continue

        # Otherwise, the torrent is missing all required trackers, so add it to the results.
        results.append(
            {
                "name": name,
                "size": size,
                "trackers": list(all_trackers),
                "hashes": hashes,
                "comment": "\n".join(sorted(tracker_comment_pairs)),  # Merge tracker-comment pairs
            }
        )
    return results

def export_missing_trackers(filename="missing_trackers.csv"):
    result = check_missing_trackers()
    total_size = sum(item["size"] for item in result)
    
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["种子名称", "大小（字节）", "所有 Tracker", "种子注释"])
        for item in result:
            writer.writerow([item["name"], item["size"], ", ".join(item["trackers"]), item["comment"]])
        writer.writerow([])
        writer.writerow(["总计", f"{total_size} 字节", f"({convert_size(total_size)})", ""])
    
    print(f"✅ 导出完成，共 {len(result)} 项，总大小 {convert_size(total_size)} → {filename}")


def delete_missing_trackers():
    result = check_missing_trackers()
    total = 0
    for item in result:
        for h in item["hashes"]:
            try:
                client.torrents_delete(
                    delete_files=delete_files_on_remove, torrent_hashes=h
                )
                print(f"已删除：{item['name']} - {h}")
                total += 1
            except Exception as e:
                print(f"删除失败：{item['name']} - {h}，原因：{e}")
    print(f"✅ 共删除 {total} 个种子")


def delete_specific_torrent(name, size):
    torrents = client.torrents.info()
    deleted = 0
    for torrent in torrents:
        if torrent.name == name and torrent.total_size == size:
            try:
                client.torrents_delete(
                    delete_files=delete_files_on_remove, torrent_hashes=torrent.hash
                )
                print(f"✅ 已删除：{torrent.name} - {torrent.hash}")
                deleted += 1
            except Exception as e:
                print(f"❌ 删除失败：{torrent.name} - {torrent.hash}，原因：{e}")
    if deleted == 0:
        print("⚠️ 未找到匹配的种子")
    else:
        print(f"✅ 共删除 {deleted} 个种子")


def limit_upload_speed_by_tracker():
    torrents = client.torrents_info()
    modified = 0
    skipped = 0
    failed = 0
    for torrent in torrents:
        try:
            trackers = client.torrents_trackers(torrent.hash)
            matched_speed = None
            matched_tracker = None
            current_limit = torrent.up_limit
            needs_update = False
            for tracker in trackers:
                url = tracker.url
                if any(proto in url for proto in ["[DHT]", "[PeX]", "[LSD]"]):
                    continue
                for domain, speed_kb in upload_speed_limits_by_tracker.items():
                    if domain in url:
                        desired_limit = speed_kb * 1024
                        if current_limit != desired_limit:
                            matched_speed = speed_kb
                            matched_tracker = url
                            needs_update = True
                        break
                if matched_speed is not None:
                    break
            if needs_update and matched_speed is not None:
                upload_limit = matched_speed * 1024
                try:
                    was_paused = torrent.state == "pausedUP"
                    if not was_paused:
                        client.torrents_pause(torrent.hash)
                    client.torrents_set_upload_limit(
                        limit=upload_limit, torrent_hashes=torrent.hash
                    )
                    if not was_paused:
                        client.torrents_resume(torrent.hash)
                    print(
                        f"✅ 限速：{torrent.name} → {matched_speed} KB/s（tracker: {matched_tracker}）"
                    )
                    modified += 1
                except Exception as e:
                    print(
                        f"❌ 限速失败：{torrent.name}（{matched_tracker} → {matched_speed} KB/s）→ {str(e)}"
                    )
                    failed += 1
            else:
                reason = "已符合要求" if matched_speed else "未匹配到限速 tracker"
                # print(f"⚠️ 跳过：{torrent.name}（{reason}）")

                skipped += 1
        except Exception as e:
            print(f"❌ 处理失败：{torrent.name} → {str(e)}")
            failed += 1
    print(
        f"\n✅ 完成：共限制 {modified} 个种子上传速度，跳过 {skipped} 个种子，失败 {failed} 个"
    )


def export_tracker_summary(filename="tracker_summary.csv"):
    torrents = client.torrents_info()
    results = []
    total_size = 0
    for torrent in torrents:
        trackers = client.torrents_trackers(torrent.hash)
        valid_trackers = [
            t.url
            for t in trackers
            if not any(proto in t.url for proto in ["[DHT]", "[PeX]", "[LSD]"])
        ]
        matched = [
            trk for trk in valid_trackers if any(req in trk for req in required_summer)
        ]
        if matched:
            created_on = datetime.datetime.fromtimestamp(torrent.added_on).strftime("%Y-%m-%d %H:%M:%S")
            results.append({
                "name": torrent.name,
                "size": torrent.total_size,
                "created_on": created_on,
                "matched_trackers": ", ".join(matched),
            })
            total_size += torrent.total_size
    
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["种子名称", "大小（字节）", "创建时间", "匹配的 Tracker"])
        for item in results:
            writer.writerow([
                item["name"],
                item["size"],
                item["created_on"],
                item["matched_trackers"],
            ])
        # 新增统计行
        writer.writerow([])
        writer.writerow(["总计", f"{total_size} 字节", f"({convert_size(total_size)})", ""])
    
    print(f"✅ 导出完成：{len(results)} 个种子，总大小 {convert_size(total_size)} → {filename}")
    print(f"📦 总大小：{total_size} 字节（{convert_size(total_size)}）")


def export_torrents_by_filter(
    keyword=None, 
    min_size=None, 
    max_size=None, 
    filename="filtered_torrents.csv"
):
    print(f"DEBUG: export_deduplicate = {export_deduplicate}")
    torrents = client.torrents_info()
    results = []
    total_size = 0  # Initialize total_size here
    
    if export_deduplicate:
        grouped = defaultdict(list)
        for torrent in torrents:
            if keyword and keyword.lower() not in torrent.name.lower():
                continue
            if min_size and torrent.total_size < min_size:
                continue
            if max_size and torrent.total_size > max_size:
                continue
            key = (torrent.name, torrent.total_size)
            grouped[key].append(torrent)
        
        for (name, size), torrent_group in grouped.items():
            # 合并所有tracker（去重）
            all_trackers = set()
            created_on = None
            for t in torrent_group:
                trackers = client.torrents_trackers(t.hash)
                for tracker in trackers:
                    url = tracker.url
                    if not any(x in url for x in ["[DHT]", "[PeX]", "[LSD]"]):
                        all_trackers.add(url)
                # 取最早的创建时间
                added_on = datetime.datetime.fromtimestamp(t.added_on)
                if created_on is None or added_on < created_on:
                    created_on = added_on
            
            results.append({
                "name": name,
                "size": size,
                "created_on": created_on.strftime("%Y-%m-%d %H:%M:%S"),
                "trackers": ", ".join(all_trackers),
            })
            total_size += size  # Add size after deduplication
    else:
        for torrent in torrents:
            if keyword and keyword.lower() not in torrent.name.lower():
                continue
            if min_size and torrent.total_size < min_size:
                continue
            if max_size and torrent.total_size > max_size:
                continue
                
            created_on = datetime.datetime.fromtimestamp(torrent.added_on).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            trackers = client.torrents_trackers(torrent.hash)
            all_trackers = [
                t.url
                for t in trackers
                if not any(proto in t.url for proto in ["[DHT]", "[PeX]", "[LSD]"])
            ]
            results.append({
                "name": torrent.name,
                "size": torrent.total_size,
                "created_on": created_on,
                "trackers": ", ".join(all_trackers),
            })
            total_size += torrent.total_size  # Add size for non-deduplicated case

    # 写入CSV文件
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["种子名称", "大小（字节）", "创建时间", "所有 Tracker"])
        for item in results:
            writer.writerow(
                [item["name"], item["size"], item["created_on"], item["trackers"]]
            )
        # 新增一行统计信息
        writer.writerow([])  # 空行分隔
        writer.writerow(["总计", f"{total_size} 字节", f"({convert_size(total_size)})", ""])
    
    print(f"✅ 导出完成，共 {len(results)} 项，总大小 {convert_size(total_size)} → {filename}")
    

# ========== 主函数，根据命令行参数执行 ==========

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "❗用法:\n  python qbt.py export\n  python qbt.py del\n  python qbt.py del <种子名称> <大小>\n  python qbt.py limit\n  python qbt.py total\n  python qbt.py search <关键词> [最小大小 单位字节] [最大大小 单位字节]"
        )
        sys.exit(1)
    cmd = sys.argv[1].lower()

    if cmd == "export":
        export_missing_trackers()
    elif cmd == "del":
        if len(sys.argv) == 2:
            delete_missing_trackers()
        elif len(sys.argv) == 4:
            name = sys.argv[2]
            try:
                size = int(sys.argv[3])
                delete_specific_torrent(name, size)
            except ValueError:
                print("❌ 第三个参数必须是整数大小（字节）")
        else:
            print("❗用法: python qbt.py del <种子名称> <大小（字节）>")
    elif cmd == "limit":
        limit_upload_speed_by_tracker()
    elif cmd == "total":
        export_tracker_summary()
    elif cmd == "search":
        keyword = sys.argv[2] if len(sys.argv) > 2 else None
        min_size = int(sys.argv[3]) if len(sys.argv) > 3 else None
        max_size = int(sys.argv[4]) if len(sys.argv) > 4 else None
        export_torrents_by_filter(keyword, min_size, max_size)
    else:
        print(f"❗未知指令: {cmd}，请用 export / del / limit / total / search")
