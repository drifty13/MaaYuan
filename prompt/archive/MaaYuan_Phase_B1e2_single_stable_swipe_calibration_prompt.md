# MaaYuan Phase B1e.2：单次稳定滑动校准，暂时移除正常页自动二次 swipe

## 背景：本轮真实 smoke 暴露两个明确问题

### 1. 当前 normal feedback probe 不再是“单次滑动测验”
现有 runner 在 coarse 结果为：

```text
efficiency_correction_required
```

时会立刻执行：

```text
efficiency_micro
```

因此一次正常页测试实际发生了两次 swipe。

本轮真实 attempts：

```text
coarse -> shift_estimate 358.5 -> efficiency_correction_required
efficiency_micro -> shift_estimate 100.45 -> terminal_partial_candidate
```

这不是当前阶段想要的实验方式。

### 2. motion estimator 仍被周期 alias 欺骗
肉眼上 candidate-02 明显比 candidate-01 更向下推进，但最终 metrics 反而选到：

```text
shift_y ≈ 100px
```

同时各 motion hypothesis 的 direct anchor 分数都非常接近：

```text
~0.70-0.72
```

说明 B1e.1 的 anchor 还不足以解决周期布局 alias。

因此现在禁止让 estimator 自动决定“再滑一次”。

---

# 本轮目标

只做一件事：

> 把正常页 coarse swipe 调成“单次、等待充分稳定、截图一次”，先把真实手势距离校准好。

不要继续自动 correction。
不要继续在本轮修 estimator。
不要做 collector。
不要 OCR。

---

# 1. Git

仓库：

```text
D:\Users\Yan\Projects\MaaYuan-v5-dev
```

分支：

```text
feat/yuanstar-capture-probe
```

先：

```powershell
git status --short --branch
git diff --check
```

不要 commit / push。

---

# 2. 正常页 feedback probe 改回单次 swipe

对正常页 coarse candidate：

```text
coarse swipe
→ settle
→ screenshot
→ evaluate
→ 保存 metrics
→ END
```

即使 evaluation 是：

```text
efficiency_correction_required
terminal_partial_candidate
unsafe_gap_risk
```

本次“正常页单次校准任务”都不得自动执行第二次 gesture。

## 保留代码但不要在 normal calibration 中触发

B1d 已验证的：

```text
terminal partial confirmation
bottom no_move
```

不要删除。

但请给当前 GUI normal calibration task 一个明确参数，例如：

```json
"single_swipe_calibration": true
```

或等价的最小实现。

当它为 true：

```text
任何第一次 candidate 完成后立即结束
```

不执行：
- efficiency_micro
- terminal_confirmation

这样这项 GUI 任务就是严格的一次 swipe 测试。

不要靠 `max_micro_attempts` 的隐含语义绕过去，明确写清楚 single calibration 行为。

---

# 3. coarse swipe 稍微回收

B1e.1：

```text
[360,930] -> [360,470]
700ms
```

用户真实观察认为最终推进略过。

本轮只小幅回收为：

```text
[360,930] -> [360,500]
700ms
```

不要一次大改。

---

# 4. settle 增加

当前 1800ms 在这次更大手势后，用户观察到页面尚未稳定就继续进入第二动作。

本轮单次校准改为：

```text
settle_ms = 2500
```

重点：

```text
swipe 完成
→ 完整等待 2500ms
→ 才截 candidate
```

本轮不要做 adaptive settle。

后续 collector 再单独设计 visual-stability settle。

---

# 5. estimator 暂时只诊断，不驱动手势

仍输出：
- motion hypotheses
- selected hypothesis
- local overlap
- anchor score
- shift estimate

但这轮不得根据它继续发 swipe。

并在 metrics 加：

```json
{
  "gesture_count": 1,
  "single_swipe_calibration": true
}
```

如果 estimator 与肉眼明显冲突，保留原始图与 hypotheses，后续单独修 estimator。

---

# 6. 不改 overlap / YuanStar 业务契约

继续保持：

```text
visual overlap
!=
YuanStar full-row overlap pair
```

本轮不把任何 calibration 结果发送到 YuanStar。

不：
- OCR 星石
- 写 confirmedOverlapPairs
- 判断具体 duplicate star
- 修改 YuanStar OCR

---

# 7. 测试

至少覆盖：

1. `single_swipe_calibration=true`
   - coarse 后不管 reason 是什么；
   - gesture_count 永远 1；
   - 不调用 micro swipe；
   - 不调用 terminal confirmation。

2. 非 calibration 模式：
   - 原 B1d terminal partial / bottom 逻辑仍保留。

3. pipeline：
   - coarse `[360,930] -> [360,500]`
   - settle 2500ms。

---

# 8. Runtime sync

更新现有：

```powershell
.\tools\sync_yuanstar_probe_runtime.ps1 `
  -RuntimePath "D:\Users\Yan\Projects\MaaYuan-v5-runtime"
```

保持：
- targeted patch
- UTF-8 BOM / PowerShell 5.1
- 不碰 config
- 不碰 MaaYuan.exe / MFAAvalonia / Python runtime

---

# 9. 真实 smoke

只跑一次：

```text
主星顶部
→ “正常页单次滑动校准”任务
```

验收首先看：

```text
真实只发生 1 次 swipe
页面稳定后才截图
```

请输出：

- prev.png
- candidate.png
- prev-roi.png
- candidate-roi.png
- metrics JSON

这一轮先由真实图片肉眼确定 gesture 是否合适。

不要因为 estimator 给出 conservative/terminal/unsafe 就自动进行第二次 swipe。

---

# 10. 重要：本轮不要继续自动调参

如果 `[930 -> 500]` 仍略多或略少，只报告真实结果。

不要在同一次任务中：
- 自动改 swipe；
- 自动追加 micro；
- 连续试多个参数。

我们要保持“一次只改变一个变量”的校准方式。
