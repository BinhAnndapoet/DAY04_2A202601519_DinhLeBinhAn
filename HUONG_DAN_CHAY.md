# Hướng dẫn chạy project DAY04 — Research Agent

Lab Day 04: build một research agent chạy thật (gọi tool thật, lưu log, tối ưu prompt/tool qua nhiều version).
Bản `starter_v0` đã có sẵn agent, eval và chat. Phần **UI (Streamlit `app.py`)** đã được ghép nối để project chạy được đầy đủ.

> Yêu cầu: **Python 3.11+** (đã test 3.11.15).

---

## 1. Cài đặt

Mở terminal ở thư mục `starter_v0`:

```bash
cd DAY04_2A202601519_DinhLeBinhAn/starter_v0

# (tuỳ chọn) tạo môi trường ảo
python -m venv .venv
# Windows (Git Bash / cmd):
.venv\Scripts\activate
# macOS / Linux:
# source .venv/bin/activate

# Cài dependency
python -m pip install -r requirements.txt
```

`requirements.txt` gồm: `openai`, `anthropic`, `google-genai` (provider), `requests`, `PyYAML`, `streamlit`, `pypdf`.

---

## 2. Cấu hình API key (.env)

```bash
# Nếu chưa có .env:
cp .env.example .env
```

Mở file `.env`, điền **ít nhất 1 key của model provider**:

```bash
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx        # khuyến nghị
# hoặc:
# OPENAI_API_KEY=sk-xxx
# ANTHROPIC_API_KEY=sk-ant-xxx
# GEMINI_API_KEY=xxx
```

Lưu ý:

- `OPENROUTER_API_KEY` hiện đang **trống** trong `.env` → phải điền mới gọi được model.
- `TAVILY_API_KEY` (dùng cho tool `lookup`) đã có sẵn.
- Các key Telegram/RapidAPI/Firecrawl là tuỳ chọn (track bonus), có thể bỏ qua.
- **Không bao giờ commit `.env`** (đã có trong `.gitignore`).

Kiểm tra nhanh provider đã cấu hình đúng chưa:

```bash
python scripts/preflight_provider.py --provider openrouter
```

(Đổi `openrouter` thành provider khác nếu dùng key khác.)

---

## 3. Chạy UI Streamlit (mặc định)

```bash
streamlit run app.py
```

Trình duyệt tự mở tại **http://localhost:8501**.

Trên UI có thể:

- Chọn **Provider**, gõ **Model** (để trống = default), đổi **Version label** (v0/v1/v2/v3…).
- Chat với agent: nhập request → xem câu trả lời + **trace từng tool** (tên, args, kết quả/lỗi, status).
- Xem `artifact_version`, `transcript_id` để biết đang chạy version nào.
- Transcript tự lưu vào `transcripts/*.transcript.json`.

> `app.py` **tái dùng đúng `run_model_tool_loop` trong `chat.py`** — UI và CLI chạy chung một agent loop, không viết logic riêng.

### Mở link cho máy khác test (Cloudflare Tunnel)

```bash
cloudflared tunnel --url http://localhost:8501
```

Lấy URL `trycloudflare.com` dán vào báo cáo. (Lưu ý bảo mật: không để lộ secrets trên UI public.)

---

## 4. Chạy eval (tối ưu version)

Vòng lặp evidence-driven: chạy eval → đọc run JSON → sửa `artifacts/system_prompt.md` hoặc `artifacts/tools.yaml` → chạy version tiếp theo.

```bash
# Baseline v0
python run_eval.py --provider openrouter --version v0 --suite base --eval-cases data/eval_base.json

# Các version tối ưu
python run_eval.py --provider openrouter --version v1 --suite base --eval-cases data/eval_base.json
python run_eval.py --provider openrouter --version v2 --suite base --eval-cases data/eval_base.json
python run_eval.py --provider openrouter --version v3 --suite base --eval-cases data/eval_base.json

# Eval do team viết (10 case)
python run_eval.py --provider openrouter --version v3 --suite group --eval-cases data/eval_group.json
```

Kết quả lưu trong `runs/*.json`. Các metric quan trọng: `summary.case_accuracy`, `summary.tool_routing_accuracy`, `summary.argument_accuracy`, `summary.multiturn_accuracy`, `summary.provider_error_cases` (phải = 0), `summary.measured_cases`.

Parse ra CSV để phân tích (tuỳ chọn):

```bash
python scripts/parse_runs.py runs/ --output analysis/base_runs.csv
```

---

## 5. Chat multi-round bằng CLI

```bash
python chat.py --provider openrouter --version v3
```

Gõ `/exit` để thoát. Mỗi turn lưu vào `transcripts/*.transcript.json`.

---

## 6. Các lệnh nhanh (tham khảo)

| Mục đích | Lệnh |
|---|---|
| Chạy UI | `streamlit run app.py` |
| Preflight provider | `python scripts/preflight_provider.py --provider openrouter` |
| Chạy base eval | `python run_eval.py --provider openrouter --version v0 --suite base --eval-cases data/eval_base.json` |
| Chat CLI | `python chat.py --provider openrouter --version v3` |
| Parse run → CSV | `python scripts/parse_runs.py runs/ --output analysis/base_runs.csv` |

---

## 7. Lưu ý trên Windows

- Dùng **Git Bash** hoặc **PowerShell**; lệnh kích hoạt venv: `.venv\Scripts\activate`.
- Nếu `python` không chạy, thử `py -3` hoặc `python3`.
- `streamlit run app.py` cần mở được `http://localhost:8501` = PASS.
- Đảm bảo thư mục hiện hành là `starter_v0` khi chạy các lệnh (các script dùng đường dẫn tương đối tới `artifacts/`, `data/`).

---

## 8. Cấu trúc chính

| Path | Mục đích |
|---|---|
| `app.py` | UI Streamlit (ghép nối `run_model_tool_loop` của `chat.py`) |
| `chat.py` | Chat CLI multi-round + agent loop dùng chung |
| `agent.py` | `ResearchAgent` + logic tóm tắt kết quả tool |
| `run_eval.py` | Chạy eval, ghi `runs/*.json` |
| `artifacts/system_prompt.md` | Instruction cho agent |
| `artifacts/tools.yaml` | Khai báo tool (tên + schema) |
| `artifacts/version_log.csv` | Giả thuyết + metric theo version |
| `data/eval_*.json` | Bộ eval |
| `providers/` | OpenRouter / OpenAI / Anthropic / Gemini |
| `tools/<tên>/tool.py` | Implement từng tool |

---

## 9. Xác minh đã chạy được

✅ `streamlit run app.py` mở được `http://localhost:8501`.
✅ Import module không lỗi (`python -c "import app"`).
✅ Agent loop (`run_model_tool_loop`) dùng chung giữa UI và CLI.

Sau khi điền API key vào `.env`, gửi 1 request trên UI là agent sẽ gọi tool thật và trả kết quả.
