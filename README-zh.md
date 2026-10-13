# phocinae-rulepack

**读一份台账 → 对一版规则包 → 只输出差异供人复核。** 零模型调用，零第三方运行时依赖。

<p>
  <img alt="python" src="https://img.shields.io/static/v1?label=python&message=%3E%3D3.9&color=3776AB&style=flat-square">
  <img alt="deps" src="https://img.shields.io/static/v1?label=runtime%20deps&message=0&color=success&style=flat-square">
  <img alt="model calls" src="https://img.shields.io/static/v1?label=model%20calls&message=0&color=blueviolet&style=flat-square">
  <img alt="License" src="https://img.shields.io/static/v1?label=License&message=Apache-2.0&color=blue&style=flat-square">
</p>

[English](./README.md)

---

## 为什么做这个：一条实测

同一个判定模型，同一个问题换两种问法，在 53 条已标注命令上的表现：

| 问法 | 对破坏性命令的召回 |
|---|---|
| 「这条该被拦吗？」（布尔） | **0.00** —— 31 条全放行 |
| allow / ask / deny（三值） | 0.74 |
| harmless / risky / destructive（标度） | 0.97 |

而在一个 14 条申报的政策校验电池上，**规则内核 14/14、零模型调用**；
同一个模型被直接问「该批还是该拒」时，把 **8 条合规申报全部拒掉**。

本包就建立在这个结论上：*规则内核值得单独做成不带模型的确定性插件。*

如果你要的是那套测量工具而不是内核，看
[`phocinae-formulate`](https://github.com/Phocinae/phocinae-formulate)。

## 安装

```sh
pip install phocinae-rulepack==0.1.0
```

需要 Python 3.9 或更高。无依赖。本包**不会打开任何网络连接**。

## 用法

```sh
# 校验一个 pack：schema、引文逐字、语料哈希
phocinae-rulepack validate expense-policy

# 跑一份文档（JSON 或 YAML；'-' 读 stdin）
phocinae-rulepack check expense-policy claim.json

# 跑一本台账，输出一个信封
phocinae-rulepack check expense-policy ledger.json --format json

# 看包里有什么
phocinae-rulepack list --packs-dir ./packs
```

退出码就是契约：

| 码 | 含义 |
|---|---|
| `0` | 全部 `pass` |
| `1` | 存在 `fail` |
| `2` | 无 `fail`，但存在 `review`（灰区 → 人决定） |
| `3` | 用法/配置错误，**或空扫描** |

优先级固定且完备：`3 > 1 > 2 > 0`。

## 三态结果

```json
{"rulepack":"expense-policy","verdict":"fail","model_calls":0,
 "reasons":[{"rule":"r2_meal_cap","verdict":"fail","reason_code":"OVER_CATEGORY_CAP",
             "cite":["c2","c4"],"evidence":"matched:r2_meal_cap"}],
 "unmatched_paths":["id"]}
```

* **`review` 是「交人决定」**，不是「回头再看看」。
* **`pass` 必须由一条声称 pass 的规则命中产生。** 一条规则都没命中的文档是
  `review`（`NO_RULE_MATCHED`）—— 没有任何东西会静静滑过变成放行。
* **字段缺失或类型不对永远不会变成 `pass`**，缺失一律 `review`，绝不当成合规。
* **真违规优先于字段缺失。** 一条规则发现违规、另一条无法求值时，判 `fail`，两条都报出来。
* **`model_calls` 是真实计数器，且恒为 `0`。**

## 取证模型才是重点

规则的成色取决于它背后的原文，所以每条引文必须说明出处，以及**有没有人真读过那份原文**：

| `evidence_level` | 含义 | 能不能据此判 `fail` |
|---|---|---|
| `verbatim` | 引文在语料里逐字出现 | 能 |
| `derived` | 主管机关的释义转述，不是条款原文 | 能，但打警告 |
| `unavailable` | **本次未取得**条款原文 | **不能 —— 判定被强制封顶为 `review`** |

这道封顶就是「诚实的工具」与「假门」的分界。**依据没人读过的规则，不可以用来驳回别人的材料。**
测试对这条封顶做了双向验证：把引文改成 `derived`，同一份输入必须从 `review` 变成 `fail`。

`validate` 会把每条引文拿到语料里逐字解析，并重算每个 sha256。
引文改一个字、或哈希写错，校验即失败。
`--strict` 另外拒绝样例语料与 `unavailable` 引文。

## 写一个 pack

```yaml
schema: phocinae-rulepack/v1
id: my-check
title: 这个 pack 校验什么
version: 0.1.0
missing_field_policy: review        # v1 只接受 'review'
corpus:
  - path: sources/spec.txt
    role: authority                  # authority | production | sample
    sha256: <64 位大写十六进制>
citations:
  - id: c1
    source: 原文出处
    locator: 第 4.2 条
    quote: "逐字抄下来的原话"
    document: sources/spec.txt
    evidence_level: verbatim
rules:
  - id: r1_limit
    when:
      all_of:
        - {field: amount, op: ">", value: 500}
        - {field: receipt, op: "==", value: false}
    then: {verdict: fail, reason_code: OVER_LIMIT, cite: [c1]}
    require_fields: [amount, receipt]
```

表达式语言是刻意做小的：`field OP value`，用 `all_of` / `any_of` / `not` 组合，
`value` 可以是 `{"ref": "other.field"}` 用来比较两个字段。
算子：`== != < <= > >= in not_in matches exists missing`。

**没有**算术、没有自定义函数、没有循环、没有网络。
需要算出来的值，请在构造输入文档的适配器里算 —— 这样判定依据留在 pack 里，可引用、可测试。

### 两个值得知道的 YAML 陷阱

这两种都会解析成「看起来对但其实错」的东西，所以加载器选择报错而不是猜：

```yaml
op: >            # 错：这是折叠块标量，会把下面的行吞掉
op: ">"          # 对：算子要加引号

note: 含有 ": " 的行内文本    # 错：YAML 认为那里要开一个新键
note: "含有 \": \" 的行内文本"  # 对：加引号，或用块标量
```

## 出厂内容

| pack | 场景 | 规则数 |
|---|---|---|
| `expense-policy` | S15（报销预判演示） | 8 |

> 编号说明：这里的 "S15" 指 gallery 的 S15 报销演示。
> 在 182 场景总表里 S15 是另一件事（多语低资源扩展）。

## 测试

```sh
python tests/run_all.py
```

不联网、不需要模型、不需要第三方包。
一个断言都没跑起来时套件**退出非零** —— 「什么都没检查」不算成功，
这和引擎对空扫描的态度是同一条规则。

测试**从不使用 `tempfile`**：临时目录走 `$PHOCINAE_RULEPACK_TMP`，或用仓库旁的目录。

## 这不是什么

它不是合规、法律、医疗或金融结论。它只输出差异供人复核。
它不是模型，也不调用模型。

## 许可

Apache-2.0。
