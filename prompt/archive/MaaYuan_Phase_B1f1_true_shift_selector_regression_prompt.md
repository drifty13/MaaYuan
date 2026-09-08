# MaaYuan Phase B1f.1：锁定手势后，修复真实纵向位移 hypothesis selector

## 目标

B1e.2 的手势参数已经通过 3 次真实 MuMu smoke 肉眼验收，**本轮禁止继续调整手势**。

现在只修一件事：

> 让 feedback probe 在周期性四列星石页面中，稳定选中真实纵向位移 hypothesis，而不是被相差约 1～3 行的周期 alias 欺骗。

本轮不做：
- 新 swipe 参数调优；
- 自动第二次 swipe；
- collector；
- OCR；
- row semantic overlap 最终判定；
- YuanStar confirmedOverlapPairs 写入；
- commit / push。

---

# 0. 已锁定的真实手势参数：严禁修改

仓库：

```text
D:\Users\Yan\Projects\MaaYuan-v5-dev
```

分支：

```text
feat/yuanstar-capture-probe
```

当前 normal calibration 手势：

```text
start: [360, 930]
end:   [360, 540]
duration_ms: 700
settle_ms: 2500
single_swipe_calibration: true
```

这组参数已经连续 3 次真实 smoke 肉眼通过。

**本轮所有代码都必须建立在这组参数不变的前提下。**

---

# 1. 三次真实 smoke：当前 selector 的明确错误

以下是同一个固定手势的 3 次真实结果。

## Run A

当前错误选中：

```text
122.4 px
anchor_score ≈ 0.751
```

hypotheses 中真实视觉位移对应：

```text
622.0 px
anchor_score ≈ 0.870
```

其他周期 alias：

```text
289.0
455.36
```

---

## Run B

当前错误选中：

```text
307.0 px
anchor_score ≈ 0.865
```

真实视觉位移对应：

```text
640.0 px
anchor_score ≈ 0.907
```

其他周期 alias：

```text
140.4
473.76
```

---

## Run C

当前错误选中：

```text
97.0 px
anchor_score ≈ 0.743
```

真实视觉位移对应：

```text
596.4 px
anchor_score ≈ 0.828
```

其他周期 alias：

```text
263.52
430.0
```

---

## 真实校准结论

同一固定手势的真实 motion 分布：

```text
596.4 ～ 640.0 px
```

平均：

```text
≈ 619.5 px
```

按 row pitch ≈ 166.5：

```text
≈ 3.58 ～ 3.84 行
```

这与肉眼验收完全一致。

当前 selector 的问题不是“没有生成正确 hypothesis”，而是：

> **正确 hypothesis 已经存在，但 selection ranking 错了。**

---

# 2. 为什么当前 selector 会错

现有 ranking 仍过度偏向：

- match_count；
- evidence_score；
- 周期性结构带来的高 feature support。

星石页面是高度周期性的四列网格，因此：

```text
真实 shift
```

和：

```text
真实 shift - 1 row pitch
真实 shift - 2 row pitch
真实 shift - 3 row pitch
```

都可能得到很强 ORB / RANSAC 支持。

所以：

```text
“match 更多”
```

不能再作为 dominant criterion。

B1e.1 加入的固定 120px direct anchor 有帮助，但仍不够，因为 120px 本身也可能落在高度周期性的卡面区域。

---

# 3. 本轮核心修复：每个 hypothesis 做 full available overlap direct validation

对每个正向 hypothesis：

```text
shift = s
ROI height = H
```

真实共享区域应该是：

```text
prev[s:H]
candidate[0:H-s]
```

因此不要只固定比较 120px。

改为：

```text
available_overlap_h = H - round(s)
```

如果：

```text
available_overlap_h >= MIN_DIRECT_OVERLAP
```

则直接比较：

```text
prev[s : s + available_overlap_h]
candidate[0 : available_overlap_h]
```

建议：

```text
MIN_DIRECT_OVERLAP = 80px
```

可以在上下各裁少量 margin，例如 4～8px，避免 interpolation / capture 边缘。

---

# 4. direct full-overlap score

为每个 hypothesis 新增：

```json
{
  "full_overlap_score": 0.0,
  "full_overlap_height_px": 0,
  "full_overlap_gray_score": 0.0,
  "full_overlap_gradient_score": 0.0
}
```

不要 OCR。

可以复用现有 OpenCV / numpy 工具，组合：

### A. grayscale normalized correlation

比较整段 overlap：

```text
prev overlap
vs
candidate overlap
```

### B. gradient / edge correlation

降低星石圆盘大面积相似颜色对周期 alias 的误导。

建议组合：

```text
full_overlap_score =
    0.45 * gray_score
  + 0.55 * gradient_score
```

具体比例可以根据现有实现微调，但 gradient 不应低于 gray 权重。

不要新增大型依赖。

---

# 5. selection 规则改为两阶段，不要让 normal motion 与 terminal partial 混在一起竞争

## Stage A：normal-motion candidate gate

这组固定手势已经真实校准，因此 normal page 的**物理先验**可以作为强 gate，而不是 0.03 级 soft bonus。

定义 diagnostic normal motion band：

```text
NORMAL_MOTION_MIN = 560px
NORMAL_MOTION_MAX = 660px
```

注意：

这不是要求最终一定 610～630；
真实 smoke 已经证明：

```text
596.4
622
640
```

都可能是正常结果。

在所有 hypotheses 中先找：

```text
560 <= shift_y <= 660
```

且满足基础可信度，例如：

```text
full_overlap_height_px >= 80
anchor/full-overlap 有效
MAD 不异常
direction 正确
```

的候选。

如果 normal band 内存在可信 candidate：

> **低位周期 alias（97 / 122 / 140 / 263 / 289 / 307 / 430 / 455 / 473）不得仅凭 match_count 更大而击败 normal candidate。**

---

## Stage B：normal band 内排序

normal band 内优先级：

1. `full_overlap_score`
2. 原有 `anchor_score`
3. spatial x coverage
4. MAD
5. match_count 只做最低支持，不做 dominant weight

建议 selection score 结构：

```text
0.55 * full_overlap_score
+ 0.25 * anchor_score
+ 0.10 * x_coverage
+ 0.10 * robust_feature_support
```

不要让 match_count 直接把 selector 拉回低位 alias。

如果只有一个可信 normal candidate，直接选它。

---

# 6. fallback：保留 near-bottom / terminal partial 能力

不能把 selector 简化成：

```text
永远选 560～660
```

因为真正 near-bottom 时，实际 shift 可以明显更小。

因此：

### 如果 normal band 内存在可信 candidate
选 normal candidate。

### 如果 normal band 内没有可信 candidate
才进入现有 fallback：

```text
small positive motion
terminal partial
bottom no_move
```

继续保留 B1d 已通过行为。

也就是说：

```text
normal motion hypothesis 有可信证据
→ normal selector

没有
→ terminal/bottom fallback
```

不要让两类状态在第一层 ranking 里互相竞争。

---

# 7. 当前 expected prior 的语义也要清理

现在 metrics 里：

```text
289
455
622
```

都可能出现：

```text
was_inside_expected_range = true
```

这容易误导，因为“expected range”目前并不等同于真实 normal motion band。

本轮请明确拆开字段：

```json
{
  "inside_normal_motion_band": true,
  "inside_physical_motion_range": true
}
```

不要再让一个模糊的：

```text
was_inside_expected_range
```

承担两种语义。

如果为兼容保留旧字段，也必须明确它的旧语义，并新增新的字段。

---

# 8. selected_hypothesis_reason

输出明确可审计原因，例如：

```json
{
  "selection_mode": "normal_motion_full_overlap",
  "normal_motion_candidate_count": 1,
  "selected_by": "full_overlap_score",
  "fallback_used": false
}
```

fallback 时：

```json
{
  "selection_mode": "terminal_fallback",
  "fallback_used": true
}
```

这样后续看到 JSON 就知道为什么选了某一个 branch。

---

# 9. 三个真实 regression case 必须成为验收条件

不要把用户真实游戏截图提交进 Git。

可以：

### 方案 A（优先）
从本地最新 3 个 probe run 目录读取图片，跑一个**不入库的 local diagnostic regression**。

要求最终 selected shift 分别落在：

```text
Run A: 622 ± 20 px
Run B: 640 ± 20 px
Run C: 596.4 ± 20 px
```

而不能再选：

```text
122
307
97
```

### 方案 B
如果本地 run 目录定位不稳定，则补 synthetic periodic-grid 单测，模拟：
- 多个相隔约 166.5px 的周期 alias；
- true branch 拥有最高 full-overlap direct correlation；
- 低位 alias match_count 更高；
- selector 仍必须选 true branch。

最好 A + B 都做。

---

# 10. 单元测试至少覆盖

1. normal band 存在可信 true hypothesis：
   - low alias match_count 更高；
   - true hypothesis full_overlap_score 更高；
   - 必须选 true。

2. 三个真实分布：
   ```text
   ~622
   ~640
   ~596
   ```

3. normal band 没有可信 candidate：
   - 可以 fallback 到小 positive motion；
   - B1d terminal partial 不回归。

4. no_move：
   - 不受 normal prior 强行拉到 560～660。

5. full-overlap strip < 80px：
   - 不得伪造 score；
   - 标记 invalid / insufficient support。

6. periodic alias：
   - match_count 最大的 branch 不一定胜出。

---

# 11. 暂时不要改 semantic overlap 判定

当前：

```text
ocr_overlap_pair_required
```

仍然可能因为简单的：

```text
visual_overlap_px >= row_pitch * 0.90
```

而误判。

**本轮先不要同时修这个。**

先让：

```text
selected shift
```

变得可信。

B1f.1 通过后，再单独做 B1f.2：

```text
根据真实 row phase / 可完整 OCR 行几何
判断 full-row overlap yes/no
```

避免一次改两个核心变量。

---

# 12. 不允许修改的内容

本轮不要修改：

```text
swipe 930 -> 540
700ms
2500ms settle
single_swipe_calibration=true
```

不要：
- 自动 micro swipe；
- 自动 terminal confirmation 在 calibration mode 中执行；
- OCR 名称/等级；
- 改 YuanStar；
- 改 Backend；
- 改 YuanHub；
- 改 MaaYuan runtime 本体；
- commit/push。

---

# 13. 验证

完成代码后：

```text
Python compile
相关 probe unit tests
pipeline JSON
PowerShell sync script syntax
git diff --check
```

然后同步到 runtime：

```powershell
.\tools\sync_yuanstar_probe_runtime.ps1 `
  -RuntimePath "D:\Users\Yan\Projects\MaaYuan-v5-runtime"
```

但**不要自动做新的 MuMu swipe**，先报告代码与 local regression。

---

# 14. 最终报告格式

请明确给出：

```text
B1f.1 PASS / PARTIAL / FAIL
```

以及：

### 代码
- 修改文件
- selector 新逻辑
- full-overlap score 定义

### 三个真实 regression
```text
Run A: old 122 -> new ?
Run B: old 307 -> new ?
Run C: old 97  -> new ?
```

目标：

```text
≈622
≈640
≈596
```

### 回归
- B1d terminal partial
- bottom no_move
- single swipe calibration

### Git
- branch
- status
- 未 commit / push

如果三组真实 regression 尚未全部选到正确 high-shift branch，不要进入 B1f.2。
