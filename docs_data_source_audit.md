# fund-event-engine 数据源 / 证据源审计（v1）

目标：把项目从“研究辅助”往“可用于拍板决策的产品”推进。
核心原则：先做对数据源，再谈评分和报告。

## 一、全局判断

当前项目优点：
- 已有按基金类型分层的 sources 配置
- 已有 official / media / specialist / sentiment 分层
- 已有一批结构化 signal collector，可快速补变量覆盖
- 已引入 source feedback / prediction history / quality score

当前主要短板：
1. **部分关键来源不稳定**
   - Reuters Markets：401
   - World Gold Council Data：404
   - MacroMicro：404
   - 国家航天局：偶发 reset
   - Reddit / X / 社区类来源稳定性差
2. **部分基金类型对 proxy 依赖仍偏高**
   - 黄金
   - 债基
   - 宽基
3. **source 配置存在“有来源名，但不一定能稳定拿到有效 detail 内容”的情况**
4. **“主证据 / 辅证据 / 情绪补充”虽然逻辑上存在，但还没完全工程化成硬门槛**

## 二、按基金类型的证据要求

### 1. 黄金（002963）
核心变量：
- 金价
- 美元
- 实际利率
- ETF 流向
- 央行购金
- 避险需求

当前已有：
- Yahoo Finance API（价格 / 美元 / 利率 / proxy）
- SGE（交易所公告）
- Central Bank Gold Signal（结构化）
- Gold ETF Flow Signal（结构化）
- Gold Safe Haven Signal（结构化）
- Kitco query / Google News gold 查询

当前问题：
- WGC 直连页不可用，黄金长期核心变量缺一条硬链
- ETF 流向仍主要来自新闻聚合，缺更稳定的持仓/流量数据底座
- 央行购金仍偏新闻聚合，缺更稳定月度更新链

结论：
- **黄金当前已从“高 proxy”改到“中等可用”**
- 下一步优先补：ETF 持仓链、央行储备链、金交所更直接价格/库存线索

### 2. 信用债（217023 / 007951）
核心变量：
- 利率中枢
- 信用利差
- 违约 / 展期 / 风险缓释
- 资金面
- 净融资 / 发行取消
- 申赎压力

当前已有：
- Yahoo Finance API（利率 / credit spread proxy / redemption proxy）
- 中国人民银行（货币政策与流动性背景）
- Bond Credit Event Signal（结构化）
- Bond Liquidity Signal（结构化）

当前问题：
- 信用利差仍是海外 proxy 表达，离中国信用债市场还有距离
- 缺“发行取消 / 净融资 / 城投地产信用事件”的更本土 direct 证据
- 缺基金层申赎 / 久期 / 杠杆更直接线索

结论：
- **债基已从“不可拍板”推进到“中等可用”**
- 下一步优先补：中国信用债风险事件、净融资/发行、国内资金面直接信号

### 3. 稀土（011035）
核心变量：
- 配额政策
- 出口管制
- 氧化镨钕 / 重稀土价格
- 永磁下游需求
- 订单 / 排产 / 开工

当前已有：
- 工信部原材料工业司
- 上海有色网 query
- 中国稀土行业协会 query
- Fastmarkets query
- Rare Earth Policy / Price-Demand / Order 结构化信号

当前问题：
- query 型来源可用但受搜索结果波动影响
- 行业协会直连抓取弱，价格 / 指标数据稳定性还不够

结论：
- **稀土证据框架相对完整**
- 下一步优先补：更稳定的价格指数源与协会/公司公告直连

### 4. 电网（025832）
核心变量：
- 国网/南网招标
- 特高压核准
- 中标订单
- 电网投资强度
- 成本价格传导

当前已有：
- 国家能源局
- 上交所公告
- Google News 电网 query
- Power Grid Structured / Demand-Supply / Price 信号

当前问题：
- 国网/南网官方招标结果尚未形成专门 collector
- 上市公司订单公告仍较依赖泛公告和新闻

结论：
- **电网当前是最接近“能拍板”的主题之一**
- 下一步优先补：国网/南网招投标直连 collector

### 5. 卫星（024194）
核心变量：
- 发射
- 组网
- 牌照 / 频轨 / 标准
- 订单
- 商业化落地

当前已有：
- 国家航天局
- 36氪商业航天 query
- Satellite Structured / Order-Demand / Policy / Price 信号
- Yahoo satellite proxy

当前问题：
- 国家航天局稳定性一般
- 产业链直连公告较少，仍靠 query/媒体较多
- 订单和商业化落地的 direct 源还可以继续补

结论：
- **卫星方向框架较好，但官方源稳定性仍是风险点**
- 下一步优先补：更稳的航天官方/协会/企业订单信号源

### 6. 宽基（007028）
核心变量：
- 流动性
- 风险偏好
- 风格
- 宏观确认

当前已有：
- 中国人民银行
- 国家统计局
- Broad Equity Risk Signal
- Yahoo index / VIX / macro proxy

当前问题：
- 本质上仍较依赖 proxy
- 宽基天然更偏宏观型判断，难完全摆脱 proxy

结论：
- **宽基是“可参考，但难变成纯 direct 驱动”的类型**
- 下一步更适合强化“宏观确认链”，而不是追求过度 direct 化

## 三、全局数据源策略调整建议

### A. 来源分层进一步硬化
主证据（可入主结论）：
- authoritative_data
- top_tier_media 中的稳定来源
- 结构化 direct signal（基于公开可追溯数据）

辅证据（可增强信心，不单独拍板）：
- specialist_research
- query 型行业媒体

情绪补充（不得单独进主结论）：
- community_forum
- self_media

### B. 优先替换/降级的脆弱源
建议降级或仅作补充：
- Reuters Markets（401）
- World Gold Council Data（404）
- MacroMicro（404）
- Reddit/X/雪球类来源

### C. 优先新增 collector 的方向
1. 债基：中国信用事件 / 净融资 / 发行取消 / 资金面 direct collector
2. 黄金：ETF 持仓 / 央行储备更稳定 collector
3. 电网：国网/南网招投标直连 collector
4. 卫星：航天系统公告 / 企业订单直连 collector
5. 稀土：价格指数 / 协会数据 / 公司公告直连 collector

## 四、产品化门槛建议
未来要把“决策可用性=高”做成硬门槛：
- 至少 2 个独立来源
- 至少 1~2 条 direct 证据
- 关键变量覆盖率达到阈值
- source stability 不低于阈值
- 若核心变量缺失，则禁止给高可用性

## 五、接下来执行顺序（建议）
1. 债基本土 direct 证据链
2. 黄金 ETF / 央行购金稳定链
3. 电网招投标直连
4. 卫星官方 / 订单直连
5. 稀土价格/协会/公告直连

