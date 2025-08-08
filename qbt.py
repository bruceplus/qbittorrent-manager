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
required_summer = config["required_summer"]
upload_speed_limits_by_tracker = config["upload_speed_limits_by_tracker"]
export_deduplicate = config.get("export_options", {}).get("deduplicate", True)
# 检查策略配置
check_strategies = config.get("check_strategies", {})
# 读取启用的检查策略列表
active_strategies = config.get("active_strategies", [])  

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


# 检查策略基类
class CheckStrategy:
    def check(self, torrent_group, client):
        """
        检查一组种子是否符合策略
        :param torrent_group: 按 (name, size) 分组的种子列表
        :param client: qBittorrent 客户端
        :return: dict - 种子信息（如果需要处理），否则返回 None
        """
        raise NotImplementedError("子类必须实现 check 方法")

# 策略：检查缺失特定Tracker
class MissingTrackersStrategy(CheckStrategy):
    def __init__(self, required_trackers):
        self.required_trackers = required_trackers

    def check(self, torrent_group, client):
        all_trackers = set()
        tracker_comment_pairs = set()
        hashes = [t.hash for t in torrent_group]
        name, size = torrent_group[0].name, torrent_group[0].total_size

        for t in torrent_group:
            trackers = client.torrents_trackers(t.hash)
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
                if comment:
                    for tracker_url in valid_trackers:
                        pair = f"站点tracker：{tracker_url}-->>>注释：{comment}"
                        tracker_comment_pairs.add(pair)
            except Exception as e:
                print(f"警告: 无法获取种子 {name} 的评论: {e}")

        # 如果没有任何必需的Tracker匹配，则需要处理
        if not any(any(req in url for req in self.required_trackers) for url in all_trackers):
            return {
                "name": name,
                "size": size,
                "trackers": list(all_trackers),
                "hashes": hashes,
                "comment": "\n".join(sorted(tracker_comment_pairs))
            }
        return None
        
# 策略：检查种子名称是否包含官组名称
class OfficialGroupStrategy(CheckStrategy):
    def __init__(self, group_names):
        self.group_names = [name.lower() for name in group_names]  # 转换为小写以不区分大小写

    def check(self, torrent_group, client):
        name, size = torrent_group[0].name, torrent_group[0].total_size
        hashes = [t.hash for t in torrent_group]
        # 检查种子名称是否包含任一官组名称（不区分大小写）
        if not any(group_name in name.lower() for group_name in self.group_names):
            all_trackers = set()
            tracker_comment_pairs = set()
            for t in torrent_group:
                trackers = client.torrents_trackers(t.hash)
                valid_trackers = [
                    tracker.url
                    for tracker in trackers
                    if not any(x in tracker.url for x in ["[DHT]", "[PeX]", "[LSD]"])
                ]
                all_trackers.update(valid_trackers)
                try:
                    properties = client.torrents_properties(t.hash)
                    comment = properties.comment or ""
                    if comment:
                        for tracker_url in valid_trackers:
                            pair = f"站点tracker：{tracker_url}-->>>注释：{comment}"
                            tracker_comment_pairs.add(pair)
                except Exception as e:
                    print(f"警告: 无法获取种子 {name} 的评论: {e}")
            return {
                "name": name,
                "size": size,
                "trackers": list(all_trackers),
                "hashes": hashes,
                "comment": f"Does not belong to official group: {', '.join(self.group_names)}"
            }
        return None
        
# 策略：根据tracker标签过滤
class TrackerTagFilterStrategy(CheckStrategy):
    def __init__(self, forbidden_tags):
        self.forbidden_tags = [tag.lower() for tag in forbidden_tags]

    def check(self, torrent_group, client):
        name, size = torrent_group[0].name, torrent_group[0].total_size
        hashes = [t.hash for t in torrent_group]
        all_trackers = set()
        tracker_comment_pairs = set()
        has_forbidden_tag = False

        for t in torrent_group:
            trackers = client.torrents_trackers(t.hash)
            valid_trackers = [
                tracker.url
                for tracker in trackers
                if not any(x in tracker.url for x in ["[DHT]", "[PeX]", "[LSD]"])
            ]
            all_trackers.update(valid_trackers)
            try:
                properties = client.torrents_properties(t.hash)
                comment = properties.comment or ""
                if comment:
                    for tracker_url in valid_trackers:
                        pair = f"站点tracker：{tracker_url}-->>>注释：{comment}"
                        tracker_comment_pairs.add(pair)
                # 检查标签
                tags = t.tags.split(",") if t.tags else []
                tags = [tag.strip().lower() for tag in tags]
                if any(tag in self.forbidden_tags for tag in tags):
                    has_forbidden_tag = True
            except Exception as e:
                print(f"警告: 无法获取种子 {name} 的属性: {e}")

        # 反转逻辑：如果没有禁止标签，则需要处理（返回种子信息）
        if not has_forbidden_tag:
            return {
                "name": name,
                "size": size,
                "trackers": list(all_trackers),
                "hashes": hashes,
                "comment": f"Does not contain protected tags: {', '.join(self.forbidden_tags)}"
            }
        return None

# 策略工厂：根据配置动态创建策略
class StrategyFactory:
    @staticmethod
    def create_strategy(strategy_name, config):
        if strategy_name == "missing_trackers":
            return MissingTrackersStrategy(config.get("required_trackers", []))
        elif strategy_name == "official_group":
            groups = config.get("groups", {})
            selected_group = config.get("selected_group", "")
            if selected_group not in groups:
                raise ValueError(f"未找到指定的官组: {selected_group}")
            return OfficialGroupStrategy(groups[selected_group])
        elif strategy_name == "tracker_tag_filter":
            return TrackerTagFilterStrategy(config.get("forbidden_tags", []))
        else:
            raise ValueError(f"未知策略: {strategy_name}")

def check_missing_trackers():
    # 创建所有启用的策略实例
    strategies = []
    for strategy_name in active_strategies:
        strategy_config = check_strategies.get(strategy_name, {})
        try:
            strategy = StrategyFactory.create_strategy(strategy_name, strategy_config)
            strategies.append(strategy)
        except ValueError as e:
            print(f"⚠️ 跳过无效策略 {strategy_name}: {e}")
            continue
    
    if not strategies:
        print("❌ 无有效策略配置")
        return []
    
    # 获取所有种子并按 (name, size) 分组
    torrents = client.torrents_info()
    grouped = defaultdict(list)
    for torrent in torrents:
        key = (torrent.name, torrent.total_size)
        grouped[key].append(torrent)
    
    # 初始化待处理的种子组
    current_groups = grouped
    
    # 按策略顺序逐层过滤
    for idx, strategy in enumerate(strategies, 1):
        next_groups = defaultdict(list)
        results = []
        seen_hashes = set()  # 用于去重
        
        for key, torrent_group in current_groups.items():
            result = strategy.check(torrent_group, client)
            if result and not any(h in seen_hashes for h in result["hashes"]):
                results.append(result)
                seen_hashes.update(result["hashes"])
                next_groups[key] = torrent_group  # 保留满足条件的种子组
        
        print(f"✅ 策略 {idx}: {type(strategy).__name__} 过滤后剩余 {len(next_groups)} 个种子组")
        current_groups = next_groups  # 更新为下一轮的输入
    
    # 返回最终结果
    return results

# 导出
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

# 删除
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
            print("❗用法: python qbt.py del 或 python qbt.py del <种子名称> <大小（字节）>")
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