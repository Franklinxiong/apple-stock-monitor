# Apple 商店库存监控

实时监控 Apple 官网（中国大陆 + 中国香港）直营店库存，关注型号有货时通过 macOS 桌面通知提醒（可同步到 iPhone），可选 Bark 手机推送。

## 功能

- 监控中国大陆（apple.com.cn）与中国香港（apple.com/hk）直营店库存
- 自定义监控型号（支持型号名/店名模糊搜索，如 "iPhone 17 512GB 黑色"、"三里屯"）与限定店铺
- 默认每 10 分钟轮询（可配置）
- 无货 → 有货时推送提醒
- 桌面通知默认开启；Bark （可选）
- 桌面 GUI：型号搜索、库存看板、到货推送开关、自动轮询

## 安装

```bash
cd apple-stock-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

首次运行 `run` 时，macOS 会弹出"终端想要发送通知"授权，请允许（这样才能弹桌面通知）。

## 使用

### 桌面 GUI（推荐）

```bash
python gui.py
```

GUI 提供深色科技感 Dashboard：

- 顶部「STOCK MONITOR」标题 + 中国区/香港区切换 + 运行状态灯
- 当前监控型号卡片，点「更换」弹出搜索框（支持中文名/英文名/Part Number 模糊搜索，点击候选即选中）
- 有货 / 无货 / 即将到货统计条；门店库存列表按 有货 → 即将到货 → 无货 排序
- 底部「到货推送」开关（状态持久化到 `config.json` 的 `gui.notify_enabled`）、Bark Key 配置、手动刷新、上次刷新时间
- 后台线程查询 + 定时自动轮询（间隔取 `config.json` 的 `poll_interval_minutes`）；网络失败显示红色横幅并保留上次数据

### 打包 APP（AppleStockMonitor.app）

已内置 py2app 打包配置，可一键生成 macOS 原生 .app：

```bash
pip install py2app
python setup.py py2app
```

产物位于 `dist/AppleStockMonitor.app`，双击即可运行（也可直接 `python gui.py` 以源码方式运行）。

打包后的 APP 将只读数据（`models_catalog.json`、`config.json` 模板等）打包进 `Contents/Resources`，可写数据统一存放在 `~/Library/Application Support/AppleStockMonitor/`：`config.json` 副本（首次启动从模板复制）与 `stores_cache_*.json` 缓存写在此处，源码目录的 `config.json` 仅作为模板，不会被修改。

### 命令行 CLI

```bash
# 1. 查看某地区直营店列表（拿店铺 ID）
python monitor.py list-stores --region cn
python monitor.py list-stores --region hk

# 2. 添加监控型号（型号名/店名模糊搜索，不知道代码也能用）
python monitor.py add --region cn --name "iPhone 17 512GB 黑色"
python monitor.py add --region hk --name "iPad Pro 13英寸 1TB" --store "ifc"
python monitor.py add --region cn --name "macbook air 13 午夜" --store "三里屯" "王府井"

# 3. 查看监控列表
python monitor.py list

# 4. 启动监控（前台常驻，Ctrl+C 退出）
python monitor.py run --verbose
```

> 提示：`--name` 支持模糊搜索，多个候选时会让你选编号；不带 `--store` 表示监控该地区全部店铺，`--store` 可传店名关键词或店铺 ID（R 编号），可多次传。`remove` 同样支持 `--name`。若速查表里没有你要的型号（如新发布机型未更新），可回退旧用法 `--model <Part Number>` 手动添加。

## 手机推送（可选）

默认桌面通知会在 Mac 与 iPhone 登录同一 Apple ID、且 iPhone「设置 → 通知 → 通知镜像」开启时同步到手机锁屏，零配置。

如需独立手机推送：iPhone 安装 Bark App，复制其中的 key，编辑 `config.json`：

```json
"bark": { "enabled": true, "key": "你的BarkKey" }
```

## 配置说明（config.json）

| 字段 | 说明 |
|------|------|
| `poll_interval_minutes` | 轮询间隔（分钟），默认 10 |
| `bark.enabled` / `bark.key` | Bark 推送开关与 Key |
| `gui.notify_enabled` | GUI 到货推送开关（默认 true，仅 GUI 使用） |
| `watchlist[]` | 监控列表：`region`(cn/hk)、`model`(Part Number)、`label`(备注)、`stores`(店铺ID数组，空=全部) |

## 状态文件

`state.json` 记录每个监控项的上次库存状态，用于去重提醒。可随时删除，不影响使用（下次会按"无货"基线重新判断）。

## 测试

```bash
pytest tests/ -v
```

## 路线图

- [x] CLI 稳定运行（当前）
- [x] GUI 界面（型号选择器、库存列表、推送开关）
- [ ] 更多地区（美国、日本等）
- [x] 多型号合并请求（同一店铺的多个监控型号合并为一次请求，`parts.N` 参数）

## 免责声明

本工具仅调用 Apple 官网公开接口做库存查询，不提供下单/抢购功能；请勿高频请求，合理设置轮询间隔。

## AI 生成声明

本项目部分代码与文档由 AI 辅助生成，仅供学习与个人使用。
