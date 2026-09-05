from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldGuide:
    sheet: str
    field: str
    required: bool
    definition: str
    example: str
    note: str = ""


FIELD_GUIDE: list[FieldGuide] = [
    FieldGuide("待排工單", "工單編號", True, "工單或製令的唯一編號。系統用它識別每一張工單，不可重複。", "WO-20260905-001"),
    FieldGuide("待排工單", "產品", True, "要生產的產品代號，必須能在產品機台產速表找到對應產速。", "SIM-C2-A"),
    FieldGuide("待排工單", "數量", True, "本工單要生產的數量。必須大於 0。", "600"),
    FieldGuide("待排工單", "單位", True, "數量單位。目前排程時間以 PCS/hr 產速換算。", "PCS"),
    FieldGuide("待排工單", "優先級", True, "工單急迫程度。支援急單、一般、低優先。", "急單"),
    FieldGuide("待排工單", "交期", True, "工單需要完成的時間。只填日期時，系統視為當天 23:59:59。", "2026/09/05 18:00", "若只填 2026/09/05，代表 2026/09/05 23:59:59。"),
    FieldGuide("待排工單", "工單限定機台", False, "單張工單的特殊限制。空白代表依產品機台產速表判斷；若填 C2,C5，代表這張工單只能排在 C2 或 C5。", "C2,C5"),
    FieldGuide("產品機台產速", "產品", True, "產品代號。每個可生產的產品/機台組合各填一列。", "SIM-C2-A"),
    FieldGuide("產品機台產速", "機台", True, "可生產該產品的機台。", "C2"),
    FieldGuide("產品機台產速", "產速_PCS_per_hr", True, "標準產速，每小時可生產 PCS 數。系統用數量除以產速計算加工時間。", "120"),
    FieldGuide("產品機台產速", "換模群組", True, "產品族群或模具/換線分類。前後工單群組不同時，系統會計算換模時間。", "C2-A"),
    FieldGuide("機台初始狀態", "機台", True, "排程開始前的機台。用來判斷第一張工單是否需要換模。", "C2"),
    FieldGuide("機台初始狀態", "初始產品", True, "排程開始前，該機台正在做或最後做的產品。", "SIM-C2-A", "若不確定，可留空或填目前最接近的產品。"),
    FieldGuide("換模時間", "來源換模群組", True, "上一張工單的換模群組。", "C2-A"),
    FieldGuide("換模時間", "目標換模群組", True, "下一張工單的換模群組。", "C2-B"),
    FieldGuide("換模時間", "換模時間_分鐘", True, "從來源群組切換到目標群組需要的分鐘數。", "20"),
]


KPI_GUIDE: list[tuple[str, str]] = [
    ("準時率", "未遲交工單數 / 總工單數。完工時間晚於交期就算遲交。"),
    ("遲交工單", "完工時間晚於交期的工單張數。"),
    ("未排入", "因排程期間太短、無合格機台、停機/休假過多等原因，無法在本次期間完成的工單數。"),
    ("換模次數", "排程中換模時間大於 0 的次數。"),
    ("總遲交", "所有工單 max(完工時間 - 交期, 0) 的小時數加總。"),
    ("最大遲交", "單張工單最大遲交小時數。"),
    ("Makespan", "最後一張已排入工單的完工時間 - 本次排程開始時間。"),
    ("平均使用率", "各機台加工時間 / 排程期間小時數，再取 C2/C4/C5 平均；目前不含換模時間。"),
]


MANUAL_SECTIONS: list[tuple[str, str]] = [
    (
        "Excel 資料準備",
        "Excel 至少要有待排工單與產品機台產速。機台初始狀態與換模時間建議填寫，排程會更接近現場。機台可用時間與排程基本設定已改到畫面操作，舊檔仍可相容。",
    ),
    (
        "工單與產品機台",
        "產品機台產速是產品層級資料，用來定義某產品可在哪些機台做與產速。工單限定機台是單張工單例外限制，例如同一產品平常 C2/C5 都能做，但某張工單只准 C5，就在待排工單填 C5。",
    ),
    (
        "交期",
        "交期可填日期或日期加時間。只填日期時，系統視為當天 23:59:59；若要指定上午或下午交貨，請填 2026/09/05 15:30 這類日期加時間。",
    ),
    (
        "換模",
        "換模群組是產品族群或模具分類。前後工單群組相同時換模時間為 0；不同時先查換模時間表，若查不到才用畫面上的預設換模時間。",
    ),
    (
        "排程操作",
        "先上傳 Excel 或載入標準資料，再設定排程開始時間、期間、策略、本次使用機台、工時模式、人力產能、週末或指定休假日，最後按確認設定並開始排程。",
    ),
    (
        "特殊狀況 / 停機",
        "臨時停機、保養、盤點、設備不可用都在特殊狀況 / 停機輸入。系統會避開該機台不可用時段。若填錯，可按清除特殊狀況。",
    ),
    (
        "KPI 解讀",
        "準時率看交期達成，總遲交看整體延誤量，最大遲交看最嚴重單張工單，Makespan 看整批排程完成所需時間，平均使用率看機台加工負載。",
    ),
    (
        "歷史排程",
        "只有成功完成排程或重排後才建立正式版本。上傳檔案、修改參數但尚未成功排程，不會建立歷史版本。",
    ),
]


def field_guide_frame_rows() -> list[list[object]]:
    rows: list[list[object]] = [["工作表", "欄位", "必填", "定義", "範例", "備註"]]
    for item in FIELD_GUIDE:
        rows.append([item.sheet, item.field, "是" if item.required else "否", item.definition, item.example, item.note])
    return rows


def manual_text() -> str:
    parts = []
    for title, body in MANUAL_SECTIONS:
        parts.append(f"{title}\n{body}")
    parts.append("KPI 定義\n" + "\n".join(f"{name}：{definition}" for name, definition in KPI_GUIDE))
    return "\n\n".join(parts)


def answer_from_manual(question: str) -> str:
    text = question.strip().lower()
    if not text:
        return "請輸入你遇到的操作問題，例如：換模群組怎麼填、為什麼排不進去、C4/C5 怎麼指定。"
    candidates: list[tuple[int, str]] = []
    for item in FIELD_GUIDE:
        keywords = [item.sheet, item.field, item.example]
        score = sum(1 for keyword in keywords if keyword and keyword.lower() in text)
        if item.field.lower() in text:
            score += 5 + len(item.field)
        if score:
            required = "必填" if item.required else "選填"
            candidates.append((score + 2, f"`{item.field}` 是{required}欄位。{item.definition} 範例：{item.example}。{item.note}".strip()))
    for title, body in MANUAL_SECTIONS:
        keywords = title.split(" / ") + [title]
        score = sum(1 for keyword in keywords if keyword.lower() in text)
        if score:
            candidates.append((score, body))
    for name, definition in KPI_GUIDE:
        if name.lower() in text or (name == "平均使用率" and "利用率" in text):
            candidates.append((3, f"`{name}`：{definition}"))
    if candidates:
        return sorted(candidates, reverse=True)[0][1]
    return "目前小幫手找不到完全對應的條目。可以先檢查 Excel 必填欄位、產品機台產速、交期是否含時間、本次使用機台、工時模式、特殊狀況 / 停機與排程期間。"
