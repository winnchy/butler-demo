"""
mock_backend 全局配置：常量、关键词表、模板池、工具函数
所有模拟数据基于北京真实地理/季节/交通特征
"""

import random
import math
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any

# ============================================================
# 地理范围：北京
# ============================================================
BJ_LON_MIN, BJ_LON_MAX = 116.1, 116.8
BJ_LAT_MIN, BJ_LAT_MAX = 39.6, 40.2

# ============================================================
# 菜系关键词匹配（最长匹配优先 → typecode 兜底）
# 注意：麻辣烫/冒菜 → 快餐，不是火锅
# ============================================================
CUISINE_KEYWORDS: List[Tuple[str, str, str]] = [
    # (正则模式, 菜系大类, 子菜系)
    # --- 火锅（不含麻辣烫/冒菜/麻辣拌）---
    (r"火锅|涮肉|涮羊肉|串串香|串串", "火锅", "川渝火锅"),
    (r"打边炉|港式火锅|牛肉火锅|潮汕牛肉", "火锅", "粤式火锅"),
    (r"铜锅|老北京涮肉|羊蝎子|阳坊", "火锅", "老北京涮肉"),
    # --- 快餐/简餐 ---
    (r"麻辣烫|冒菜|麻辣拌|麻辣香锅", "快餐/简餐", "麻辣烫"),
    (r"快餐|盒饭|盖饭|盖浇|木桶饭|煲仔饭", "快餐/简餐", "中式快餐"),
    (r"麦当劳|肯德基|汉堡王|德克士|subway|赛百味", "快餐/简餐", "西式快餐"),
    (r"沙县|黄焖鸡|兰州拉面|牛肉面|米线|米粉|螺蛳粉", "快餐/简餐", "地方小吃"),
    # --- 粤菜/港式 ---
    (r"粤菜|粤港|茶餐厅|港式|烧腊|烧鹅|叉烧|煲仔|虾饺|肠粉", "粤菜", "港式茶餐厅"),
    (r"潮汕|潮州|打冷|卤水", "粤菜", "潮汕菜"),
    (r"顺德|客家", "粤菜", "客家菜"),
    # --- 川菜 ---
    (r"川菜|川味|水煮|钵钵鸡|担担面|回锅肉|宫保|麻婆", "川菜", "经典川菜"),
    (r"江湖菜|自贡|盐帮", "川菜", "江湖菜"),
    # --- 日料 ---
    (r"日料|日本|居酒屋|寿司|刺身|拉面|铁板|烧鸟|鳗鱼|天妇罗|味噌", "日料", "综合日料"),
    (r"omakase|怀石|割烹", "日料", "高端日料"),
    # --- 韩餐 ---
    (r"韩式|韩国|韩餐|拌饭|炸鸡|部队锅|大酱汤|参鸡汤|泡菜锅", "韩餐", "经典韩餐"),
    (r"烤肉|韩式烤肉|炭火烤肉", "韩餐", "韩式烤肉"),
    # --- 西餐 ---
    (r"西餐|牛排|意面|意大利|法式|法餐|bistro|fine.?dining", "西餐", "欧陆西餐"),
    (r"西班牙|tapas|海鲜饭", "西餐", "西班牙菜"),
    # --- 东南亚 ---
    (r"东南亚|泰国|泰式|冬阴功|越南|越南粉|pho|印度|咖喱", "东南亚菜", "综合东南亚"),
    (r"新加坡|肉骨茶|叻沙", "东南亚菜", "南洋风味"),
    # --- 京菜 ---
    (r"烤鸭|北京菜|北京烤鸭|京味|宫廷|炸酱面|豆汁|卤煮|炒肝|爆肚", "京菜", "老北京风味"),
    # --- 西北/东北 ---
    (r"西北|新疆|大盘鸡|羊肉串|拉条子|馕", "西北菜", "新疆风味"),
    (r"东北|铁锅炖|锅包肉|杀猪菜|酸菜白肉", "东北菜", "东北家常"),
    (r"清真|回民|牛街|羊肉泡馍|biangbiang", "清真", "清真风味"),
    # --- 海鲜 ---
    (r"海鲜|蟹|龙虾|鱼生|海钓|渔港|蒸汽海鲜", "海鲜", "综合海鲜"),
    # --- 烧烤 ---
    (r"烧烤|烤串|烤肉串|BBQ|炭烤|电烤|羊板筋|烤羊", "烧烤", "中式烧烤"),
    # --- 自助 ---
    (r"自助|任食|放题|海鲜自助|烤肉自助", "自助餐", "综合自助"),
    # --- 饮品 ---
    (r"咖啡|拿铁|美式|手冲|精品咖啡|espresso|cafe|café", "咖啡厅", "精品咖啡"),
    (r"星巴克|瑞幸|costa|manner|seesaw|tims", "咖啡厅", "连锁咖啡"),
    (r"茶馆|茶楼|茶空间|茶室|喝茶|品茶|茶社", "茶馆", "中式茶馆"),
    (r"奶茶|果茶|柠檬茶|喜茶|奈雪|蜜雪|茶颜|霸王茶姬", "饮品", "新茶饮"),
    (r"酒吧|酒馆|pub|精酿|cocktail|鸡尾酒|威士忌|whisky|bar", "酒吧", "综合酒吧"),
    # --- 甜品/烘焙 ---
    (r"甜品|蛋糕|面包|烘焙|patisserie|pastry|泡芙|蛋挞|提拉米苏", "甜品/烘焙", "综合甜品"),
    # --- 农家/地方 ---
    (r"豆腐宴|农家|土菜|柴火|灶台|铁锅", "农家菜", "农家风味"),
    (r"湘菜|湘|剁椒|腊肉", "湘菜", "湖南风味"),
    (r"云南|过桥米线|菌子|汽锅", "云南菜", "云南风味"),
    # --- 酒店餐饮 ---
    (r"饭店|宾馆|酒店|大饭店", "酒店餐饮", "酒店附属"),
]
# 已编译的正则版本
CUISINE_KEYWORDS_COMPILED = [(re.compile(p, re.IGNORECASE), cu, sub) for p, cu, sub in CUISINE_KEYWORDS]

# ============================================================
# 菜系 → 营业时间（差异化）
# ============================================================
BUSINESS_HOURS_BY_CUISINE = {
    "火锅":          {"weekday": "11:00-23:00", "weekend": "11:00-23:30", "break_time": "14:30-17:00"},
    "快餐/简餐":     {"weekday": "10:00-22:00", "weekend": "10:00-22:30", "break_time": None},
    "粤菜":          {"weekday": "11:00-22:00", "weekend": "10:00-22:30", "break_time": "14:30-17:00"},
    "川菜":          {"weekday": "10:30-22:30", "weekend": "10:00-23:00", "break_time": None},
    "日料":          {"weekday": "11:30-14:00,17:00-22:00", "weekend": "11:00-22:00", "break_time": "14:00-17:00"},
    "韩餐":          {"weekday": "11:00-22:00", "weekend": "11:00-22:30", "break_time": None},
    "西餐":          {"weekday": "11:00-22:00", "weekend": "10:00-23:00", "break_time": None},
    "东南亚菜":      {"weekday": "11:00-22:00", "weekend": "11:00-22:30", "break_time": None},
    "京菜":          {"weekday": "11:00-21:30", "weekend": "10:30-22:00", "break_time": "14:30-17:00"},
    "清真":          {"weekday": "10:00-22:00", "weekend": "10:00-22:30", "break_time": None},
    "烧烤":          {"weekday": "16:00-02:00", "weekend": "15:00-03:00", "break_time": None},
    "海鲜":          {"weekday": "11:00-22:00", "weekend": "10:30-22:30", "break_time": None},
    "自助餐":        {"weekday": "11:00-14:00,17:00-21:30", "weekend": "11:00-21:30", "break_time": "14:00-17:00"},
    "咖啡厅":        {"weekday": "08:00-22:00", "weekend": "08:30-23:00", "break_time": None},
    "茶馆":          {"weekday": "09:00-22:00", "weekend": "09:00-23:00", "break_time": None},
    "饮品":          {"weekday": "10:00-22:00", "weekend": "10:00-22:30", "break_time": None},
    "酒吧":          {"weekday": "18:00-02:00", "weekend": "17:00-03:00", "break_time": None},
    "甜品/烘焙":     {"weekday": "09:00-21:00", "weekend": "09:00-22:00", "break_time": None},
    "农家菜":        {"weekday": "10:00-21:00", "weekend": "10:00-21:30", "break_time": None},
    "西北菜":        {"weekday": "10:00-22:00", "weekend": "10:00-22:30", "break_time": None},
    "东北菜":        {"weekday": "10:00-22:00", "weekend": "10:00-22:30", "break_time": None},
    "湘菜":          {"weekday": "10:30-22:30", "weekend": "10:00-23:00", "break_time": None},
    "云南菜":        {"weekday": "11:00-22:00", "weekend": "10:30-22:30", "break_time": None},
    "酒店餐饮":      {"weekday": "06:30-10:00,11:30-14:00,17:30-22:00", "weekend": "06:30-10:30,11:30-14:30,17:30-22:30", "break_time": "10:00-11:30,14:00-17:30"},
}

# ============================================================
# 菜系 → 菜系对口评价模板池
# ============================================================
CUISINE_REVIEW_TEMPLATES = {
    "火锅": {
        "pos": [
            "毛肚七上八下刚好脆嫩，必点！", "锅底够味，煮到后面也不会发苦",
            "蘸料自助区选择多，麻酱是现磨的", "鸭血新鲜，入口即化",
            "肥牛卷纹理漂亮，不是拼接肉", "服务周到，主动帮忙控制火候",
            "红糖糍粑外酥里糯，解辣必备",
        ],
        "neg": [
            "锅底越煮越咸，中途加了好几次水", "肥牛卷切得太薄，一煮就碎",
            "麻酱调得太稀，不够香浓", "排队太久但味道一般，性价比不高",
        ],
    },
    "粤菜": {
        "pos": [
            "虾饺皮薄馅大，虾仁弹牙", "煲仔饭锅巴焦香，腊味选得好",
            "白切鸡皮脆肉嫩，姜葱蘸料是灵魂", "炖汤火候足，料也很扎实",
            "叉烧肥瘦相间，蜜汁入味", "环境雅致，适合慢慢吃",
        ],
        "neg": [
            "点心不是现做的，应该是冷冻复热", "叉烧偏甜腻，吃两块就腻了",
            "上菜间隔太久，吃完一道干等十几分钟", "茶位费不便宜但茶叶品质一般",
        ],
    },
    "川菜": {
        "pos": [
            "水煮鱼麻辣鲜香，鱼肉嫩滑", "宫保鸡丁荔枝味调得好，正宗",
            "麻婆豆腐花椒味够劲，下饭神器", "分量实在，性价比很高",
            "担担面味道还原了成都街头的水平",
        ],
        "neg": [
            "辣味是工业辣，不是辣椒的香", "太油了，每道菜都飘着一层油",
            "花椒品质不好，麻味发苦",
        ],
    },
    "日料": {
        "pos": [
            "刺身新鲜，切功不错", "寿司米酸度和温度刚好",
            "烤鳗鱼酱汁浓郁，肉质肥美", "环境是日式原木风，很舒服",
            "天妇罗炸得酥脆不油腻",
        ],
        "neg": [
            "刺身解冻没处理好，有冰渣感", "寿司米饭捏得太紧，口感偏硬",
            "价格偏贵但分量太少，没吃饱", "拉面汤底不够浓郁，偏淡",
        ],
    },
    "烧烤": {
        "pos": [
            "羊肉串肥瘦相间，炭火味十足", "烤茄子蒜蓉满满的，太香了",
            "烤鸡翅外焦里嫩，腌料入味", "大排档氛围，夏天撸串太爽了",
            "板筋烤得刚好，有嚼劲又不硬",
        ],
        "neg": [
            "烤得太咸了，吃完狂喝水", "上串速度太慢，等得人心急",
            "环境油烟大，吃完一身味", "肉串偏小，性价比一般",
        ],
    },
}

# 通用评语（菜系没有专属模板时使用）
DEFAULT_REVIEW_POS = [
    "味道不错，下次还会来", "环境舒适，服务热情",
    "性价比高，推荐", "菜品精致，值得一试",
    "体验挺好的，会推荐给朋友",
]
DEFAULT_REVIEW_NEG = [
    "上菜速度有待提高", "环境一般，有点吵",
    "价格偏高，性价比一般", "服务态度需改进",
]

# ============================================================
# 餐厅 → 环境氛围
# ============================================================
ATMOSPHERE_STYLES = ["现代简约", "中式古典", "日式禅意", "工业风", "北欧清新", "港式怀旧", "东南亚风情", "美式复古", "韩式温馨", "田园风"]
NOISE_LEVELS = ["安静", "适中", "较热闹", "非常热闹"]
SUITABLE_FOR = ["朋友聚餐", "家庭聚会", "情侣约会", "商务宴请", "一人食", "闺蜜下午茶", "同事拼单", "带娃出行"]
LIGHTING_TYPES = ["明亮", "暖黄", "暗调氛围灯", "自然光"]
HIGHLIGHT_FEATURES = ["靠窗景观位", "有背景音乐", "绿植环绕", "有吧台", "榻榻米包间", "露台", "投影幕布", "开放式厨房", "有壁炉"]

# 氛围 → 菜系关联
ATMOSPHERE_BY_CUISINE = {
    "火锅":  ["中式古典", "港式怀旧", "现代简约"],
    "粤菜":  ["港式怀旧", "中式古典", "现代简约"],
    "川菜":  ["中式古典", "工业风", "现代简约"],
    "日料":  ["日式禅意", "现代简约", "东南亚风情"],
    "韩餐":  ["韩式温馨", "现代简约", "工业风"],
    "西餐":  ["美式复古", "北欧清新", "现代简约"],
    "东南亚菜": ["东南亚风情", "现代简约", "田园风"],
    "京菜":  ["中式古典", "现代简约"],
    "烧烤":  ["工业风", "港式怀旧", "现代简约"],
    "咖啡厅": ["北欧清新", "现代简约", "工业风"],
    "茶馆":  ["中式古典", "日式禅意"],
    "酒吧":  ["工业风", "美式复古", "暗调氛围灯"],
}

# ============================================================
# 北京真实地铁线路数据
# 用于匹配种子数据中的 40 个地铁站 + 构建网络
# ============================================================
BEIJING_METRO_LINES = {
    "1号线/八通线": {
        "color": "#C23A30",
        "direction": "east-west",
        "stations_ordered": ["古城", "八角游乐园", "八宝山", "玉泉路", "五棵松", "万寿路",
            "公主坟", "军事博物馆", "木樨地", "南礼士路", "复兴门", "西单", "天安门西",
            "天安门东", "王府井", "东单", "建国门", "永安里", "国贸", "大望路", "四惠",
            "四惠东", "高碑店", "传媒大学", "双桥", "管庄", "八里桥", "通州北苑", "果园",
            "九棵树", "梨园", "临河里", "土桥", "花庄", "环球度假区"],
    },
    "2号线": {
        "color": "#004B87",
        "direction": "loop",
        "stations_ordered": ["西直门", "积水潭", "鼓楼大街", "安定门", "雍和宫", "东直门",
            "东四十条", "朝阳门", "建国门", "北京站", "崇文门", "前门", "和平门",
            "宣武门", "长椿街", "复兴门", "阜成门", "车公庄"],
    },
    "4号线/大兴线": {
        "color": "#008C95",
        "direction": "north-south",
        "stations_ordered": ["安河桥北", "北宫门", "西苑", "圆明园", "北京大学东门",
            "中关村", "海淀黄庄", "人民大学", "魏公村", "国家图书馆", "动物园",
            "西直门", "新街口", "平安里", "西四", "灵境胡同", "西单", "宣武门",
            "菜市口", "陶然亭", "北京南站", "马家堡", "角门西", "公益西桥", "新宫",
            "西红门", "高米店北", "高米店南", "枣园", "清源路", "黄村西大街",
            "黄村火车站", "义和庄", "生物医药基地", "天宫院"],
    },
    "5号线": {
        "color": "#AA0061",
        "direction": "north-south",
        "stations_ordered": ["天通苑北", "天通苑", "天通苑南", "立水桥", "立水桥南",
            "北苑路北", "大屯路东", "惠新西街北口", "惠新西街南口", "和平西桥",
            "和平里北街", "雍和宫", "北新桥", "张自忠路", "东四", "灯市口", "东单",
            "崇文门", "磁器口", "天坛东门", "蒲黄榆", "刘家窑", "宋家庄"],
    },
    "6号线": {
        "color": "#B58500",
        "direction": "east-west",
        "stations_ordered": ["金安桥", "苹果园", "杨庄", "西黄村", "廖公庄", "田村",
            "海淀五路居", "慈寿寺", "花园桥", "白石桥南", "车公庄西", "车公庄",
            "平安里", "北海北", "南锣鼓巷", "东四", "朝阳门", "东大桥", "呼家楼",
            "金台路", "十里堡", "青年路", "褡裢坡", "黄渠", "常营", "草房",
            "物资学院路", "通州北关", "通运门", "北运河西", "北运河东", "郝家府",
            "东夏园", "潞城"],
    },
    "7号线": {
        "color": "#FFC56E",
        "direction": "east-west",
        "stations_ordered": ["北京西站", "湾子", "达官营", "广安门内", "菜市口",
            "虎坊桥", "珠市口", "桥湾", "磁器口", "广渠门内", "广渠门外", "双井",
            "九龙山", "大郊亭", "百子湾", "化工", "南楼梓庄", "欢乐谷景区", "垡头",
            "双合", "焦化厂", "黄厂", "郎辛庄", "黑庄户", "万盛西", "万盛东",
            "群芳", "高楼金", "花庄", "环球度假区"],
    },
    "8号线": {
        "color": "#009B77",
        "direction": "north-south",
        "stations_ordered": ["朱辛庄", "育知路", "平西府", "回龙观东大街", "霍营",
            "育新", "西小口", "永泰庄", "林萃桥", "森林公园南门", "奥林匹克公园",
            "奥体中心", "北土城", "安华桥", "安德里北街", "鼓楼大街", "什刹海",
            "南锣鼓巷", "中国美术馆", "金鱼胡同", "王府井", "前门", "珠市口",
            "天桥", "永定门外", "木樨园", "海户屯", "大红门南", "和义", "东高地",
            "火箭万源", "五福堂", "德茂", "瀛海"],
    },
    "9号线": {
        "color": "#97D700",
        "direction": "north-south",
        "stations_ordered": ["国家图书馆", "白石桥南", "白堆子", "军事博物馆",
            "北京西站", "六里桥东", "六里桥", "七里庄", "丰台东大街", "丰台南路",
            "科怡路", "丰台科技园", "郭公庄"],
    },
    "10号线": {
        "color": "#0092BC",
        "direction": "loop",
        "stations_ordered": ["巴沟", "车道沟", "长春桥", "火器营", "慈寿寺", "西钓鱼台",
            "公主坟", "莲花桥", "六里桥", "西局", "泥洼", "丰台站", "首经贸",
            "纪家庙", "草桥", "角门西", "角门东", "大红门", "石榴庄", "宋家庄",
            "成寿寺", "分钟寺", "十里河", "潘家园", "劲松", "双井", "国贸",
            "金台夕照", "呼家楼", "团结湖", "农业展览馆", "亮马桥", "三元桥",
            "太阳宫", "芍药居", "惠新西街南口", "安贞门", "北土城", "健德门",
            "牡丹园", "西土城", "知春路", "知春里", "海淀黄庄", "苏州街"],
    },
    "13号线": {
        "color": "#F4DA40",
        "direction": "north-loop",
        "stations_ordered": ["西直门", "大钟寺", "知春路", "五道口", "上地",
            "清河站", "西二旗", "龙泽", "回龙观", "霍营", "立水桥", "北苑",
            "望京西", "芍药居", "光熙门", "柳芳", "东直门"],
    },
    "14号线": {
        "color": "#CA9A8E",
        "direction": "east-west-north",
        "stations_ordered": ["张郭庄", "园博园", "大瓦窑", "郭庄子", "大井", "七里庄",
            "西局", "东管头", "丽泽商务区", "菜户营", "西铁营", "景风门",
            "北京南站", "陶然桥", "永定门外", "景泰", "蒲黄榆", "方庄",
            "十里河", "北工大西门", "平乐园", "九龙山", "大望路", "红庙",
            "金台路", "朝阳公园", "枣营", "东风北桥", "将台", "高家园",
            "望京南", "阜通", "望京", "东湖渠", "来广营", "善各庄"],
    },
    "15号线": {
        "color": "#653279",
        "direction": "east-west",
        "stations_ordered": ["清华东路西口", "六道口", "北沙滩", "奥林匹克公园",
            "安立路", "大屯路东", "关庄", "望京西", "望京", "望京东", "崔各庄",
            "马泉营", "孙河", "国展", "花梨坎", "后沙峪", "南法信", "石门",
            "顺义", "俸伯"],
    },
    "16号线": {
        "color": "#6BA539",
        "direction": "north-south",
        "stations_ordered": ["北安河", "温阳路", "稻香湖路", "屯佃", "永丰",
            "永丰南", "西北旺", "马连洼", "农大南路", "西苑", "万泉河桥",
            "苏州街", "苏州桥", "万寿寺", "国家图书馆", "二里沟", "甘家口",
            "玉渊潭东门", "木樨地", "达官营", "红莲南路", "丽泽商务区",
            "东管头南", "丰台站", "丰台南路", "富丰桥", "看丹", "榆树庄"],
    },
    "17号线": {
        "color": "#00B2A9",
        "direction": "north-south",
        "stations_ordered": ["未来科学城北", "未来科学城", "天通苑东", "清河营",
            "勇士营", "望京西", "太阳宫", "西坝河", "左家庄", "工人体育场",
            "东大桥", "永安里", "广渠门外", "潘家园西", "十里河", "十八里店",
            "北神树", "次渠北", "次渠", "嘉会湖"],
    },
    "亦庄线": {
        "color": "#E40077",
        "direction": "north-south",
        "stations_ordered": ["宋家庄", "肖村", "小红门", "旧宫", "亦庄桥", "亦庄文化园",
            "万源街", "荣京东街", "荣昌东街", "同济南路", "经海路", "次渠南",
            "次渠", "亦庄火车站"],
    },
    "房山线": {
        "color": "#D86018",
        "direction": "east-west",
        "stations_ordered": ["东管头南", "花乡东桥", "白盆窑", "郭公庄", "大葆台",
            "稻田", "长阳", "篱笆房", "广阳城", "良乡大学城北", "良乡大学城",
            "良乡大学城西", "良乡南关", "苏庄", "阎村东"],
    },
    "昌平线": {
        "color": "#DE82B2",
        "direction": "north-south",
        "stations_ordered": ["西二旗", "生命科学园", "朱辛庄", "巩华城", "沙河",
            "沙河高教园", "南邵", "北邵洼", "昌平东关", "昌平", "十三陵景区",
            "昌平西山口"],
    },
    "机场线": {
        "color": "#A192B2",
        "direction": "north-loop",
        "stations_ordered": ["东直门", "三元桥", "T2航站楼", "T3航站楼"],
    },
    "S1线": {
        "color": "#A45A2A",
        "direction": "east-west",
        "stations_ordered": ["苹果园", "金安桥", "四道桥", "桥户营", "上岸", "栗园庄",
            "小园", "石厂"],
    },
    "西郊线": {
        "color": "#D0006F",
        "direction": "east-west",
        "stations_ordered": ["巴沟", "颐和园西门", "茶棚", "万安", "国家植物园", "香山"],
    },
    "19号线": {
        "color": "#D2A6A0",
        "direction": "north-south",
        "stations_ordered": ["牡丹园", "北太平庄", "积水潭", "平安里", "太平桥",
            "牛街", "景风门", "草桥", "新发地", "新宫"],
    },
}

# 换乘站集合（出现在多条线路的车站）
TRANSFER_STATIONS = set()
line_station_count = {}
for line, info in BEIJING_METRO_LINES.items():
    for st in info["stations_ordered"]:
        line_station_count[st] = line_station_count.get(st, 0) + 1
TRANSFER_STATIONS = {st for st, count in line_station_count.items() if count >= 2}

# ============================================================
# 商圈 → 消费档次推断
# ============================================================
PREMIUM_BIZ_AREAS = {"国贸", "金融街", "CBD", "燕莎", "三里屯", "亮马桥", "王府井", "西单",
                        "中关村", "望京", "蓝色港湾", "东单", "建国门", "朝阳门", "大望路",
                        "东直门", "复兴门", "丽都", "使馆区", "什刹海", "鼓楼", "798", "芳草地"}
MID_BIZ_AREAS = {"双井", "常营", "五道口", "朝阳大悦城", "东直门", "崇文门", "方庄", "上地", "西红门", "立水桥"}
BUDGET_BIZ_AREAS = {"通州", "昌平", "大兴", "房山", "顺义", "石景山", "门头沟", "怀柔", "密云", "延庆", "平谷", "柳沟", "南磨房"}

def infer_price_level(name: str, biz_area: str, seed_price: Optional[float]) -> Tuple[int, str]:
    """推断人均消费和档次标签，返回 (avg_price, level)"""
    if seed_price and seed_price > 0:
        # 用种子真实价格
        if seed_price >= 300:
            return int(seed_price), "高端"
        elif seed_price >= 100:
            return int(seed_price), "中高端"
        elif seed_price >= 50:
            return int(seed_price), "中端"
        else:
            return int(seed_price), "经济实惠"
    # 无真实价格 → 基于店名和商圈推断
    biz_str = str(biz_area)
    if any(b in biz_str for b in PREMIUM_BIZ_AREAS):
        base = random.randint(120, 400)
        level = "中高端"
    elif any(b in biz_str for b in MID_BIZ_AREAS):
        base = random.randint(50, 180)
        level = "中端"
    else:
        base = random.randint(20, 100)
        level = "经济实惠"
    # 店名微调
    if any(w in name for w in ["大饭店", "贵宾楼", "昆仑", "中国大饭店", "国际饭店"]):
        base = max(base, random.randint(250, 600))
        level = "高端"
    elif any(w in name for w in ["饭店", "酒店", "酒楼", "公馆"]):
        base = int(base * random.uniform(1.5, 2.5))
        level = "高端" if base >= 300 else ("中高端" if base >= 150 else level)
    elif any(w in name for w in ["小馆", "小吃", "麻辣烫", "盖饭", "拉面", "包子"]):
        base = int(base * random.uniform(0.3, 0.6))
        level = "经济实惠"
    return base, level

# ============================================================
# 品牌/连锁 → 店名推断
# ============================================================
CHAIN_KEYWORDS = [
    "海底捞", "西贝", "呷哺呷哺", "肯德基", "麦当劳", "必胜客", "星巴克", "瑞幸",
    "喜茶", "奈雪", "蜜雪冰城", "太二", "湊湊", "巴奴", "全聚德", "便宜坊",
    "大董", "小大董", "大鸭梨", "金鼎轩", "紫光园", "南城香", "老乡鸡",
    "庆丰包子", "护国寺", "姚记", "陈记", "张记", "柳沟",
]
def detect_chain(name: str) -> Dict:
    """检测是否为连锁品牌"""
    # 有分店后缀的 → 连锁
    if re.search(r"\(.+店\)|（.+店）|[第]?\d+店", name):
        base_name = re.sub(r"\(.+店\)|（.+店）", "", name).strip()
        return {"is_chain": True, "chain_name": base_name, "is_local_specialty": False}
    # 知名连锁品牌
    for keyword in CHAIN_KEYWORDS:
        if keyword in name:
            return {"is_chain": True, "chain_name": keyword, "is_local_specialty": False}
    # 含"店"且名长 → 可能连锁
    if "店" in name and len(name) >= 5:
        return {"is_chain": True, "chain_name": name[:4], "is_local_specialty": False}
    # 地名+特色 → 本地独有
    if any(w in name for w in ["胡同", "大院", "巷", "村", "屯", "堡", "沟"]):
        return {"is_chain": False, "chain_name": None, "is_local_specialty": True}
    # 默认
    is_chain = random.random() < 0.2
    return {
        "is_chain": is_chain,
        "chain_name": name[:4] if is_chain else None,
        "is_local_specialty": not is_chain
    }

# ============================================================
# 交通 → 拥堵时段基准
# ============================================================
def congestion_by_hour(hour: int) -> float:
    """北京典型交通拥堵指数 0-1"""
    if 0 <= hour < 6:
        return 0.05
    elif 6 <= hour < 7:
        return 0.30
    elif 7 <= hour < 9:
        return 0.85
    elif 9 <= hour < 11:
        return 0.50
    elif 11 <= hour < 13:
        return 0.60
    elif 13 <= hour < 16:
        return 0.40
    elif 16 <= hour < 17:
        return 0.55
    elif 17 <= hour < 19:
        return 0.90
    elif 19 <= hour < 21:
        return 0.60
    elif 21 <= hour < 24:
        return 0.25
    return 0.1

# ============================================================
# 各类型 POI 素材池
# ============================================================

# 宠物服务
PET_SERVICE_TYPES = ["宠物医院", "宠物美容", "宠物寄养", "宠物用品店", "宠物乐园", "宠物训练"]
PET_SPECIES = ["犬", "猫", "兔子", "仓鼠", "龙猫", "鹦鹉", "乌龟", "蛇", "蜥蜴"]

# 医院
HOSPITAL_LEVELS = ["三级甲等", "三级乙等", "二级甲等", "二级乙等", "社区卫生服务中心"]
HOSPITAL_DEPARTMENTS = ["内科", "外科", "儿科", "妇产科", "骨科", "眼科", "口腔科", "皮肤科", "急诊科", "体检中心", "神经内科", "心血管内科"]

# 加油站
GAS_TYPES = ["92#", "95#", "98#", "0#柴油"]
GAS_PRICE_RANGE = {"92#": (7.5, 8.2), "95#": (8.0, 8.7), "98#": (9.0, 9.8), "0#柴油": (7.0, 7.6)}

# 酒店
HOTEL_STARS = ["五星级", "四星级", "三星级", "经济型", "精品民宿"]

# ============================================================
# 天气 → 季节特征（北京 5-6月）
# ============================================================
def get_seasonal_weather_base(month: int) -> Dict:
    """返回北京该月的天气基准"""
    if month in [12, 1, 2]:
        return {"temp_low": -8, "temp_high": 5, "humidity": 30, "rain_prob": 5, "condition": "晴"}
    elif month in [3, 4]:
        return {"temp_low": 5, "temp_high": 20, "humidity": 40, "rain_prob": 15, "condition": "多云"}
    elif month in [5, 6]:
        return {"temp_low": 16, "temp_high": 32, "humidity": 55, "rain_prob": 30, "condition": "晴"}
    elif month in [7, 8]:
        return {"temp_low": 23, "temp_high": 35, "humidity": 75, "rain_prob": 45, "condition": "多云"}
    else:  # 9, 10, 11
        return {"temp_low": 8, "temp_high": 22, "humidity": 45, "rain_prob": 20, "condition": "晴"}

# ============================================================
# 场景触发器预设
# ============================================================
SCENARIO_TRIGGERS = {
    "1": {  # 接待上级午餐
        "time_override": "11:30",
        "weather": {"condition": "晴", "current_temp": 28, "alerts": []},
        "restaurant_queues_override": True,
        "traffic": {"citywide_congestion": 0.55},
        "description": "小琴接待王总+深圳合作方午餐"
    },
    "2": {  # 逛街突遇暴雨
        "time_override": "14:30",
        "weather": {"condition": "暴雨", "current_temp": 24, "alerts": ["暴雨黄色预警"],
                    "hourly_rain": [("14:00", "中雨"), ("14:30", "暴雨"), ("15:00", "小雨")]},
        "traffic": {"citywide_congestion": 0.75},
        "description": "小琴和婆婆在蓝色港湾遇暴雨"
    },
    "7": {  # 乐乐凌晨发烧
        "time_override": "02:00",
        "weather": {"condition": "晴", "current_temp": 22, "alerts": []},
        "health_event": {"user": "parent", "type": "fever", "person": "乐乐",
                         "temp_curve": [(2, 38.5), (4, 38.2), (7, 37.8), (12, 37.2)]},
        "description": "乐乐凌晨发烧38.5°C"
    },
    "9": {  # 上海终面飞机延误
        "time_override": "08:00",
        "weather": {"condition": "雷暴", "current_temp": 26, "alerts": ["雷电橙色预警", "暴雨黄色预警"]},
        "flight_delay": {"flight_id": "CA1234", "route": "北京→上海", "delay_min": 120,
                         "original": "10:00", "delayed": "12:00", "reason": "天气原因"},
        "traffic": {"citywide_congestion": 0.45},
        "description": "小晴上海终面航班延误2小时"
    },
    "10": {  # 生理期痛经
        "time_override": "08:00",
        "weather": {"condition": "阴", "current_temp": 16, "alerts": []},
        "health_event": {"user": "student", "type": "menstrual_pain", "severity": "severe",
                         "duration_hours": 24},
        "description": "小晴生理期痛经请假"
    },
    "14": {  # 沙尘暴突袭
        "time_override": "08:00",
        "weather": {"condition": "沙尘暴", "current_temp": 18, "alerts": ["沙尘暴黄色预警"],
                    "aqi_override": 350, "wind_level_override": 6},
        "traffic": {"citywide_congestion": 0.7},
        "description": "北京沙尘暴黄色预警，AQI>300"
    },
    "15": {  # 早高峰地铁故障
        "time_override": "08:15",
        "weather": {"condition": "晴", "current_temp": 22, "alerts": []},
        "traffic": {"citywide_congestion": 0.8, "metro_disruption": {
            "line": "6号线", "station": "常营", "delay_min": 20, "reason": "信号故障"}},
        "description": "6号线常营段信号故障，延误20分钟"
    },
    "18": {  # 宠物急诊
        "time_override": "18:30",
        "weather": {"condition": "多云", "current_temp": 20, "alerts": []},
        "health_event": {"user": "parent", "type": "pet_emergency", "person": "布丁",
                         "severity": "severe", "duration_hours": 6},
        "description": "布丁疑似误食呕吐，阿彬加班中小冉独自应对"
    },
    "19": {  # 到店发现关门
        "time_override": "18:00",
        "weather": {"condition": "晴", "current_temp": 25, "alerts": []},
        "restaurant_closure": True,
        "traffic": {"citywide_congestion": 0.5},
        "description": "小晴约好聚餐的餐厅临时歇业"
    },
}

# ============================================================
# 工具函数
# ============================================================

def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Haversine 公式计算两点距离（米）"""
    R = 6371000
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def safe_float(val, default=0.0) -> float:
    try:
        if isinstance(val, (list, tuple)):
            return float(val[0]) if val else default
        return float(val)
    except:
        return default

def safe_int(val, default=0) -> int:
    try:
        if isinstance(val, (list, tuple)):
            return int(float(val[0])) if val else default
        return int(float(val))
    except:
        return default

def parse_lonlat(location_str: str) -> Tuple[float, float]:
    """解析 "lon,lat" 字符串"""
    try:
        lon, lat = location_str.split(",")
        return float(lon), float(lat)
    except:
        # 返回北京中心 + 小随机偏移
        return 116.4 + random.uniform(-0.1, 0.1), 39.9 + random.uniform(-0.1, 0.1)

def random_pick(items: List, count: int = 1) -> List:
    """随机挑选 count 个不重复元素"""
    return random.sample(items, min(count, len(items)))

def generate_id() -> int:
    return random.randint(10000, 99999)

def match_cuisine(name: str, typecode: str) -> Tuple[str, str]:
    """
    从店名推断菜系：关键字匹配优先，typecode 兜底
    返回 (菜系大类, 子菜系)
    """
    for pattern, cuisine, sub in CUISINE_KEYWORDS_COMPILED:
        if pattern.search(name):
            return cuisine, sub
    # typecode 兜底
    tc_prefix = typecode[:6] if typecode else ""
    TC_TO_CUISINE = {
        "050100": ("中餐", "综合中餐"),
        "050200": ("火锅", "川渝火锅"),
        "050300": ("烧烤", "中式烧烤"),
        "050400": ("日料", "综合日料"),
        "050500": ("韩餐", "经典韩餐"),
        "050600": ("西餐", "欧陆西餐"),
        "050700": ("东南亚菜", "综合东南亚"),
        "050800": ("快餐/简餐", "中式快餐"),
        "050900": ("咖啡厅", "综合咖啡"),
        "051000": ("茶馆", "中式茶馆"),
        "051100": ("酒吧", "综合酒吧"),
    }
    if tc_prefix in TC_TO_CUISINE:
        return TC_TO_CUISINE[tc_prefix]
    return ("中餐", "综合中餐")

def match_metro_station(name: str) -> Tuple[List[str], float, float]:
    """
    匹配站名到真实北京地铁线路
    返回 (线路列表, 参考经度, 参考纬度)
    坐标是近似值，用于网络拓扑构建
    """
    for line, info in BEIJING_METRO_LINES.items():
        if name in info["stations_ordered"]:
            idx = info["stations_ordered"].index(name)
            # 生成近似坐标（实际会在种子数据中获取精确坐标）
            if info["direction"] in ("east-west", "east-west-north"):
                lon = 116.2 + idx * 0.02
                lat = 39.92
            else:
                lon = 116.38
                lat = 39.78 + idx * 0.025
            return [line], lon, lat
    return [], 0.0, 0.0

def generate_cuisine_reviews(cuisine: str, rating: float, count: int = None) -> List[Dict]:
    """生成菜系对口的模拟评价"""
    if count is None:
        count = random.randint(4, 8)
    templates = CUISINE_REVIEW_TEMPLATES.get(cuisine, {"pos": DEFAULT_REVIEW_POS, "neg": DEFAULT_REVIEW_NEG})
    reviews = []
    for _ in range(count):
        is_pos = random.random() < 0.75
        comment = random.choice(templates["pos"] if is_pos else templates["neg"])
        r = round(random.uniform(3.5, 5.0), 1) if is_pos else round(random.uniform(2.0, 3.5), 1)
        days_ago = random.randint(0, 28)
        review_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        reviews.append({
            "user_name": f"用户{random.randint(100, 9999)}",
            "rating": r,
            "comment": comment,
            "date": review_date,
            "tags": random_pick(["服务好", "味道正宗", "环境好", "性价比高", "上菜快", "分量足",
                                 "适合拍照", "安静", "排队久", "停车方便"], random.randint(1, 3))
        })
    return reviews

def nearest_pois(lon: float, lat: float, pois: List[Dict], n: int = 3, max_dist: float = 5000) -> List[Dict]:
    """找最近的 N 个 POI（含距离字段）"""
    results = []
    for poi in pois:
        plon = safe_float(poi.get("longitude", poi.get("location", "0,0").split(",")[0]))
        plat = safe_float(poi.get("latitude", poi.get("location", "0,0").split(",")[1] if "," in str(poi.get("location", "")) else "0"))
        if plon == 0 and plat == 0:
            continue
        dist = haversine(lon, lat, plon, plat)
        if dist <= max_dist:
            results.append((dist, poi))
    results.sort(key=lambda x: x[0])
    return [{"distance_meters": int(d), **p} for d, p in results[:n]]

def is_in_mall(address: str, mall_names: List[str]) -> Optional[str]:
    """判断地址是否在商场内"""
    for mall in mall_names:
        short_name = mall.replace("购物中心", "").replace("商场", "").replace("广场", "").replace("大厦", "")
        if short_name in address or mall in address:
            return mall
    return None

def day_of_week_cn(date: datetime = None) -> str:
    """返回中文星期几"""
    if date is None:
        date = datetime.now()
    days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return days[date.weekday()]

def is_weekend(date: datetime = None) -> bool:
    if date is None:
        date = datetime.now()
    return date.weekday() >= 5

def is_meal_time(hour: int = None) -> bool:
    """判断是否在饭点"""
    if hour is None:
        hour = datetime.now().hour
    return (11 <= hour <= 13) or (17 <= hour <= 19)

def is_rush_hour(hour: int = None) -> bool:
    """判断是否在交通高峰"""
    if hour is None:
        hour = datetime.now().hour
    return (7 <= hour <= 9) or (17 <= hour <= 19)
