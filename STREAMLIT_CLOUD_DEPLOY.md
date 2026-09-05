# Streamlit Community Cloud 公開部署手冊

這份文件用來把 East Fu Lean APS 發佈成公開網址，讓公司同仁或外部測試者直接用瀏覽器開啟。

## 重要提醒

公開網址代表知道連結的人都可能使用。上線公開 demo 時，請勿上傳真實客戶訂單、價格、產能或任何敏感資料。

目前系統的歷史排程會寫入 `data/schedule_history.json`。這個檔案已加入 `.gitignore`，不要把本機測試歷史推到 GitHub。若部署成公開 demo，建議定期清空部署端歷史，或後續改成登入後每家公司獨立保存。

## 需要準備

- GitHub 帳號
- Streamlit Community Cloud 帳號
- 本專案資料夾：`east-fu-lean-aps`

## Step 1：建立 GitHub Repository

1. 到 GitHub 建立新 repository，例如 `east-fu-lean-aps`
2. 建議先設為 `Private`
3. 將本專案整個資料夾上傳到 repository

需要上傳的主要檔案：

- `app.py`
- `requirements.txt`
- `.streamlit/config.toml`
- `aps/`
- `ui/`
- `data/EastFu_Lean_APS_Demo.xlsx`
- `README.md`

不要上傳：

- `.pytest_cache/`
- `__pycache__/`
- `tests/.tmp/`
- `data/schedule_history.json`

## Step 2：部署到 Streamlit Cloud

1. 開啟 [Streamlit Community Cloud](https://streamlit.io/cloud)
2. 使用 GitHub 登入
3. 點選 `Create app`
4. Repository 選擇 `east-fu-lean-aps`
5. Branch 選擇 `main`
6. Main file path 填：

```text
app.py
```

7. 點選 `Deploy`

部署完成後會得到公開網址，例如：

```text
https://east-fu-lean-aps.streamlit.app
```

## Step 3：公開網址測試

開啟網址後確認：

1. 首頁顯示「東福精實生產排程系統」
2. 點「載入東福 10 筆示範資料」
3. 顯示 `10 / 10 orders valid`
4. 選 `24 小時`
5. 選 `交期優先 EDD`
6. 點「開始排程」
7. 看得到甘特圖、KPI、排程摘要
8. 上傳 `OSFP_Gen1_APS_UAT_10單_24H_C2C4C5.xlsx`
9. validation PASS，並可開始排程

## 常見問題

### 網頁顯示 ModuleNotFoundError

確認 `requirements.txt` 有：

```text
streamlit
pandas
openpyxl
plotly
```

### 上傳 Excel 後格式錯誤

請確認 workbook 至少有：

- `待排工單`
- `產品機台產速`
- `機台可用時間`
- `排程基本設定`

系統支援 East Fu UAT 欄位，例如：

- `製令單號*`
- `產品品號*`
- `預計產量*`
- `交期*`
- `工單急迫程度*`
- `標準產速*`
- `可用起始時間*`
- `可用結束時間*`

### 歷史排程資料

公開 demo 階段請把歷史排程視為暫存展示資料。正式營運前，建議加上登入與每家公司獨立資料保存。

