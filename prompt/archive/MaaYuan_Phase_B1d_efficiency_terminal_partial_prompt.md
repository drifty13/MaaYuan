# MaaYuan Phase B1d：效率收敛 + near-bottom 位移选择修复

## 背景

正常页 feedback probe 已连续多次通过：

- 实际 shift 约 403～444 px
- confidence 高
- local overlap 高
- accepted = true

但 near-bottom 真实样本暴露出一个重要问题：

`feedback-metrics(5)` 中 motion hypotheses 为：

```text
~63 px   score ~36
~230 px  score ~131   ← 图像直接对齐也支持这一档
~396 px  score ~8
```

现实现却因为：

```text
diagnostic_expected_shift_px = [250, 700]
```

把约 230 px 的强证据 hypothesis 排除，最终选了约 396 px 的弱证据 hypothesis。

因此：

- `bottom_no_move` 已真实通过；
- 正常页 estimator 已基本通过；
- near-bottom estimator 仍需修；
- `expected shift` 不能继续作为硬过滤条件。

同时，当前正常页实际 shift 约 400～440 px，720×1280 controller 下 compare ROI 高 760 px，意味着每页保留约 320～360 px overlap，约接近 2 行，采图/OCR 效率偏低。

本阶段目标是把正常页推进量提高到大约“只保留 1 行左右安全 overlap”，同时保持 feedback 验证，不追求零 overlap。

---

# 1. Git

仓库：

```text
D:\Users\Yan\Projects\MaaYuan-v5-dev
```

分支预期：

```text
feat/yuanstar-capture-probe
```

先：

```powershell
git status --short --branch
git diff --check
```

不要 commit/push。

---

# 2. 修复 hypothesis 选择：prior 只能 soft bias，不能 hard filter

当前错误：

```text
candidate shift 不在 expected range
→ 直接无法被选中
```

改为：

```text
方向过滤
→ motion hypothesis clustering
→ 证据评分
→ 宽松 physical range
→ expected range 只做 soft bias / tie-break
→ 选 strongest evidence
→ local correlation 验证
```

## 物理硬边界

例如：

```json
"diagnostic_physical_shift_px": [30, 700]
```

只排除：

- 负方向；
- 近乎 no-move（另走 no_move）；
- 明显超出 ROI 的不可能位移。

## expected range

保留类似：

```json
"diagnostic_expected_shift_px": [250, 700]
```

但只能做：

- 轻量加分；
- 同分/近似分时 tie-break；

不能把 230px 这种证据远强于 396px 的 hypothesis 直接排除。

测试必须覆盖真实 near-bottom 结构：

```text
230px cluster: 175 matches / very high score
396px cluster: 12 matches / low score
expected lower bound = 250
```

最终必须选 230，而不是 396。

---

# 3. normal page 效率策略：从约 2 行 overlap 收敛到约 1 行

不要追求零 overlap。

目标：

```text
normal accepted pair:
实际 shift ≈ 500～560 px
ROI height = 760 px
剩余视觉 overlap ≈ 200～260 px
```

这大约是一行级安全余量，而不是当前约 320～360 px 的近两行余量。

仍然由 MaaYuan 自动输出 pair-level：

```text
relation = overlap
```

不做：
- duplicate row
- duplicate star
- OCR

YuanStar 继续按现有 OCR/reconcile 处理。

## 新增目标区间

例如：

```json
"diagnostic_target_shift_px": [480, 560]
```

注意区分：

```text
target range
= 效率目标

safe range
= 数据安全边界

physical range
= estimator 可考虑的物理范围
```

不要混在一起。

建议初始：

```json
target_shift_px: [480, 560]
safe_shift_px: [300, 600]
physical_shift_px: [30, 700]
```

这些仍为 diagnostic，真实 smoke 后再收。

---

# 4. coarse swipe 做一次温和加大，不继续手调零 overlap

当前：

```text
[360,930] -> [360,650]
```

真实 normal shift ~403～444。

下一轮 diagnostic 改为：

```text
[360,930] -> [360,600]
duration 700ms
settle 1800ms
```

只做温和增加。

不要直接跳到非常激进的大 swipe。

feedback estimator 仍以真实 prev/candidate 为准。

---

# 5. 正常页 acceptance

正常页 candidate：

如果：

```text
motion estimate 可信
local overlap 可信
shift 落在 safe range
```

即可 accepted。

`target range` 只用于判断效率是否理想：

```text
accepted = true
efficiency_status = target / conservative / aggressive
```

不要因为 shift=450 低于 target 就强制 micro swipe。

原因：

- 如果每页为了追 target 都追加 micro swipe + 再等 1800ms，可能截图张数少了，但交互时间反而增加；
- MVP 优先“一次 coarse 大多数直接成功”；
- micro 只留给真正过小、明显浪费的情况。

建议 micro 触发条件不要等于 target lower bound，而应明显更低，例如：

```text
shift < 300
```

再考虑 micro。

---

# 6. near-bottom terminal partial 逻辑

最后一次实际移动可能只有几十到两百多 px。

不能把：

```text
positive small shift
```

直接当失败，也不能为了达到 normal target 再不断 micro。

新增状态：

```text
terminal_partial_candidate
```

逻辑：

```text
prev
→ swipe
→ candidate 有可信正向小位移
→ candidate 已包含新内容
→ 先暂存 candidate
→ 再做一次确认 swipe
```

如果确认 swipe：

```text
no_move
```

则：

```text
接受之前的 terminal partial candidate
标记 previous -> candidate = overlap
标记 section complete
不保存 no_move confirm frame
```

如果确认 swipe仍继续移动：

```text
说明还没到底
→ 回到普通 feedback 流程
```

关键原则：

> 只要发生过真实正向移动并且图像匹配可信，就不能因为“小于 normal target”直接丢掉 candidate。

---

# 7. bottom_no_move

保持现有已真实通过逻辑：

```text
same_position_score ≈ 1
shift ≈ 0
→ bottom_no_move
→ 不保存新图
→ 当前 section 停止
```

不要改松。

---

# 8. OCR / overlap 效率边界

明确：

- 本阶段优化重点是减少**截图总数**；
- 不改 YuanStar OCR；
- 不按 machine overlap 裁掉图片区域；
- 不跳过某行 OCR；
- 不做 MaaYuan 星石识别；
- overlap pair 自动提供，不增加用户手工 pair 标注。

不要为了减少 duplicate reconcile 改动现有 OCR 业务链。

---

# 9. Debug metrics

增加：

```json
{
  "target_shift_range": [480, 560],
  "safe_shift_range": [300, 600],
  "physical_shift_range": [30, 700],
  "efficiency_status": "target | conservative | aggressive | terminal_partial",
  "selected_hypothesis_reason": {
    "evidence_score": 0,
    "expected_prior_bonus": 0,
    "was_inside_expected_range": true
  }
}
```

让下一轮可以确认 prior 没有压过真实证据。

---

# 10. Tests

至少覆盖：

1. 正常页 403/443 类样本仍选正确 hypothesis；
2. near-bottom：
   - 230px 高证据
   - 396px 低证据
   - expected lower bound 250
   - 必须选 230；
3. target/safe/physical range 互相独立；
4. normal 520px -> accepted + efficiency target；
5. 430px -> accepted + conservative，不强制 micro；
6. 200px positive reliable -> terminal_partial_candidate；
7. terminal partial + next no_move -> 接受 final candidate；
8. bottom no_move 保持；
9. unsafe true overshoot 仍 fail-safe。

不安装新依赖。

---

# 11. GUI / runtime sync

保留现有三个 probe task。

`开发调试｜星石背包反馈滑动探针` 使用新的参数。

更新 sync 脚本，继续保证：

- UTF-8 BOM / Windows PowerShell 5.1
- targeted backup
- 不碰 config
- 不碰 MaaYuan.exe
- 不碰 MFAAvalonia
- 不碰 Python runtime

---

# 12. 本轮真实 smoke 顺序

代码完成后不要 commit/push。

用户同步 runtime 后：

### Smoke A：正常页

主星顶部，运行一次 feedback probe。

验证：
- shift 是否大约进入 480～560 或至少明显高于旧 403～443；
- estimator 正确；
- accepted；
- local overlap 仍可信。

### Smoke B：near-bottom

在距离底部不远的位置运行。

验证：
- 不再被硬 expected range 强行选错误 hypothesis；
- small positive move 能保留 terminal candidate。

### Smoke C：bottom

完全到底运行。

验证：
- bottom_no_move。

不要整背包循环。

---

# 13. 最终报告

说明：

- near-bottom 230/396 误选如何修复；
- expected prior 已变 soft；
- normal target/safe/physical 三层区间；
- 新 coarse swipe；
- terminal partial 规则；
- tests；
- runtime sync；
- 未 commit/push。

最后只要求用户依次跑 A/B/C 三组 smoke。
