# MaaYuan Phase B1b：主星正常翻页真实 Pair Probe

## 前置实测结果

B1a `capture_only` 已真实通过。

MaaFramework controller 原始截图：

```text
width    = 720
height   = 1280
channels = 3
dtype    = uint8
```

真实截图为完整竖屏星石背包页面。当前用户可以手动进入：

```text
星石背包 → 主星 → 顶部
```

本轮只做一次“正常向下翻页”的真实 pair probe。

---

## 0. 本轮目标

新增第二个临时 GUI 调试任务：

```text
开发调试｜星石背包单次滑动探针
```

它调用现有 `StarBackpackCaptureProbe` 的：

```text
mode = pair_probe
```

只完成：

```text
before screenshot
→ 一次固定 swipe
→ settle
→ after screenshot
→ 纯图像 visual compare
→ 保存 before/after/ROI/metrics
```

本轮不做连续翻页、不做到底判断、不做自动分类、不做 OCR、不做 transport。

---

# 1. Git

仓库：

```text
D:\Users\Yan\Projects\MaaYuan-v5-dev
```

当前预期分支：

```text
feat/yuanstar-capture-probe
```

先只读检查：

```powershell
git status --short --branch
git branch --show-current
git diff --check
```

不要 commit/push。

---

# 2. 使用 B1a 已验证的 controller 坐标系

真实 controller 截图为：

```text
720 × 1280
```

根据 B1a `capture.png`，本轮第一组**诊断参数**使用：

```json
{
  "mode": "pair_probe",
  "debug_dir": "debug/star-backpack-probe",
  "compare_roi": [40, 280, 640, 760],
  "swipe": {
    "start": [360, 930],
    "end": [360, 450],
    "duration_ms": 700
  },
  "settle_ms": 900,
  "compare": {
    "min_overlap_ratio": 0.20,
    "max_overlap_ratio": 0.90
  }
}
```

这些值只是 B1b diagnostic，不是生产常量。

理由：

- ROI 排除顶部资源栏、标题和主/辅/经验 tab；
- ROI 排除底部分解/自动/筛选/容量固定栏；
- swipe 在列表中央纵向执行，不触碰 tab/footer；
- 480 px 手势先用于产生一组明显可分析的正常位移样本；
- 这一步优先验证 controller swipe 与视觉 overlap helper，而不是最小化最终生产 overlap。

不要把这些参数提升为最终 production defaults。

---

# 3. GUI Task

保留已有：

```text
开发调试｜星石背包截图探针
```

默认 `capture_only`，不要改。

新增：

```text
开发调试｜星石背包单次滑动探针
```

任务说明明确写：

```text
请先手动进入「星石背包 → 主星 → 顶部」。
本任务会自动向上滑动一次，请勿用于其他页面。
```

pipeline 调用：

```text
StarBackpackCaptureProbe
mode = pair_probe
```

使用上面的显式 ROI/swipe 参数。

---

# 4. 不修改视觉算法语义

继续使用现有：

```python
compute_visual_overlap(...)
```

本轮不要调 threshold、不要加入业务分类规则。

`metrics.json` 仍然：

```text
classification = diagnostic_only
```

本轮只观察：

- `same_position_score`
- `best_overlap_score`
- `best_overlap_px`
- `best_shift_px`

并人工查看 before/after 是否与 metrics 方向一致。

---

# 5. Runtime sync 脚本

更新现有：

```text
tools/sync_yuanstar_probe_runtime.ps1
```

让它安全 patch **两个**开发任务：

1. `开发调试｜星石背包截图探针`
2. `开发调试｜星石背包单次滑动探针`

仍然：

- 只同步本轮 agent/pipeline；
- targeted backup；
- 不碰 config；
- 不碰 MaaYuan.exe；
- 不碰 MFAAvalonia；
- 不碰 Python runtime；
- 不碰日志；
- 不整体覆盖 runtime interface。

### Windows PowerShell 5.1 编码

上一轮已经真实遇到 UTF-8 无 BOM `.ps1` 在 Windows PowerShell 5.1 下中文 task 名乱码。

本轮必须保证：

```text
tools/sync_yuanstar_probe_runtime.ps1
```

以 Windows PowerShell 5.1 可稳定读取的编码保存（例如 UTF-8 BOM），不要再次让中文 `$probeName` 乱码。

---

# 6. 测试

只做：

- Python syntax/import；
- 现有 7 个 probe unit tests；
- pipeline JSON parse；
- sync PowerShell syntax；
- 确认两个 task 名能从 source interface 唯一解析。

不执行 runtime 同步。
不执行真实 swipe。

---

# 7. 本轮不做

不要：

- 连续翻页
- 自动到底
- 主/辅/经验切换
- OCR
- YuanHub
- Backend
- CaptureBatch transport
- 生产 stride 校准
- commit/push

---

# 8. 最终报告

说明：

- 修改文件
- 新 GUI task 名
- 使用的 diagnostic ROI/swipe 参数
- sync 脚本是否已兼容两个 task 和 PowerShell 5.1 中文编码
- tests
- 未 commit/push

最后只给用户下一步：

1. 关闭 MaaYuan runtime；
2. 运行 sync 脚本；
3. 重开 MaaYuan；
4. 手动进入 `星石背包 → 主星 → 顶部`；
5. 运行一次 `开发调试｜星石背包单次滑动探针`；
6. 提供：
   - `before.png`
   - `after.png`
   - `before-roi.png`
   - `after-roi.png`
   - `metrics.json`

不要继续自动第二次 swipe。
