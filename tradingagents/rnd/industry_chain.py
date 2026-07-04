from __future__ import annotations

from datetime import datetime

from .industry_intelligence import latest_industry_intelligence


PROJECT_REFERENCES = [
    {
        "name": "AICARDMAP",
        "url": "https://github.com/REDLIUSIKE/AICARDMAP",
        "takeaway": "AI 硬件基础设施产业链、环节库、公司索引、情报雷达、证据状态。",
        "license_note": "公开仓库为 showcase；All Rights Reserved，不复用其源码、截图或品牌资产。",
    },
    {
        "name": "stock-industry-chain",
        "url": "https://github.com/OwenZhangGC/stock-industry-chain",
        "takeaway": "交互式产业链小表格、公司资料卡、行情联动。",
    },
    {
        "name": "ChainKnowledgeGraph",
        "url": "https://github.com/liuhuanyong/ChainKnowledgeGraph",
        "takeaway": "公司、行业、产品、上下游产品关系的知识图谱 schema。",
    },
]


EVIDENCE_LEGEND = [
    {"status": "confirmed", "label": "已验证", "meaning": "公告、年报、招股书、官网产品页或多源高质量资料支持。"},
    {"status": "business_fit", "label": "业务匹配", "meaning": "公司能力与链条环节匹配，但客户关系或订单强度仍需核验。"},
    {"status": "needs_review", "label": "待核验", "meaning": "有线索价值，但缺少足够公开证据，不能当作确定关系使用。"},
]


AI_INFRA_TRACKS = [
    {
        "id": "compute",
        "title": "算力芯片",
        "summary": "GPU、AI ASIC、CPU、加速卡与软件生态决定训练和推理的供给上限。",
        "layers": {
            "upstream": ["先进制程", "HBM", "CoWoS/先进封装", "EDA/IP"],
            "bottlenecks": ["GPU", "AI ASIC", "CUDA/软件生态", "高带宽互联"],
            "integration": ["服务器整机", "集群调度", "液冷供电适配"],
            "demand": ["大模型训练", "推理集群", "云厂商 capex"],
        },
        "watch": ["海外芯片出口限制", "国产 AI ASIC 招标", "云厂商资本开支", "先进封装产能"],
    },
    {
        "id": "memory",
        "title": "存储与内存",
        "summary": "HBM、DRAM、NAND、主控和模组决定 AI 服务器的数据吞吐与成本曲线。",
        "layers": {
            "upstream": ["硅片", "电子特气", "湿电子化学品", "CMP 材料"],
            "bottlenecks": ["HBM", "HBM3E/HBM4", "DRAM", "NAND"],
            "integration": ["存储模组", "SSD/eSSD 主控", "服务器内存子系统"],
            "demand": ["AI 服务器", "企业级 SSD", "端侧 AI 设备"],
        },
        "watch": ["HBM 供需", "晶圆厂稼动率", "存储涨价周期", "材料国产替代认证"],
    },
    {
        "id": "networking",
        "title": "网络与光通信",
        "summary": "光模块、交换芯片、光器件和网络设备决定集群横向扩展效率。",
        "layers": {
            "upstream": ["InP/GaAs 材料", "激光器", "光芯片", "高速 PCB"],
            "bottlenecks": ["800G/1.6T 光模块", "交换芯片", "CPO", "RoCE/RDMA"],
            "integration": ["交换机", "光互联架构", "数据中心网络"],
            "demand": ["AI 集群扩容", "云厂商网络升级", "运营商骨干网"],
        },
        "watch": ["光模块订单", "交换机招标", "CPO 进展", "海外大客户 capex"],
    },
    {
        "id": "packaging",
        "title": "先进封装",
        "summary": "封装把芯片、HBM 和高速互联组装为可交付算力，是 AI 芯片扩产的硬约束之一。",
        "layers": {
            "upstream": ["载板", "封装材料", "键合设备", "测试探针"],
            "bottlenecks": ["CoWoS", "2.5D/3D 封装", "Chiplet", "封装良率"],
            "integration": ["OSAT", "晶圆厂封装线", "系统级封装"],
            "demand": ["GPU/HBM 组合", "高端 ASIC", "国产替代封装"],
        },
        "watch": ["CoWoS 扩产", "封测资本开支", "载板供需", "先进封装良率"],
    },
    {
        "id": "manufacturing",
        "title": "晶圆制造与设备",
        "summary": "制程、设备、材料和良率决定芯片能否稳定量产。",
        "layers": {
            "upstream": ["光刻胶", "电子气体", "靶材", "清洗/刻蚀材料"],
            "bottlenecks": ["刻蚀", "沉积", "清洗", "量测"],
            "integration": ["晶圆代工", "国产产线认证", "设备维护"],
            "demand": ["AI 芯片", "存储扩产", "功率/模拟芯片"],
        },
        "watch": ["设备国产化率", "材料认证进度", "晶圆厂稼动率", "资本开支周期"],
    },
    {
        "id": "testing",
        "title": "测试与良率",
        "summary": "测试机、分选机、探针台和良率分析决定高价值芯片能否稳定交付。",
        "layers": {
            "upstream": ["精密运动平台", "高速接口", "探针卡", "测试治具"],
            "bottlenecks": ["SoC 测试机", "存储测试机", "先进封装测试", "良率分析"],
            "integration": ["晶圆级测试", "封装成品测试", "可靠性验证"],
            "demand": ["GPU/AI ASIC", "HBM", "汽车芯片", "Chiplet"],
        },
        "watch": ["高端测试机验证", "先进封装良率", "存储测试需求", "国产设备导入"],
    },
    {
        "id": "materials",
        "title": "半导体材料",
        "summary": "高纯化学品、光刻胶、CMP、电子气体和封装材料共同决定制程稳定性。",
        "layers": {
            "upstream": ["高纯原料", "树脂与溶剂", "特种气体", "硅基材料"],
            "bottlenecks": ["光刻胶", "CMP 材料", "湿电子化学品", "先进封装材料"],
            "integration": ["晶圆厂认证", "批次稳定性", "本地供应保障"],
            "demand": ["先进制程", "成熟制程扩产", "存储复苏", "国产替代"],
        },
        "watch": ["客户认证进度", "高端品类收入", "晶圆厂稼动率", "原料价格与毛利率"],
    },
    {
        "id": "power_cooling",
        "title": "电力与散热",
        "summary": "AI 集群从芯片问题变成电力密度问题，电源、变压器、液冷和机房工程会决定部署速度。",
        "layers": {
            "upstream": ["磁性材料", "铜材", "制冷工质", "泵阀管路"],
            "bottlenecks": ["服务器电源", "液冷 CDU", "变压器", "高压直流"],
            "integration": ["数据中心供配电", "液冷机柜", "热管理系统"],
            "demand": ["高功率机柜", "海外数据中心", "智算中心建设"],
        },
        "watch": ["AI 服务器功耗", "液冷渗透率", "电源模块订单", "数据中心电力审批"],
    },
    {
        "id": "servers",
        "title": "服务器与数据中心",
        "summary": "整机、机柜、网络、供电和运维把底层零部件变成可出售的算力。",
        "layers": {
            "upstream": ["GPU/CPU", "内存", "高速 PCB", "电源与散热"],
            "bottlenecks": ["AI 服务器", "整机交付", "集群调优", "运维可靠性"],
            "integration": ["云厂商", "运营商", "政企智算中心"],
            "demand": ["模型训练", "推理服务", "行业私有化部署"],
        },
        "watch": ["AI 服务器中标", "整机毛利率", "应收账款", "云厂商采购周期"],
    },
    {
        "id": "software_apps",
        "title": "AI软件与应用",
        "summary": "模型、数据、云资源和行业工作流共同决定AI能力能否转化为可持续的软件收入。",
        "layers": {
            "upstream": ["基础模型", "云算力与推理服务", "行业数据", "开发工具链"],
            "bottlenecks": ["模型效果与成本", "数据治理", "产品分发", "商业化与续费"],
            "integration": ["办公与协同", "企业软件", "智能汽车与端侧", "垂直行业应用"],
            "demand": ["降本增效", "AI原生应用", "企业数字化", "端侧智能升级"],
        },
        "watch": ["ARR与续费率", "付费用户和席位", "推理成本", "订单与利润兑现"],
    },
]


PUBLIC_COMPANIES = [
    {"ticker": "688041.SH", "name": "海光信息", "role": "CPU / DCU", "tracks": ["compute"]},
    {"ticker": "688256.SH", "name": "寒武纪", "role": "AI 加速芯片", "tracks": ["compute"]},
    {"ticker": "688047.SH", "name": "龙芯中科", "role": "通用处理器", "tracks": ["compute"]},
    {"ticker": "688008.SH", "name": "澜起科技", "role": "内存接口芯片", "tracks": ["memory"]},
    {"ticker": "603986.SH", "name": "兆易创新", "role": "存储与控制芯片", "tracks": ["memory"]},
    {"ticker": "301308.SZ", "name": "江波龙", "role": "存储模组", "tracks": ["memory"]},
    {"ticker": "688525.SH", "name": "佰维存储", "role": "存储模组与封测", "tracks": ["memory", "packaging"]},
    {"ticker": "300308.SZ", "name": "中际旭创", "role": "高速光模块", "tracks": ["networking"]},
    {"ticker": "300502.SZ", "name": "新易盛", "role": "高速光模块", "tracks": ["networking"]},
    {"ticker": "300394.SZ", "name": "天孚通信", "role": "光器件", "tracks": ["networking"]},
    {"ticker": "002281.SZ", "name": "光迅科技", "role": "光芯片与光模块", "tracks": ["networking"]},
    {"ticker": "000938.SZ", "name": "紫光股份", "role": "交换机与算力网络", "tracks": ["networking", "servers"]},
    {"ticker": "600584.SH", "name": "长电科技", "role": "集成电路封测", "tracks": ["packaging"]},
    {"ticker": "002156.SZ", "name": "通富微电", "role": "集成电路封测", "tracks": ["packaging"]},
    {"ticker": "002185.SZ", "name": "华天科技", "role": "集成电路封测", "tracks": ["packaging"]},
    {"ticker": "688362.SH", "name": "甬矽电子", "role": "先进封装", "tracks": ["packaging"]},
    {"ticker": "002371.SZ", "name": "北方华创", "role": "刻蚀、沉积与清洗设备", "tracks": ["manufacturing"]},
    {"ticker": "688012.SH", "name": "中微公司", "role": "刻蚀与薄膜设备", "tracks": ["manufacturing"]},
    {"ticker": "688082.SH", "name": "盛美上海", "role": "清洗与电镀设备", "tracks": ["manufacturing"]},
    {"ticker": "688072.SH", "name": "拓荆科技", "role": "薄膜沉积设备", "tracks": ["manufacturing"]},
    {"ticker": "688120.SH", "name": "华海清科", "role": "CMP 设备", "tracks": ["manufacturing"]},
    {"ticker": "300604.SZ", "name": "长川科技", "role": "测试机与分选机", "tracks": ["testing"]},
    {"ticker": "688200.SH", "name": "华峰测控", "role": "半导体测试设备", "tracks": ["testing"]},
    {"ticker": "688627.SH", "name": "精智达", "role": "存储与显示测试", "tracks": ["testing"]},
    {"ticker": "688019.SH", "name": "安集科技", "role": "CMP 与功能性湿化学品", "tracks": ["materials"]},
    {"ticker": "300054.SZ", "name": "鼎龙股份", "role": "CMP 抛光垫与半导体材料", "tracks": ["materials"]},
    {"ticker": "002409.SZ", "name": "雅克科技", "role": "电子材料与前驱体", "tracks": ["materials"]},
    {"ticker": "603078.SH", "name": "江化微", "role": "湿电子化学品", "tracks": ["materials", "manufacturing"]},
    {"ticker": "300811.SZ", "name": "铂科新材", "role": "服务器电源磁性材料", "tracks": ["power_cooling"]},
    {"ticker": "002837.SZ", "name": "英维克", "role": "数据中心温控与液冷", "tracks": ["power_cooling"]},
    {"ticker": "301018.SZ", "name": "申菱环境", "role": "数据中心环境控制", "tracks": ["power_cooling"]},
    {"ticker": "000977.SZ", "name": "浪潮信息", "role": "AI 服务器", "tracks": ["servers"]},
    {"ticker": "603019.SH", "name": "中科曙光", "role": "服务器与算力基础设施", "tracks": ["servers"]},
    {"ticker": "601138.SH", "name": "工业富联", "role": "服务器制造与网络设备", "tracks": ["servers", "networking"]},
    {"ticker": "688111.SH", "name": "金山办公", "role": "办公软件与AI助手", "tracks": ["software_apps"]},
    {"ticker": "002230.SZ", "name": "科大讯飞", "role": "大模型与行业应用", "tracks": ["software_apps"]},
    {"ticker": "600588.SH", "name": "用友网络", "role": "企业软件与智能体", "tracks": ["software_apps"]},
    {"ticker": "600570.SH", "name": "恒生电子", "role": "金融科技软件", "tracks": ["software_apps"]},
    {"ticker": "002410.SZ", "name": "广联达", "role": "建筑数字化与AI应用", "tracks": ["software_apps"]},
    {"ticker": "300496.SZ", "name": "中科创达", "role": "端侧AI与智能汽车软件", "tracks": ["software_apps", "compute"]},
]


TECHNOLOGY_ROUTES = [
    {"title": "训练算力扩展", "path": ["GPU / AI ASIC", "HBM", "先进封装", "高速互联", "集群调度"], "focus": "系统交付能力，而非单卡峰值"},
    {"title": "推理成本下降", "path": ["模型压缩", "推理芯片", "内存带宽", "端云协同", "软件生态"], "focus": "每 token 成本与能效"},
    {"title": "光互联升级", "path": ["光芯片", "高速光模块", "800G / 1.6T", "CPO", "全光网络"], "focus": "带宽、功耗与量产良率"},
    {"title": "高密度机柜", "path": ["高功率电源", "磁性器件", "液冷 CDU", "供配电", "园区电力"], "focus": "单柜功率与部署速度"},
    {"title": "国产制造闭环", "path": ["设备", "材料", "晶圆制造", "封装", "测试与良率"], "focus": "认证、稳定量产与成本曲线"},
    {"title": "AI应用商业化", "path": ["基础模型", "推理服务", "应用产品", "行业工作流", "订阅与续费"], "focus": "真实使用、付费和利润兑现"},
]


LEARNING_PATHS = [
    {"level": "01", "title": "先理解一台 AI 服务器", "steps": ["芯片提供计算", "HBM 提供带宽", "网络连接集群", "电源与液冷保障运行"]},
    {"level": "02", "title": "再理解供给瓶颈", "steps": ["找到扩产最慢环节", "区分产能和良率", "核对客户认证", "观察价格与交付周期"]},
    {"level": "03", "title": "最后映射到 A 股公司", "steps": ["确认主营产品", "判断收入相关度", "核验订单和客户", "跟踪估值与交易拥挤度"]},
]


UPDATE_LOG = [
    {"date": "2026-07-01", "title": "补齐九条 AI 基础设施产业链", "detail": "新增测试与良率、半导体材料，并扩展 A 股公司索引。"},
    {"date": "2026-07-01", "title": "建立证据分级", "detail": "公司能力匹配不再直接等同于客户或订单确认。"},
    {"date": "2026-06-29", "title": "接入产业链研究工作台", "detail": "支持链条、公司、技术路线和情报之间的交叉检索。"},
]


COMPANY_LINKS = {
    "300496.SZ": {
        "links": [
            {"track": "software_apps", "node": "端侧AI与智能汽车软件", "status": "business_fit"},
            {"track": "compute", "node": "软件生态", "status": "business_fit"},
        ],
    },
    "603078.SS": {
        "links": [
            {"track": "manufacturing", "node": "湿电子化学品", "status": "business_fit"},
            {"track": "materials", "node": "湿电子化学品", "status": "business_fit"},
        ],
    },
    "300811.SZ": {
        "links": [
            {"track": "power_cooling", "node": "服务器电源磁性材料", "status": "business_fit"},
            {"track": "power_cooling", "node": "高频高功率电感", "status": "needs_review"},
        ],
    },
    "003022.SZ": {
        "links": [],
    },
    "000938.SZ": {
        "links": [
            {"track": "servers", "node": "AI 服务器与网络设备", "status": "business_fit"},
            {"track": "networking", "node": "交换机/数据中心网络", "status": "business_fit"},
        ],
    },
}


INTELLIGENCE_RADAR = [
    {
        "track": "compute",
        "title": "AI 芯片供给从单卡性能转向系统可交付能力",
        "impact": "需要同时看芯片、HBM、先进封装、服务器整机和软件生态，单一芯片指标不足以解释产业节奏。",
        "status": "business_fit",
        "source_type": "云厂商 capex / 芯片路线 / 服务器交付",
    },
    {
        "track": "memory",
        "title": "HBM 与先进存储仍是 AI 服务器吞吐瓶颈",
        "impact": "会抬高存储链条、材料认证和模组环节的重要性。",
        "status": "needs_review",
        "source_type": "行业新闻 / 公司公告 / 供应链跟踪",
    },
    {
        "track": "power_cooling",
        "title": "机柜功率密度提升推动电源与液冷链条重估",
        "impact": "需要跟踪磁性材料、电源模块、CDU、泵阀和数据中心工程。",
        "status": "business_fit",
        "source_type": "技术路线 / 数据中心建设 / 订单验证",
    },
    {
        "track": "networking",
        "title": "AI 集群扩容让 800G/1.6T 光互联成为关键变量",
        "impact": "光模块、交换机、高速 PCB 和光器件需要从订单和 capex 交叉验证。",
        "status": "business_fit",
        "source_type": "云厂商 capex / 光通信订单 / 产业新闻",
    },
    {
        "track": "manufacturing",
        "title": "国产半导体材料的核心是认证和批量稳定性",
        "impact": "江化微等材料链条不能只看国产替代叙事，要看客户认证和高端品类占比。",
        "status": "business_fit",
        "source_type": "年报 / 客户认证 / 招标线索",
    },
    {
        "track": "packaging",
        "title": "先进封装扩产要同时观察设备、材料与良率",
        "impact": "名义产能不等于可交付产能，封装良率和关键设备到位时间会决定实际供给。",
        "status": "business_fit",
        "source_type": "资本开支 / 设备交付 / 良率进展",
    },
    {
        "track": "testing",
        "title": "高算力芯片提高测试复杂度与单颗测试时长",
        "impact": "测试设备价值量和先进封装测试需求可能提升，但需要订单与验证进度支持。",
        "status": "needs_review",
        "source_type": "产品验证 / 封测扩产 / 公司公告",
    },
    {
        "track": "materials",
        "title": "材料国产替代进入高端品类和批次稳定性阶段",
        "impact": "后续判断重点从是否进入客户，转向高端收入占比、复购和毛利率。",
        "status": "business_fit",
        "source_type": "年报 / 认证进度 / 晶圆厂稼动率",
    },
    {
        "track": "servers",
        "title": "AI 服务器需求需要用交付、毛利率和回款交叉验证",
        "impact": "收入增长若伴随低毛利和应收上升，不能直接等同于利润质量改善。",
        "status": "business_fit",
        "source_type": "招标 / 交付 / 毛利率 / 应收账款",
    },
    {
        "track": "software_apps",
        "title": "AI应用交易热度上升，但需要从反弹转向收入验证",
        "impact": "软件板块若只有低位反弹而没有用户、续费、订单和利润上修，持续性通常弱于有基本面支撑的产业趋势。",
        "status": "needs_review",
        "source_type": "相对强弱 / 成交扩散 / 订单 / ARR与续费",
    },
]


CHAIN_LIBRARY = {
    "300496.SZ": {
        "anchor": "AI 终端操作系统与智能汽车软件",
        "first_principle": "软件公司的产业链价值来自终端出货、芯片平台适配、车厂定点和高毛利软件/IP 复用率，而不是单纯 AI 叙事。",
        "watch_signals": ["高通/英伟达生态新品", "新车型 SOP 节点", "智能座舱渗透率", "研发费用率和回款周期"],
        "risks": ["车厂降本压价", "项目制收入波动", "端侧 AI 商业化慢于预期", "海外客户交付不确定性"],
        "questions": ["新增定点中，软件 IP 授权占比是否提升？", "AI 终端业务是否形成可复用产品，而不是一次性项目？"],
    },
    "603078.SS": {
        "anchor": "半导体湿电子化学品",
        "first_principle": "湿电子化学品的核心不是“国产替代”四个字，而是纯度等级、客户认证、扩产良率、价格周期和下游晶圆厂稼动率的乘积。",
        "watch_signals": ["晶圆厂稼动率", "湿电子化学品招标", "半导体材料国产替代政策", "毛利率同比变化"],
        "risks": ["低端化学品价格战", "认证周期长", "危化品安全环保约束", "扩产后利用率不足"],
        "questions": ["高端半导体品类收入占比是否真正提高？", "毛利率改善来自结构升级还是原料短期回落？"],
    },
    "300811.SZ": {
        "anchor": "金属软磁粉芯与 AI 电源",
        "first_principle": "磁性材料的投资逻辑取决于电源密度提升带来的单机价值量、粉末冶金工艺壁垒、客户导入节奏和产能成本曲线。",
        "watch_signals": ["AI 服务器出货", "电源模块方案升级", "光伏逆变器库存", "金属粉末价格"],
        "risks": ["AI 订单验证不及预期", "光伏需求拖累", "产能扩张导致折旧压力", "客户集中度"],
        "questions": ["AI 电源相关收入是否已有可验证客户和订单？", "高端产品毛利是否能抵消光伏周期压力？"],
    },
    "003022.SZ": {
        "anchor": "EVA/POE 与新材料平台",
        "first_principle": "联泓新科的核心逻辑是EVA/POE等化工新材料的装置成本、产品价差、下游周期和新品商业化；当前缺少把它直接归入AI基础设施主链的充分证据。",
        "watch_signals": ["EVA 价格与库存", "光伏组件排产", "煤化工成本", "POE/高端新材料进展"],
        "risks": ["光伏产业链过剩", "EVA 价差收缩", "装置检修或安全环保", "新品进度低于预期"],
        "questions": ["利润弹性来自 EVA 周期修复还是新品结构变化？", "新项目资本开支对现金流压力多大？", "是否存在可量化的AI基础设施业务暴露，而非主题联想？"],
    },
    "000938.SZ": {
        "anchor": "数字基础设施、网络设备与算力集成",
        "first_principle": "ICT 集成公司的价值取决于算力需求、网络设备份额、新华三产品竞争力、渠道回款和低毛利集成业务占比。",
        "watch_signals": ["云厂商 capex", "AI 服务器招标", "交换机/路由器份额", "新华三利润率"],
        "risks": ["低毛利集成拖累", "AI 服务器供应约束", "政企业务回款慢", "竞争压价"],
        "questions": ["AI 服务器收入增长是否改善利润，而非稀释毛利？", "新华三网络设备份额是否稳定提升？"],
    },
}


def build_industry_chain_brief(universe: list[dict]) -> dict:
    chains = []
    company_index = []
    track_titles = {track["id"]: track["title"] for track in AI_INFRA_TRACKS}
    for item in universe:
        ticker = str(item.get("ticker", "")).upper()
        chain = CHAIN_LIBRARY.get(ticker, {})
        links = COMPANY_LINKS.get(ticker, {}).get("links", [])
        company_index.append(
            {
                "ticker": ticker,
                "name": item.get("name", ticker),
                "theme": item.get("theme", ""),
                "pool": item.get("pool", ""),
                "links": [
                    {
                        **link,
                        "track_title": track_titles.get(link.get("track"), link.get("track", "")),
                    }
                    for link in links
                ],
                **chain,
            }
        )
        if chain:
            chains.append(
                {
                    "ticker": ticker,
                    "name": item.get("name", ticker),
                    "theme": item.get("theme", ""),
                    "pool": item.get("pool", ""),
                    **chain,
                    "map": [
                        {
                            **link,
                            "track_title": track_titles.get(link.get("track"), link.get("track", "")),
                        }
                        for link in links
                    ],
                }
            )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": {
            "name": "AI 基础设施产业链地图",
            "summary": "先看链条环节和瓶颈，再把公司放回产业位置，并用证据状态区分确认关系、业务匹配和待核验线索。",
        },
        "references": PROJECT_REFERENCES,
        "evidence_legend": EVIDENCE_LEGEND,
        "tracks": AI_INFRA_TRACKS,
        "public_companies": PUBLIC_COMPANIES,
        "technology_routes": TECHNOLOGY_ROUTES,
        "learning_path_cards": LEARNING_PATHS,
        "update_log": UPDATE_LOG,
        "daily_intelligence": latest_industry_intelligence(),
        "company_index": company_index,
        "radar": INTELLIGENCE_RADAR,
        "chains": chains,
        "learning_paths": [
            "先从算力需求出发，看芯片、HBM、网络、电力和散热如何共同约束集群扩张。",
            "每个环节先分清：上游输入、核心瓶颈、系统集成、需求拉动。",
            "对公司只做位置映射和证据标注，不把业务匹配直接等同于订单确认。",
        ],
    }
