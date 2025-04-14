# qBittorrent 管理脚本

这是一个用于管理 qBittorrent 客户端的 Python 脚本，支持导出、删除、限速和统计种子信息。脚本通过配置文件灵活设置 tracker 和连接信息，适合批量管理种子任务。

## 功能

- **导出缺失 tracker 的种子**：将不包含指定 tracker 的种子信息导出为 CSV 文件。
- **删除缺失 tracker 的种子**：删除不包含指定 tracker 的种子，可选择是否同时删除本地文件。
- **删除特定种子**：根据种子名称和大小删除指定种子。
- **按 tracker 限速**：为包含特定 tracker 的种子设置上传速度限制。
- **统计 tracker 信息**：统计包含指定 tracker 的种子信息并导出为 CSV 文件。
- **按条件搜索种子**：根据关键词、大小范围搜索种子并导出结果。

## 环境要求

- Python 3.6 或以上
- qBittorrent Web UI 已启用并可访问

## 安装

1. 克隆或下载本仓库到本地：

   ```bash
   git clone https://github.com/your-username/qbittorrent-manager.git
   cd qbittorrent-manager
   ```

2. 安装依赖（一条命令）：

   ```bash
   pip install qbittorrent-api pyyaml
   ```

3. 创建配置文件：

   - 在项目config目录下已经有了demo.ymal，复制粘贴一份，重命名为home.ymal，如果有多份环境配置，在根目录下config.yml中指定环境

     ```yaml
     # 当前使用的环境名称，对应 config/ 目录下的 xxx.yaml 文件
     use_env: "home"
     ```

   -  `demo.yaml`内容示例：

     ```yaml
     # ==== qBittorrent 客户端连接信息 ====
     qbittorrent:
       host: "192.168.1.28"     # 客户端 IP 或域名
       port: 8005               # Web UI 端口
       username: "admin"        # 登录用户名
       password: "your_password_here"  # 登录密码
     
     # ==== 删除种子时是否同时删除本地文件 ====
     delete_files_on_remove: true
     
     # ==== tracker 列表，当种子没有该tracker时，会将该种子导出或删除 ====
     required_trackers:
       - "tracker.your"
     
     # ==== 需要统计数据的 tracker（用于 total 命令） ====
     required_summer:
       - "tracker.m-your.cc"
     
     # ==== 根据 tracker 域名限速（单位：KB/s） ====
     upload_speed_limits_by_tracker:
       "pt.your": 600
       "ptl.your": 600
     ```

   - 根据你的 qBittorrent 设置修改 `host`、`port`、`username` 和 `password`。

   - 根据需要调整 `required_trackers`、`required_summer` 和 `upload_speed_limits_by_tracker`。

## 使用方法

在项目目录下运行脚本，命令格式为：

```bash
python qbt.py <命令> [参数]
```

### 可用功能命令

1. **导出缺失 tracker 的种子**：

   ```bash
   python qbt.py export
   ```

   - 功能：将不包含 `required_trackers` 中任一 tracker 的种子导出为 `missing_trackers.csv`。【说人话】填写想被辅种的站点tracker，支持多个。导出来的数据可以查看哪些是未被辅种到的站点数据
   - 输出：CSV 文件包含种子名称、大小和所有 tracker。

2. **删除缺失 tracker 的种子**：

   ```bash
   python qbt.py del
   ```

   - 功能：删除不包含 `required_trackers` 中任一 tracker 的种子。【说人话】在功能一基础上增加了删除。删除之前先导出来和qb对比下是否有问题。required_trackers是两个方法通用的
   - 注意：根据 `delete_files_on_remove` 设置决定是否删除本地文件。

3. **删除特定种子**：

   ```bash
   python qbt.py del "<种子名称>" <大小>
   ```

   - 功能：删除名称和大小完全匹配的种子。

   - 示例：

     ```bash
     python qbt.py del "Example.Torrent.Name" 1073741824
     ```

   - 注意：大小单位为字节。

4. **按 tracker 限速**：

   ```bash
   python qbt.py limit
   ```

   - 功能：根据 `upload_speed_limits_by_tracker` 设置，为匹配 tracker 的种子限制上传速度（单位：KB/s）。
   - 对各站点限速。这里叠个甲，一定的限速是为了细水长流，要是运营商不管，也不会有这个功能。有的时候总会有新的辅种，新订阅好的种子，每次手动太麻烦了，so~

5. **统计 tracker 信息**：

   ```bash
   python qbt.py total
   ```

   - 功能：统计包含 `required_summer` 中 tracker 的种子，导出为 `tracker_summary.csv`。
   - 输出：CSV 文件包含种子名称、大小、创建时间和匹配的 tracker。

6. **按条件搜索种子**：

   ```bash
   python qbt.py search <关键词> [最小大小] [最大大小]
   ```

   - 功能：根据关键词（可选）、最小大小（可选，单位字节）、最大大小（可选，单位字节）搜索种子，导出为 `filtered_torrents.csv`。

   - 示例：

     ```bash
     导出所有名称中包含 “movie” 的种子
     python qbt.py search movie
     
     导出大小大于 1GB 的电影种子（单位是字节）
     python ms.py search movie 1073741824
     
     导出大小介于 500MB 到 5GB 的电影种子
     python ms.py search movie 524288000 5368709120
     ```

   - 输出：CSV 文件包含种子名称、大小、创建时间和所有 tracker。

### 错误排查

- **找不到 `config.yml` 或 `home.yaml`**：
  - 确保文件存在于正确路径（`config.yml` 在根目录，`home.yaml` 在 `config/` 文件夹）。
  - 检查文件名是否正确（区分大小写）。
- **编码错误**：
  - 确保 `config.yml` 和 `home.yaml` 使用 UTF-8 编码保存。
  - 在文本编辑器中检查并转为 UTF-8（VS Code、Notepad++ 等支持）。
- **登录失败**：
  - 确认 `home.yaml` 中的 `host`、`port`、`username` 和 `password` 是否正确。
  - 确保 qBittorrent Web UI 已启用并可访问。

## 注意事项

- 运行 `del` 命令时谨慎操作，建议先用 `export` 命令检查要删除的种子。
- 修改 `upload_speed_limits_by_tracker` 时，确保速度值合理，避免影响上传效率。
- 配置文件中的 tracker 域名需与 qBittorrent 中的 tracker URL 匹配（部分或全匹配）。
- 脚本会自动跳过 DHT、PeX 和 LSD 等协议的 tracker。
