# MaaYuan Phase B1c.1：修复真实滚动位移估计的周期性误匹配

## 现状与真实 smoke 结论

B1c 第一次真实 `feedback_probe` 已完成。

真实输出：

```json
{
  "shift_y": -70.019,
  "inlier_count": 52,
  "match_count": 256,
  "confidence": 0.1948,
  "local_overlap_score": -1.0,
  "accepted": false,
  "reason": "unsafe_gap_risk"
}
```

肉眼检查 `prev.png` / `candidate.png` 可确认：

- 游戏内容实际是**向上移动了数个星石行**
- `shift_y = -70` 明显是假匹配
- 页面具有强周期结构：四列金色星石 + 固定行距
- 当前 ORB + 单次 `estimateAffinePartial2D(RANSAC)` 仍可能锁到错误的“相邻周期”
- 因为 confidence < threshold，安全逻辑正确地在第一次 coarse swipe 后停止，没有执行 micro swipe
- `local_overlap_score = -1` 是负 shift 导致局部搜索窗口为空的次生问题

因此本轮不要改“失败就停止”的安全策略，而是修**motion estimator**。

---

# 目标

让真实主星页面中：

```text
upward swipe
→ content 向上移动
```

时，位移估计：

1. 不再接受反方向 alias；
2. 不在所有重复行匹配中直接做一个全局 affine RANSAC；
3. 先生成多个纵向 shift hypothesis；
4. 利用方向、宽松的 gesture prior、match 支持度和空间覆盖选出真实 hypothesis；
5. 再在该 hypothesis 附近做局部 correlation 确认。

仍然不做 OCR。

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

先检查：

```powershell
git status --short --branch
git diff --check
```

不要 commit/push。

---

# 2. 保留安全控制流

以下逻辑保持：

```text
accepted
→ 接受 candidate

move_too_small
→ 最多 micro swipe

unsafe_gap_risk
→ 立即停止，不继续向下滑

bottom_no_move
→ 停止
```

第一次真实 smoke 只滑一次正是因为 estimator 给出低 confidence / unsafe_gap_risk。

这是正确 fail-safe，不要为了“让它多滑几次”放宽。

---

# 3. 修复方向过滤

当前 feature match 允许正负 dy 都进入 RANSAC。

对于当前 probe：

```text
手势：finger 向上滑
预期：list content 向上移动
```

定义：

```text
shift_y = before_y - after_y
```

则正常向下浏览必须：

```text
shift_y > 0
```

在 feedback probe 的 upward-scroll estimator 中：

- 排除明显 `shift_y <= 0` 的 match；
- 可保留接近 0 的 evidence 给 no_move 独立判断；
- 不允许反方向周期 alias 主导真实 movement estimate。

不要把该方向假设硬塞进通用 OCR 或其他 MaaYuan action；只作用于这个星石滚动 probe / 可参数化 estimator。

---

# 4. 不再直接对所有 match 做一个 affine RANSAC

实现 1D vertical-motion hypothesis clustering。

对 Lowe ratio + `abs(dx)` 过滤后的每个 match：

```python
motion_y = before_y - after_y
```

只对正向 candidate 做聚类。

建议：

- 以约 `8~12 px` tolerance 聚类；
- 每个 cluster 计算：
  - center/median shift
  - match count
  - MAD
  - x coverage
  - y coverage
  - descriptor distance statistics

输出多个 hypothesis，例如：

```json
[
  {
    "shift_y": 598.4,
    "match_count": 81,
    "mad": 1.2,
    "x_coverage": 0.83,
    "y_coverage": 0.71
  },
  {
    "shift_y": 431.7,
    "match_count": 37,
    "mad": 1.6
  }
]
```

---

# 5. 增加“宽松 gesture prior”，只用于消歧义

不要再假设固定 stride。

但我们知道 coarse swipe 不可能意味着：

```text
真实向下浏览却 content 反向移动
```

也不应该优先接受接近 0 的周期 alias。

在 feedback config 增加独立字段，例如：

```json
"diagnostic_expected_shift_px": [250, 700]
```

注意：

- 这是**宽松消歧义 prior**
- 不是 accepted safe range
- 不是累计位置
- 不是固定 stride
- 每一页仍然从真实 prev/candidate 重新估计

真实 acceptance 仍继续使用：

```json
"diagnostic_safe_shift_px": [140, 520]
```

这样：

- estimator 可以识别“真实移动约 600px”
- 但业务仍可判定它超过当前安全上限而拒绝
- 不会为了让 estimator 看起来成功而放宽安全规则

---

# 6. Hypothesis 选择

在 `diagnostic_expected_shift_px` 内，对 hypothesis 综合评分。

优先：

1. match support 多；
2. MAD 小；
3. x coverage 广（不是只在某一列金色圆盘重复纹理里成立）；
4. y coverage 广；
5. descriptor quality 合理。

不要单纯选择：
- shift 最接近某个固定目标；
- 全局 NCC 最高峰。

选出 primary hypothesis 后：

- 只在该 cluster 内做 translation/RANSAC refinement；
- `shift_y` 最终应保持正向定义。

---

# 7. 局部 correlation 只做确认

得到 primary `shift_y` 后：

```text
shift_y ± 20px
```

做现有 local correlation。

不要全 ROI 扫描所有 offset。

同时修复边界：

- predicted shift < 0
- predicted shift >= ROI height
- local search range 为空

这种情况不要返回神秘的 `-1`。

输出明确状态，例如：

```text
local_overlap_valid = false
local_overlap_score = null
```

---

# 8. Debug 指标增强

`feedback-metrics.json` 增加：

```json
{
  "motion_hypotheses": [],
  "selected_hypothesis": {},
  "direction_rejected_match_count": 0,
  "local_overlap_valid": true
}
```

这样下一次真实 smoke 可以直接看它为什么选某个 shift。

---

# 9. Coarse swipe 暂时再保守一点

当前：

```text
[360,930] -> [360,560]
```

真实 swipe 看起来推进偏大。

为了后续安全 smoke，本轮把 coarse diagnostic 改为：

```text
[360,930] -> [360,650]
duration 700ms
settle 1800ms
```

micro 暂时保持现有较小手势。

目的只是让下一次真实 sample 更可能落入 `safe_shift <= 520`。

仍然不把它视为固定 stride。

---

# 10. Tests

至少新增：

### A. 周期性页面 alias

构造：
- 多个相似重复行
- 少量独特局部纹理
- 真实向上 shift 约 500~600px
- 同时制造 ±一个行周期的假 matches

要求：
- estimator 选择真实正向 cluster
- 不选反方向/近零 alias

### B. 方向

向上浏览：
- 负/反向 hypothesis 不应成为 selected

### C. 真实 shift 超 safe range

例如：
- estimator 正确估计 600
- expected prior 允许
- safe range 最大 520

结果必须：

```text
accepted = false
reason = unsafe_gap_risk
```

证明“估计正确”和“业务接受”是两回事。

### D. move too small

正确进入 micro path。

### E. no_move

保持已有逻辑。

---

# 11. 不做

不要：

- 整背包循环
- OCR
- YuanHub
- Backend
- 自动导航
- 放宽 fail-safe
- commit/push

---

# 12. 最终报告

必须说明：

1. 为什么第一次真实 run 只滑了一次；
2. 为什么 `-70px` 是周期 alias；
3. 新 hypothesis clustering 的选择逻辑；
4. expected prior 与 safe range 的区别；
5. 新 coarse swipe 参数；
6. tests；
7. runtime sync 命令。

最后只让用户：

```text
关闭 runtime
→ sync
→ 重开
→ 主星顶部
→ 运行一次 feedback probe
→ 提供 prev/candidate/feedback-metrics.json
```

不要连续跑。
