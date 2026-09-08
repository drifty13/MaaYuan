# MaaYuan Phase B1f.1.1：补齐 normal-band direct candidate generation

## 目标

上一轮 B1f.1 已经修复了一个问题：

> 当真实高位移 hypothesis 已经存在时，selector 能够正确选中它，而不再被 1/2/3 行周期 alias 抢走。

但最新一次真实 MuMu live smoke 暴露出新的、更加底层的问题：

> **正确的约 4 行真实位移根本没有进入 ORB hypothesis 列表。**

因此本轮只做一件事：

> 在正常翻页的已知物理区间内，新增一个轻量的 direct visual candidate search，把 ORB 没生成出来的真实 normal-motion shift 补进 hypothesis 集合，再交给现有 selector 统一排序。

本轮不做：
- 不再调 swipe；
- 不改 OCR；
- 不改 YuanStar；
- 不改 semantic overlap / `ocr_overlap_pair_required`；
- 不做 collector；
- 不做自动多页；
- 不改 terminal / bottom 流程；
- 不 commit / push。

---

# 0. 仓库与分支

仓库：

```text
D:\Users\Yan\Projects\MaaYuan-v5-dev
```

分支：

```text
feat/yuanstar-capture-probe
```

先检查：

```powershell
git status --short --branch
git log -1 --oneline
```

不要 pull / reset / stash / merge。

---

# 1. 已锁定的真实 swipe 参数：严禁修改

当前 normal calibration 手势已经多次真实验收通过：

```text
start: [360, 930]
end:   [360, 540]
duration_ms: 700
settle_ms: 2500
single_swipe_calibration: true
```

**本轮禁止修改这些参数。**

---

# 2. 最新 live smoke：明确失败证据

最新真实 MuMu 运行中，画面肉眼显示正常翻页，实际位移约 3.8～4 行，约：

```text
~620–650 px
```

但当前 estimator 输出为：

```text
shift_y = 151.64
selection_mode = terminal_fallback
normal_motion_candidate_count = 0
fallback_used = true
accepted = false
reason = terminal_partial_candidate
```

ORB 只生成了三个正向 hypothesis：

```text
151.2
318.0
484.0
```

它们近似对应：

```text
~1 row
~2 rows
~3 rows
```

而真实的：

```text
~620–650 px
```

根本没有进入 hypothesis 列表。

这说明当前 B1f.1 selector 本身不是这次的主要问题：

> selector 只能在已有 hypotheses 中选；如果真实 branch 没被 ORB proposer 提出，它无法恢复。

---

# 3. 本轮设计原则

保留现有：

```text
ORB / BFMatcher / RANSAC
```

作为 feature-based proposer。

新增一个：

```text
normal-band direct candidate generator
```

作为 deterministic fallback proposer。

最终：

```text
ORB hypotheses
        +
direct normal-band hypothesis
        ↓
统一 dedupe / validation
        ↓
现有 B1f.1 selector
```

不要建立第二套 selector。

---

# 4. direct search 的范围

已经通过真实 smoke 确认 normal page 的物理运动范围：

```text
560–660 px
```

本轮只在这个窄范围内搜索：

```python
NORMAL_DIRECT_MIN = 560
NORMAL_DIRECT_MAX = 660
```

不要扫描整个 0–700。

理由：
- 控制耗时；
- 降低周期 alias；
- normal page 与 near-bottom / no_move 分层处理；
- terminal fallback 已由现有逻辑负责。

---

# 5. direct candidate search 方法

对每一个整数 shift `s`：

```text
s ∈ [560, 660]
```

计算实际共享区域：

```text
prev[s:H]
candidate[0:H-s]
```

设：

```text
overlap_h = H - s
```

如果：

```text
overlap_h < MIN_DIRECT_OVERLAP_PX
```

则跳过。

现有代码里已经有：

```text
MIN_DIRECT_OVERLAP_PX = 80
```

优先复用，不新增重复常量。

允许上下裁 4～8px edge margin，避免截图边缘误差。

---

# 6. direct score

尽量复用 B1f.1 已有 full-overlap validation。

对每个 `s` 计算：

```text
gray_score
gradient_score
```

并组合：

```text
direct_score =
    0.45 * gray_score
  + 0.55 * gradient_score
```

不要新增 OCR。

不要新增大型依赖。

---

# 7. 必须避免的“宽平顶”问题

星石页面高度周期化，因此 normal band 内可能出现一个较宽的高分 plateau，而不是单点尖峰。

不要简单：

```python
best = max(score)
```

就结束。

至少做以下一种稳健处理：

## 推荐：局部峰 + 邻域平均

对每个 `s` 计算：

```text
score(s)
```

同时计算：

```text
local_mean(s) = mean(score[s-2:s+2])
```

最终 direct rank 例如：

```text
0.7 * score(s)
+ 0.3 * local_mean(s)
```

避免单像素噪声。

如果当前实现已有平滑工具，可直接复用。

---

# 8. direct candidate 的可信门槛

不要只要 560–660 内有结果就强行注入。

至少要求：

```text
full_overlap_valid = true
overlap_h >= 80
direct_score >= 合理阈值
```

阈值不要拍脑袋写得太高。

先根据本地已有真实 run 统计：

```text
真实 branch direct/full overlap score
错误低位 alias score
```

再确定一个最小门槛。

目标不是“用阈值直接识别 shift”，而只是：

> 保证 normal-band direct branch 至少能成为一个可信 hypothesis。

---

# 9. 生成 hypothesis 的字段

direct candidate 应转成与现有 motion hypothesis 兼容的数据结构。

例如：

```json
{
  "shift_y": 6xx.x,
  "match_count": 0,
  "median_abs_deviation": 0,
  "x_coverage": 1.0,
  "y_coverage": 1.0,
  "mean_descriptor_distance": null,
  "anchor_score": ...,
  "full_overlap_score": ...,
  "full_overlap_height_px": ...,
  "full_overlap_gray_score": ...,
  "full_overlap_gradient_score": ...,
  "full_overlap_valid": true,
  "evidence_score": ...,
  "inside_normal_motion_band": true,
  "inside_physical_motion_range": true,
  "proposal_source": "direct_normal_band"
}
```

注意：

不要伪造：

```text
match_count
descriptor distance
MAD
```

如果这些字段语义属于 ORB，direct candidate 应明确写 null / 0，并通过 `proposal_source` 区分。

---

# 10. ORB hypothesis 与 direct candidate 的 dedupe

如果 ORB 本身已经生成了接近真实 shift 的 branch，例如：

```text
ORB: 622
direct: 620
```

不要保留两份重复 branch。

按例如：

```text
abs(shift_a - shift_b) <= 12px
```

做 dedupe。

优先策略建议：

- 保留一个 merged candidate；
- full-overlap 采用更可信的 direct validation；
- ORB feature support 可以保留为辅助字段。

不要让 direct candidate 与 ORB true branch 相互竞争造成重复。

---

# 11. selector 不要重写

B1f.1 已经实现：

```text
normal band 内先竞争
→ full-overlap / anchor / x coverage / feature support 排序
→ normal band 无可信候选才 terminal fallback
```

本轮不要重新设计 selection。

只需要让新的 direct candidate：

```text
进入现有 hypothesis 集合
```

并能被现有 selector 正常选中。

---

# 12. 最新 live regression：本轮最关键验收

必须优先找到用户刚刚运行产生的最新 probe run。

其 metrics 具有以下特征：

```text
shift_y ≈ 151.6356
hypotheses = 151.2 / 318 / 484
normal_motion_candidate_count = 0
selection_mode = terminal_fallback
gesture = [360,930] -> [360,540]
```

对这组真实 prev / candidate 图片运行修复后的 estimator。

目标：

```text
new selected shift ≈ 620–650 px
```

更具体可接受：

```text
590–660 px
```

但应尽量给出实际 direct peak 数值。

并且：

```text
selection_mode = normal_motion_full_overlap
normal_motion_candidate_count >= 1
fallback_used = false
accepted = true
```

如果当前 accepted 判定受后续旧 semantic overlap 逻辑影响，可以不强行要求 accepted=true，但必须明确：

```text
normal shift selection 已正确
```

不要为了让 accepted=true 去改 `ocr_overlap_pair_required`。

---

# 13. 之前三组 regression 也必须继续通过

B1f.1 已经成功修复的三组：

```text
Run A: ~621.93
Run B: ~640.24
Run C: ~596.62
```

本轮完成后必须继续保持。

不能因为新增 direct proposer 导致：

```text
A/B/C 回退到错误周期 alias
```

---

# 14. terminal / bottom 回归

必须确认：

### near-bottom
normal direct candidate 不应因为固定 560–660 搜索就强行覆盖真实小位移。

如果 normal direct score 不可信：

```text
→ 不注入可信 normal candidate
→ 继续走现有 terminal fallback
```

### bottom no_move
不能伪造 560–660 normal candidate。

如果截图基本不动：

```text
→ direct normal-band score 应不通过可信门槛
→ 保留 no_move
```

---

# 15. 性能要求

normal direct search 只有约：

```text
101 个 shift
```

而每次只比较现成 ROI。

要求记录额外耗时，例如：

```text
direct_search_ms
```

目标：

```text
< 100ms
```

如果 Python/OpenCV 实际略高但仍 <200ms，可以接受。

不要引入逐 shift ORB、OCR 或昂贵模型。

---

# 16. metrics 新增审计字段

建议增加：

```json
{
  "direct_normal_search": {
    "enabled": true,
    "min_shift_px": 560,
    "max_shift_px": 660,
    "best_shift_px": 6xx,
    "best_score": 0.x,
    "candidate_injected": true,
    "elapsed_ms": 12.3
  }
}
```

每个 hypothesis 增加：

```text
proposal_source
```

取值至少：

```text
orb
direct_normal_band
merged
```

这样以后能直接看出真实 branch 是谁提出的。

---

# 17. 本轮不要碰 semantic overlap

特别强调：

当前：

```text
visual_overlap
ocr_overlap_pair_required
```

仍然可能语义不正确。

**本轮禁止修改。**

B1f.1.1 只解决：

```text
真实 normal motion hypothesis 缺失
```

等 shift 稳定之后，下一轮 B1f.2 再处理：

```text
有物理 overlap
≠
有完整 OCR 行 overlap
```

---

# 18. 测试

至少新增：

1. ORB 只有：
   ```text
   151 / 318 / 484
   ```
   direct normal search 能补出：
   ```text
   ~620–650
   ```

2. ORB 已有：
   ```text
   622
   ```
   direct：
   ```text
   620
   ```
   dedupe 后只保留一个 true branch。

3. periodic alias：
   direct true branch 的 match_count=0，
   低位 alias match_count 很高，
   selector 仍选 normal true branch。

4. near-bottom：
   direct normal search 不可信，
   terminal fallback 保留。

5. no_move：
   不得伪造 normal candidate。

6. overlap height < 80：
   direct candidate invalid。

---

# 19. 验证命令

完成后至少执行：

```text
Python compile
相关 probe unit tests
pipeline JSON validation
PowerShell sync script syntax
git diff --check
```

然后：

```powershell
.\tools\sync_yuanstar_probe_runtime.ps1 `
  -RuntimePath "D:\Users\Yan\Projects\MaaYuan-v5-runtime"
```

**不要自动触发新的 MuMu swipe。**

---

# 20. 最终报告

请明确输出：

```text
B1f.1.1 PASS / PARTIAL / FAIL
```

并给出：

## 最新 live regression

```text
旧 selected shift: 151.2
ORB hypotheses: 151 / 318 / 484
direct search best: ?
最终 selected shift: ?
selection_mode: ?
fallback_used: ?
```

## 旧三组 regression

```text
A: ?
B: ?
C: ?
```

目标仍为：

```text
~622
~640
~596
```

## 回归

```text
terminal partial
bottom no_move
single swipe calibration
```

## 性能

```text
direct_search_ms
```

## Git

```text
branch
status
未 commit / push
```

如果最新 live regression 仍然无法补出可信的 590–660px branch，则不要进入 B1f.2。
