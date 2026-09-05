# East Fu Lean APS 部署說明

這套系統是 Streamlit / Python app，需要部署在可以長時間執行 Python server 的環境。

## 最短公司內部上線方式

適合先給公司同仁在同一個內網使用。

```powershell
cd C:\Users\User\Documents\Codex\2026-09-05\files-pasted-by-the-user-aps\outputs\east-fu-lean-aps
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

同一個公司網路內的同仁可用：

```text
http://你的電腦IP:8501
```

## Docker 部署方式

適合部署到公司 VM、NAS Docker、Azure、AWS、GCP、Render、Railway 等可跑容器的平台。

```bash
docker build -t east-fu-lean-aps .
docker run -d --name east-fu-lean-aps -p 8501:8501 east-fu-lean-aps
```

公司同仁即可連：

```text
http://伺服器IP:8501
```

## 網域與 HTTPS

正式給公司使用時，建議：

- 用固定主機或雲端服務部署。
- 設定公司網域，例如 `https://aps.company.com`。
- 前面加 Nginx / Caddy / Cloudflare Tunnel 做 HTTPS。
- 若資料含正式訂單，請限制只允許公司內網或 VPN 存取。

## 資料保存

目前排程歷史保存在：

```text
data/schedule_history.json
```

若使用 Docker 並希望容器更新後歷史仍保留，請掛載 volume：

```bash
docker run -d --name east-fu-lean-aps -p 8501:8501 -v east-fu-aps-data:/app/data east-fu-lean-aps
```

## 不適合的部署方式

一般靜態網站空間不適合，因為本系統需要：

- Python
- Streamlit server
- pandas / openpyxl 讀 Excel
- 伺服器端保存排程歷史

