---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: aae5b95be9c110458ce4d08d357cc7d3_0d335106b57311f188f9525400248c00
    ReservedCode1: IxkrdIVLI/6yZnmNgo0XgNXlTZDp0HF/OLv7dJQQSIli9uoNEr1D57oQRwHqZbjC9A2hsj0v1qCk/vk4JChgDUUaIJ2JLTM3fGn/l/yrjEjHA6P9ByaltEOQT7iEiDgHoB4iWlnIwEQcXJ5svX1bUb5eF8y5wd8W4D05tG8K/4hCpHoJ6FIPBe9nmqQ=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: aae5b95be9c110458ce4d08d357cc7d3_0d335106b57311f188f9525400248c00
    ReservedCode2: IxkrdIVLI/6yZnmNgo0XgNXlTZDp0HF/OLv7dJQQSIli9uoNEr1D57oQRwHqZbjC9A2hsj0v1qCk/vk4JChgDUUaIJ2JLTM3fGn/l/yrjEjHA6P9ByaltEOQT7iEiDgHoB4iWlnIwEQcXJ5svX1bUb5eF8y5wd8W4D05tG8K/4hCpHoJ6FIPBe9nmqQ=
---

# Apple 商店库存监控工具 — 设计文档

- 日期：2026-09-21
- 状态：已批准（用户已确认需求与推送方案）

## 1. 背景与目标

用户需要实时监控 Apple 官方商店（中国大陆 + 中国香港）的设备库存情况，当关注的型号有货时及时收到提醒，以便第一时间下单购买。

### 核心目标

1. 支持监控中国大陆（apple.com.cn）与中国香港（apple.com/hk）两个地区的直营店库存
2. 允许用户自定义监控的设备款式型号（Part Number，如 `MQ0X3CH/A`）与指定店铺
3. 定时轮询，检测到"无货 → 有货"状态变化时推送通知
4. 提醒方式：macOS 桌面通知（默认）→ 通过 iCloud 通知镜像同步到 iPhone；可选 Bark 手机推送

### 非目标（YAGNI）

- 不做下单/抢购自动化
- 不做价格监控、历史价格曲线
- 不做微信小程序推送（技术不可行，见 §6）
- 本轮不做 GUI，仅做 CLI（GUI 列入后续路线 §8）

## 2. 需求

### 用户故事

- 作为用户，我可以添加要监控的型号（如 iPhone 16 Pro Max 256GB 沙漠色钛金属，Part Number `MQ0X3CH/A`），以便只关注我想要的设备
- 作为用户，我可以选择监控中国大陆、中国香港或两地同时监控
- 作为用户，我可以限定只监控某个或某些店铺，避免被无关店铺打扰
- 作为用户，我可以设置轮询间隔，平衡实时性与请求频率
- 作为用户，当关注型号在指定店铺从无货变为有货时，我会收到桌面通知（同步到手机锁屏）
- 作为用户，我可以选择启用 Bark 推送，在手机上独立收到通知
- 作为用户，同一型号同一店铺的"有货"提醒只推送一次，避免重复轰炸

## 3. 技术方案

### 3.1 技术选型

- **语言**：Python 3.9+（标准库为主，跨平台，后续 GUI 扩展方便）
- **依赖**：`requests`（HTTP）；桌面通知用 macOS 原生 `osascript`（零依赖）；可选 `bark` 推送走 HTTPS POST
- **数据源**：Apple 官网公开库存接口（无鉴权，直接 GET）

### 3.2 Apple 库存接口（2026-08 后新版）

> 旧接口 `/shop/fulfillment-messages` 自 2026-08 起恒定返回 HTTP 541 已失效，新版改用 `pickup-message` 接口（无鉴权，GET 即可）。

```
中国大陆: https://www.apple.com.cn/shop/retail/pickup-message?pl=true&mts.0=regular&parts.0={PART_NUMBER}&parts.1={PART_NUMBER2}&store={STORE_ID}
中国香港: https://www.apple.com/hk/shop/retail/pickup-message?pl=true&mts.0=regular&parts.0={PART_NUMBER}&store={STORE_ID}
```

返回 JSON 结构（关键字段，与旧版不同）：

```json
{
  "body": {
    "stores": [
      {
        "storeNumber": "R428",
        "storeName": "ifc mall",
        "partsAvailability": {
          "MQ0X3CH/A": { "pickupDisplay": "available" }
        }
      }
    ]
  }
}
```

- `pickupDisplay` 取值：`available`（有货）/ `unavailable`（无货）/ `ineligible`（不可自提）
- **必须携带 `store` 参数**：不带 store 时仅返回 eligibility 信息、无具体店铺库存；`partsAvailability` 缺失某型号视为该店未上架（not_listed = 无货）
- 支持一次请求携带多个型号（`parts.0`、`parts.1`…），减少请求数
- 店铺列表从零售店页面 `/retail/storelist/` 内嵌的 `storeList` JSON 解析（按 locale 分组，zh_CN / zh_HK），带 24h 本地缓存

### 3.3 架构与组件

```
apple-stock-monitor/
├── config.json            # 用户配置（监控列表、轮询间隔、推送开关）
├── monitor.py             # CLI 入口 + 主循环调度
├── fetcher.py             # 调用 Apple fulfillment API 拉取库存
├── parser.py              # 解析库存状态（有货/无货/异常）
├── notifier.py            # 通知：桌面通知 + Bark 推送
├── state.py               # 状态持久化（去重提醒：记录上次是否有货）
├── models.py              # 数据模型（Region/Model/WatchItem/Store）
└── tests/                 # 单元测试
```

各组件职责单一、接口清晰：

| 组件 | 职责 | 依赖 |
|------|------|------|
| `fetcher.py` | 构造 URL、发起请求、返回原始 JSON | requests |
| `parser.py` | 从 JSON 提取店铺+型号的库存状态 | 无 |
| `state.py` | 读写状态文件（JSON），记录每个监控项上次状态 | 无 |
| `notifier.py` | 桌面通知（osascript）、Bark 推送 | 无 |
| `monitor.py` | CLI 解析、轮询循环、状态比对、触发通知 | 以上全部 |

### 3.4 数据流

```
定时触发（默认 10 分钟）
  → fetcher 拉取各地区各型号库存 JSON
  → parser 提取关注店铺的库存状态
  → state 对比上次状态（无货→有货 才触发）
  → notifier 桌面通知 + 可选 Bark
  → 更新 state
```

### 3.5 配置格式（config.json）

```json
{
  "poll_interval_minutes": 10,
  "bark": {
    "enabled": false,
    "key": ""
  },
  "watchlist": [
    {
      "region": "cn",
      "model": "MQ0X3CH/A",
      "label": "iPhone 16 Pro Max 256G 沙漠色",
      "stores": ["R428"]
    }
  ]
}
```

- `region`：`cn`（中国大陆）/ `hk`（中国香港）
- `stores`：留空数组表示关注该地区全部店铺
- `label`：可选，便于人读（用于通知文案）

## 4. CLI 设计

```
python monitor.py list-stores --region cn        # 列出该地区全部直营店及 ID
python monitor.py add --region cn --model MQ0X3CH/A [--label "iPhone 16 Pro Max"] [--store R428]...
python monitor.py remove --region cn --model MQ0X3CH/A
python monitor.py list                          # 查看当前监控列表
python monitor.py run                           # 启动监控（前台常驻）
```

- `add` 未指定 `--store` 时监控该地区全部店铺
- `add` 时自动校验型号格式（Part Number 形如 `XXXXX/A`）并可试查一次确认型号有效
- `run` 启动后输出心跳日志，`Ctrl+C` 优雅退出

## 5. 通知设计

### 5.1 默认推送链（零 Key）

1. `notifier.py` 调用 macOS `osascript` 弹出系统通知（标题含地区+型号+店铺）
2. Mac 与 iPhone 同 Apple ID 时，iPhone「设置 → 通知 → 通知镜像」开启后，该通知自动同步到 iPhone 锁屏——**零配置、零 Key**

### 5.2 可选 Bark 推送

- `config.json` 中 `bark.enabled=true` 并填入 App 生成的 key
- 通过 `https://api.day.app/{key}/{标题}/{内容}` POST 推送，手机 Bark App 即时收到

### 5.3 去重提醒

- `state.json` 持久化每个监控项（region+model+store）的上次状态
- 仅当状态从 `unavailable → available` 时推送；持续有货不重复推
- 从有货变回无货后自动重置，下次有货会再次提醒

## 6. 已否决方案

| 方案 | 否决原因 |
|------|---------|
| 微信小程序推送 | 小程序无法后台运行、无法主动推送；订阅消息一次性授权体验差，长期订阅仅限政务/民生类目；需服务器部署，成本高 |
| 仅 Server 酱/PushPlus | 需要注册账号拿 Key，且依赖微信服务号模板消息，体验劣于 Bark |
| Node.js / Go 实现 | 开发迭代慢、后续 GUI 扩展成本高于 Python |

## 7. 容错与测试

### 容错

- 网络失败：单次失败跳过本轮，指数退避重试（30s → 1min → 2min），连续失败写日志不中断
- Apple 接口变动：JSON 结构解析失败时输出可读错误并跳过该型号，不崩溃
- 通知失败：Bark 推送失败不影响桌面通知；桌面通知失败记录日志

### 测试

- `parser`：用固定 JSON fixture 测试 available/unavailable/异常结构
- `state`：状态转换（无货→有货→无货→有货）触发逻辑
- `notifier`：mock osascript/Bark HTTP，验证调用
- 集成测试：mock 接口响应跑一轮完整轮询

## 8. 后续路线（本轮不做）

1. GUI 界面（型号选择器、库存列表、开关推送）——待 CLI 稳定后迭代
2. 支持更多地区（美国、日本等，接口结构一致，扩展成本低）
3. ~~多型号批量查询合并~~（已实现：`run` 按（地区, 店铺）分组，一次请求携带多个 `parts.N` 型号）

## 9. 交付标准

- 命令 `python monitor.py run` 可稳定运行，按配置轮询
- `add/remove/list/list-stores` 命令可用
- 模拟有货时桌面通知正常弹出（可在本机实际验证）
- README 说明安装、配置、使用方式
*（内容由AI生成，仅供参考）*
