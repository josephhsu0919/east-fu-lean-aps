# East Fu Lean APS

東福精實生產排程系統是一個簡潔、中文介面、Excel 驅動的 Lean APS MVP。

## 啟動方式

```bash
pip install -r requirements.txt
python scripts_make_demo.py
python -m streamlit run app.py
```

若要部署給公司同仁連線使用，請見 [DEPLOYMENT.md](DEPLOYMENT.md)。
若要部署成公開網址，請見 [STREAMLIT_CLOUD_DEPLOY.md](STREAMLIT_CLOUD_DEPLOY.md)。

內建標準資料 Excel 路徑：

```text
data/EastFu_Lean_APS_Demo.xlsx
```

## 使用流程

上傳 Excel，或按「載入東福標準排程資料」，完成驗證後選擇策略並執行 APS 排程。系統會產生排程結果、Plotly 甘特圖、KPI、策略比較與推薦方案，並可匯出 Excel 與甘特圖 HTML。

日常主流程控制在五步：

1. 上傳訂單 Excel
2. 選擇排程期間
3. 選擇排程策略
4. 按「開始排程」
5. 查看甘特圖與 KPI

## Excel 工作表

- 待排工單
- 產品機台產速
- 機台可用時間
- 排程基本設定

## 支援策略

- 急單優先＋最早交期
- 最早交期優先
- 先進先出
- 最短加工時間優先
- 最短等待時間優先
- 機台負載平衡
- 東福 Lean 綜合排程
- 減少換模

## 第二版新增

- 欄位 alias normalization：支援工單編號 / WO / work_order、產品編號 / Product、需求日期 / Due Date、Quantity、Priority 等欄名。
- Friendly validation：缺欄位時顯示中文訊息與偵測到的欄位，不暴露 KeyError 或 traceback。
- Planning horizon：支援 24 小時、48 小時、72 小時、一週、自訂開始 / 結束。
- Changeover：預設不同產品換模時間會影響開始時間、makespan、tardiness、換模次數。
- 今日異常：機台停機期間不可排入生產。
- 急單：可新增急單並建立新 schedule version。
- 歷史排程：每次排程保存到 `data/schedule_history.json`，重啟後仍可查看版本、訂單、甘特圖與 KPI。

## KPI 公式

- 完成工單數：結束時間未超過排程 horizon 的工單數。
- 未完成 / 超出 horizon 工單數：結束時間超過排程 horizon 的工單數。
- 準時完成率：未遲交工單數 / 總工單數 * 100。
- 遲交工單數：結束時間晚於交期的工單數。
- 總遲交時間：所有工單 max(結束時間 - 交期, 0) 的小時數總和。
- 平均遲交時間：總遲交時間 / 總工單數。
- 最大遲交時間：單張工單最大遲交小時數。
- Makespan：最後完工時間 - 排程開始時間。
- 平均等待時間：總等待時間 / 總工單數。
- 總等待時間：所有工單 max(開始時間 - 排程開始時間, 0) 的總和。
- C2/C4/C5 utilization：該機台加工時間 / horizon 小時數 * 100。
- 平均 utilization：三台機台 utilization 平均。
- Resource Load Imbalance：最大機台 utilization - 最小機台 utilization。

## 推薦邏輯

系統使用透明規則排序，不宣稱 AI 最佳化：

1. 準時完成率越高越好。
2. 總遲交時間越低越好。
3. 平均等待時間越低越好。
4. 資源負載不均越低越好。
5. Makespan 越低越好。

## 第一版限制

- 工單不拆分。
- 一張工單只排在一台合格機台。
- 工單開始後不插單、不中斷。
- 排程演算法為 deterministic heuristic。
- 手動調整為簡單下拉式機台指定，不支援拖拉甘特圖。
