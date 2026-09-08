# MaaYuan v5 × YuanStar Phase B1a
## 真实 MuMu Controller 截图探针 + 可配置单次滑动/视觉比较骨架

## 当前环境

```text
MaaYuan 源码：
D:\Users\Yan\Projects\MaaYuan-v5-dev

MaaYuan v5 runtime：
D:\Users\Yan\Projects\MaaYuan-v5-runtime

MuMu：
已成功被 MaaYuan v5 runtime 连接
```

用户可以手动把游戏停在：

```text
星石背包 → 主星 → 列表顶部
```

前置 A1 已完成：MaaYuan 未来只提供图片级 overlap，YuanStar 仍走现有 OCR/reconcile。

---

# 0. 本轮目标

本轮只实现 B1a 调试探针。

第一次真实 smoke 只做：

```text
用户手动进入 主星列表顶部
→ MaaYuan 开发调试任务
→ controller 截一张原始截图
→ 保存 PNG + metadata
→ 明确真实 width / height / channels
```

同时搭一个可配置、但第一次不运行的 `pair_probe` 骨架：

```text
before screenshot
→ 显式参数指定 1 次固定 swipe
→ settle
→ after screenshot
→ 只比较 scroll ROI
→ 输出 moved / overlap / no_move 的诊断指标
```

不要根据用户手工截图约 900×1600 或 README 的 1280×720 猜生产坐标。

真正参数以后续 `controller.post_screencap()` 返回的图像尺寸为准。

---

# 1. Git

进入：

```powershell
Set-Location D:\Users\Yan\Projects\MaaYuan-v5-dev
```

先：

```powershell
git status --short --branch
git branch --show-current
git log -1 --oneline
git remote -v
git submodule status --recursive
```

要求：

- 当前来自 `v5`
- `assets/MaaCommonAssets` 已初始化
- 如果 clean，从 `v5` 创建本地分支：

```text
feat/yuanstar-capture-probe
```

- 本轮不要 push
- 暂不 fork
- 不 pull / merge / reset / clean / stash
- 有未知用户改动先停

---

# 2. 先审查

至少看：

```text
agent/custom/action/paged_item_recognition.py
agent/custom/action/__init__.py
agent/main.py
assets/interface.json
assets/resource/pipeline/**
install4release.py
```

确认：

1. screenshot / swipe / wait 的现有调用范式；
2. `PagedItemRecognition` 里的 debug image/json 输出和 OpenCV/NumPy helper；
3. custom action 注册方式；
4. 最小开发调试 task 怎样出现在 MFAAvalonia GUI；
5. dev source 与 runtime 的 `agent/`、`resource/`、`interface.json` 对应关系。

不要复制整份 `PagedItemRecognition`。

---

# 3. 新增 `StarBackpackCaptureProbe`

建议：

```text
agent/custom/action/star_backpack_capture_probe.py
```

按项目现有机制注册。

支持：

```json
{
  "mode": "capture_only",
  "debug_dir": "debug/star-backpack-probe"
}
```

以及未来：

```json
{
  "mode": "pair_probe",
  "debug_dir": "debug/star-backpack-probe",
  "compare_roi": [0, 0, 0, 0],
  "swipe": {
    "start": [0, 0],
    "end": [0, 0],
    "duration_ms": 400
  },
  "settle_ms": 700,
  "compare": {
    "min_overlap_ratio": 0.20,
    "max_overlap_ratio": 0.90
  }
}
```

`pair_probe` 的 ROI 和 swipe 坐标必须显式传入；缺失就报错。

不要猜坐标。

---

# 4. `capture_only`

沿项目现有方式调用真实 controller screenshot，例如：

```python
context.tasker.controller.post_screencap().wait().get()
```

以实际 API 为准。

保存：

```text
<debug_dir>/<run_id>/
  capture.png
  metadata.json
```

metadata 至少：

```json
{
  "mode": "capture_only",
  "width": 0,
  "height": 0,
  "channels": 0,
  "dtype": "...",
  "created_at": "...",
  "file": "capture.png"
}
```

logger 输出真实尺寸。

不要 OCR。
不要 swipe。
不要分析星石。

---

# 5. `pair_probe` 骨架

本轮可以实现，但第一次 smoke 不运行。

流程：

```text
capture before
→ save before.png
→ exact one configured swipe
→ wait settle_ms
→ capture after
→ save after.png
→ crop compare_roi
→ pure visual compare
→ metrics.json
```

## 视觉方法

只做图片级页面关系，不识别星石。

建议：

1. ROI 灰度化；
2. 可轻量 resize/blur/normalize；
3. 计算 same-position similarity，用于 no_move；
4. 扫描合理 vertical overlap；
5. 比较 before 底部 strip 与 after 顶部 strip；
6. 返回 best correlation / overlap / shift。

输出类似：

```json
{
  "same_position_score": 0.0,
  "best_overlap_score": 0.0,
  "best_overlap_px": null,
  "best_shift_px": null,
  "classification": "diagnostic_only"
}
```

本轮不要锁生产阈值。

不要调用任何 OCR、`recognize_item_grid`、星石名称识别。

---

# 6. 未来业务语义

```text
no_move
→ swipe 后页面没继续移动
→ 已到底
→ after 只用于确认，不作为新业务截图

overlap
→ before/after 有高可信页面重合
→ CaptureBatch 只记录 image pair overlap

moved
→ 正常新页面
```

不要输出具体重复行/具体星石/名称/等级。

---

# 7. Debug 输出

pair probe：

```text
<debug_dir>/<run_id>/
  before.png
  after.png
  before-roi.png
  after-roi.png
  metrics.json
```

可选一个简单 overlap 可视化，但不要做复杂 UI。

---

# 8. GUI 最小开发入口

用户使用：

```text
D:\Users\Yan\Projects\MaaYuan-v5-runtime\MaaYuan.exe
```

优先在现有 interface/pipeline 体系中增加一个明显的临时开发任务：

```text
开发调试｜星石背包截图探针
```

默认：

```text
mode = capture_only
```

任务说明：

```text
请先手动进入「星石背包 → 主星 → 顶部」，再执行本任务。
```

不要自动 swipe。

如果 GUI interface 不适合低风险加入临时 task，就报告项目原生最短调试调用方式，不要硬改。

---

# 9. Dev → Runtime 本地同步

不要整体覆盖 runtime。

不要碰：

```text
config
用户配置
日志
MaaYuan.exe
MFAAvalonia runtime
python runtime
```

创建本地开发同步脚本，例如：

```text
tools/sync_yuanstar_probe_runtime.ps1
```

接受：

```powershell
-RuntimePath "D:\Users\Yan\Projects\MaaYuan-v5-runtime"
```

只同步本轮需要的：

- 新 custom action
- `agent/custom/action/__init__.py`（如改）
- 新/改 pipeline
- 必要的 interface task

同步前对目标文件做 targeted backup。

如果需要处理 runtime `interface.json`，不能粗暴覆盖动态 version / 本地运行字段；先比较 schema，再做安全 patch。

本轮 Codex **只生成和检查同步脚本，不自动执行**。

---

# 10. 测试

只做本地逻辑测试：

- Python syntax/import；
- visual helper synthetic test：
  - identical -> same-position 高
  - 已知纵向重叠 -> 能找到大致 overlap
  - 完全不同 -> 不给高置信 overlap
- 参数校验：
  - pair_probe 缺 ROI -> fail
  - pair_probe 缺 swipe -> fail

不要安装新依赖。

---

# 11. 本轮不做

不要：

- 自动导航
- 自动切主星/辅星/经验星
- 连续翻完整背包
- 星石 OCR
- YuanHub transport
- Backend 图片上传
- YuanStar 改动
- 生产 threshold 校准
- 写死真实 swipe px
- commit/push

---

# 12. 最终报告

## Git
- branch
- HEAD
- dirty files
- 未 commit/push

## Controller
- screenshot API
- swipe API
- settle 方式

## Probe
- 文件
- modes
- debug 输出

## Visual compare
- 算法
- 不依赖 OCR
- 当前仅 diagnostic

## GUI
- task 名称
- 如何触发
- 启动前页面要求

## Runtime sync
- 脚本路径
- 会覆盖哪些文件
- 不会碰哪些文件
- 用户下一步命令

## Tests
- 结果

## 下一步唯一操作

如果正常：

1. 关闭 `MaaYuan-v5-runtime\MaaYuan.exe`
2. 运行 sync 脚本
3. 重开 MaaYuan.exe
4. 手动进入 `星石背包 → 主星 → 顶部`
5. 只运行一次 `开发调试｜星石背包截图探针`
6. 提供生成的 `capture.png + metadata.json`

不要继续真实 `pair_probe` swipe。
