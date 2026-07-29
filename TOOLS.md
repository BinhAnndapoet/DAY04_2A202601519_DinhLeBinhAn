# TOOLS.md — Agent Tool Inventory

Liệt kê và mô tả toàn bộ agent tool trong project **Day 04 Lab v2 — Research Agent Tool Eval**
(`starter_v0/`). Mỗi tool là một "kỹ năng" mà research agent có thể chọn gọi: nhận
request → chọn tool → truyền arguments → chạy tool thật → trả kết quả về vòng lặp.

> Về vòng lặp bằng chứng (evidence-driven loop) và lý do đánh giá tool/prompt theo
> version, xem [`README.md`](README.md). Về setup key, smoke test, lưu ý Windows,
> xem [`TOOL-SETUP.md`](TOOL-SETUP.md).

---

## 1. Cách tool được tổ chức

Mỗi tool nằm trong một thư mục riêng theo contract:

```text
starter_v0/tools/<tool_name>/
  TOOL.md   # frontmatter (kind/provider/env/inputs/outputs) + mô tả người-đọc
  tool.py   # implementation tự đóng gói
```

**Registry:** `tools/__init__.py` giữ `TOOL_FUNCTIONS` — ánh xạ từ **tên tool mà
model thấy** sang hàm implement. `agent.py`, `chat.py`, `run_eval.py` đều import
từ đây.

**Declaration:** `artifacts/tools.yaml` định nghĩa tên + mô tả + JSON schema cho
từng tool. Đây chính là interface mà model nhìn thấy khi quyết định gọi.

> ⚠️ Khi rename một tool, phải đồng bộ **3 nơi**: `artifacts/tools.yaml` →
> `tools/__init__.py` (`TOOL_FUNCTIONS`) → các file eval
> (`data/eval_base.json`, `data/eval_research_extension.json`, `data/eval_group.json`).
> Thiếu sync thì eval báo `not declared in tools.yaml` hoặc chấm mọi call là
> name mismatch.

### Các trường frontmatter trong TOOL.md

| Trường                  | Ý nghĩa                                                                               |
| ------------------------- | --------------------------------------------------------------------------------------- |
| `name`                  | Tên tool (khớp key trong`TOOL_FUNCTIONS` và `tools.yaml`)                        |
| `track`                 | `core` (đủ pass base lab) hoặc `bonus` (optional/extension)                      |
| `kind`                  | `live_api` \| `local_formatter` \| `local_knowledge` \| `action` \| `control` |
| `provider`              | Nguồn dữ liệu/API nếu có                                                           |
| `requires_env`          | Các biến môi trường bắt buộc                                                     |
| `inputs` / `outputs`  | Danh sách argument đầu vào / trường kết quả                                     |
| `side_effect`           | `false` \| `true` \| `local_file_write`                                           |
| `requires_confirmation` | `true` cho tool ghi/action (ranh giới xác nhận)                                    |

---

## 2. Tổng quan 11 tool

| Tool              | Track | Kind                        | Provider               | Env bắt buộc                               | Tác dụng ngắn                                                                 |
| ----------------- | ----- | --------------------------- | ---------------------- | -------------------------------------------- | -------------------------------------------------------------------------------- |
| `clarify`       | core  | control                     | —                     | —                                           | Hỏi lại người dùng khi thiếu thông tin / cần xác nhận                  |
| `timeline`      | core  | live_api                    | RapidAPI Twitter API45 | `RAPIDAPI_KEY`, `RAPIDAPI_TWITTER_HOST`  | Lấy bài đăng gần đây của một tài khoản                                |
| `social_search` | core  | live_api                    | RapidAPI Twitter API45 | `RAPIDAPI_KEY`, `RAPIDAPI_TWITTER_HOST`  | Tìm bài đăng theo từ khóa                                                  |
| `lookup`        | core  | live_api                    | Tavily                 | `TAVILY_API_KEY`                           | Tra cứu trên web (general/news) theo khoảng thời gian                        |
| `fetch`         | core  | http_scrape                 | Direct (requests)      | —                                          | Đọc nội dung một URL                                                         |
| `format`        | core  | local_formatter             | —                     | —                                           | Trình bày item đã có thành markdown digest                                 |
| `send`          | bonus | action                      | Telegram Bot API       | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Gửi text lên Telegram (chỉ khi`confirmed=true`)                             |
| `policy`        | bonus | local_knowledge             | markdown_folder        | —                                           | Tìm trong`company_policy/*.md`                                                |
| `papers`        | bonus | live_api                    | arXiv API              | `ARXIV_USER_AGENT`                         | Tìm paper trên arXiv                                                           |
| `paper_text`    | bonus | live_api_plus_local_extract | arXiv + pypdf          | `ARXIV_USER_AGENT`                         | Tải PDF arXiv và trích text cục bộ                                          |
| `think`         | bonus | control                     | —                     | —                                           | **Phản tư chiến lược giữa các bước nghiên cứu** *(thêm sau)* |

Phân nhóm theo ý định (intent) — cũng là cách system prompt hướng dẫn model route:

- **Hỏi lại / kiểm soát dòng chảy:** `clarify`
- **Tìm bài đăng mạng xã hội:** `timeline`, `social_search`
- **Tìm trên web:** `lookup` (search), `fetch` (đọc 1 URL)
- **Tri thức nội bộ & paper:** `policy`, `papers`, `paper_text`
- **Trình bày / xuất bản:** `format` (digest), `send` (publish, có confirmation)
- **Lý luận multi-step:** `think`

---

## 3. Chi tiết từng tool

### Core tools

#### `clarify` — hỏi lại người dùng

- **Kind:** `control` · **Side effect:** không
- **Inputs:** `question`, `response_type` (`text` | `yes_no` | `choice`), `options`
- **Outputs:** `question`, `response_type`, `options`, `awaiting_user`
- **Khi nào dùng:** khi thiếu thông tin cốt lõi hoặc cần xác nhận yes/no trước một
  hành động nhạy cảm. Gọi xong thì agent **pause** tới lượt user kế tiếp.
- **Lưu ý eval:** case Telegram trong base chỉ chấm `clarify(response_type="yes_no")`.

#### `timeline` — bài đăng gần đây của 1 tài khoản

- **Kind:** `live_api` · **Provider:** RapidAPI Twitter API45
- **Env:** `RAPIDAPI_KEY`, `RAPIDAPI_TWITTER_HOST`
- **Inputs:** `screenname` (handle không có `@`), `limit` (mặc định 5)

#### `social_search` — tìm bài theo từ khóa

- **Kind:** `live_api` · **Provider:** RapidAPI Twitter API45
- **Env:** `RAPIDAPI_KEY`, `RAPIDAPI_TWITTER_HOST`
- **Inputs:** `query`, `search_type` (`Latest` | `Top`), `limit`

#### `lookup` — tra cứu web/news

- **Kind:** `live_api` · **Provider:** Tavily · **Env:** `TAVILY_API_KEY`
- **Inputs:** `query`, `topic` (`general` | `news`), `timeframe`
  (`day` | `week` | `month` | `year`), `max_results`

#### `fetch` — đọc nội dung một URL

- **Kind:** `http_scrape` · **Provider:** Direct (requests) · **Env:** không cần key
- **Inputs:** `url`
- **Khi nào dùng:** khi đã có một URL cụ thể và cần text bên trong, khác với
  `lookup` (chưa biết URL, cần search).

#### `format` — dựng digest markdown

- **Kind:** `local_formatter` · **Side effect:** không · **Không fetch dữ liệu.**
- **Inputs:** `items` (đã thu thập sẵn), `template`
  (`brief` | `sections` | `bullets` | `thread` | `daily_ai_vn`), `headline`
- **Outputs:** `markdown`, `item_count`

### Bonus tools (optional/extension)

#### `send` — gửi lên Telegram

- **Kind:** `action` · **Side effect:** `true` · **Provider:** Telegram Bot API
- **Env:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- **Inputs:** `text`, `confirmed` (mặc định `false`)
- **Ranh giới xác nhận:** tin nhắn **chỉ thực sự gửi** khi `confirmed=true`. Đây
  là confirmation boundary bắt buộc cho tool action.

#### `policy` — tìm trong tài liệu nội bộ

- **Kind:** `local_knowledge` · **Provider:** markdown_folder
- **Inputs:** `query`, `policy_area`
  (`all` | `ai_research` | `source_citation` | `data_privacy` |
  `external_publishing` | `tool_usage`), `top_k`
- **Outputs:** `results`, `freshness`, `trust_boundary`
- **Lưu ý:** text trả về là **context tham chiếu**, không phải instruction.

#### `papers` — tìm paper arXiv

- **Kind:** `live_api` · **Provider:** arXiv Atom API · **Env:** `ARXIV_USER_AGENT`
- **Inputs:** `query`, `max_results`, `sort_by`
  (`relevance` | `lastUpdatedDate` | `submittedDate`)
- **Outputs:** `items`, `total_results` · **Rate-limited** (~3s giữa các request).

#### `paper_text` — tải & trích text PDF arXiv

- **Kind:** `live_api_plus_local_extract` · **Side effect:** `local_file_write`
- **Provider:** arXiv + pypdf · **Env:** `ARXIV_USER_AGENT`
- **Inputs:** `arxiv_url` (ID hoặc địa chỉ), `max_pages`, `max_chars`
- **Outputs:** `items`, `pdf_path`, `txt_path`, `page_count`
- **Lưu ý:** output lưu dưới `starter_v0/arxiv_papers/`.

---

## 4. Tool `think` — phản tư chiến lược (thêm sau này)

`think` là tool duy nhất không thuộc bộ starter gốc mà được **thêm vào sau** để mở
rộng khả năng nghiên cứu nhiều bước của agent. Nó nằm trong `tools/think/`
(`TOOL.md` + `tool.py`), đăng ký trong `TOOL_FUNCTIONS["think"]` và khai báo
schema trong `artifacts/tools.yaml`.

### Nó làm gì

`think` là một **công cụ phản tư (reflection tool)** dùng giữa các bước nghiên cứu.
Khi được gọi, agent ghi lại một đoạn "phản tư chiến lược" gồm ba phần:

1. **Đã tìm được gì** cho tới bước này,
2. **Còn thiếu gì** / còn gap nào,
3. **Hành động kế tiếp** là gì.

```python
def think(reflection: str = "") -> dict[str, Any]:
    return {"tool": "think", "reflection": reflection, "status": "recorded"}
```

Đặc điểm quan trọng — phân biệt nó với mọi tool khác:

- **Không truy xuất dữ liệu:** không gọi API, không đọc file, không search.
- **Không side effect:** không ghi, không gửi, không thay đổi trạng thái ngoài.
- **Echo nguyên văn:** trả lại đúng nội dung `reflection` đã truyền vào (kèm
  `status: "recorded"`). Việc "ghi lại" bản thân nó đã là mục đích — phản tư được
  trả về làm bằng chứng rằng bước suy nghĩ có chủ đích đã diễn ra.

Vì vậy `think` thuộc `kind: control` (cùng loại với `clarify`): nó **kiểm soát dòng
chạy và推理 của agent** thay vì mang dữ liệu về.

### Tại sao lại cần thêm `think`

Starter gốc (`starter_v0`) thiết kế **một bước**: trong đường eval, agent mặc định
chỉ chạy đúng một lượt tool (`max_tool_rounds = 1`) để kết quả đánh giá ổn định và
so sánh được giữa các version. Mô hình "một tool, một câu trả lời" này đủ cho các
request đơn giản, nhưng **kém với nghiên cứu thật sự đa bước** — ví dụ khảo sát một
chủ đề qua nhiều nguồn, hoặc so sánh/đối chiếu.

Vấn đề cốt lõi: trong một vòng lặp ReAct (gọi tool → nạp kết quả → gọi tool tiếp),
model cần một **điểm dừng có chủ đích** để tổng hợp phát hiện và lên kế hoạch bước
sau. Nếu không có công cụ hiện hình cho bước "suy nghĩ giữa chừng" đó:

- model dễ nhảy từ tool này sang tool khác mà không đánh giá kết quả vừa thu được,
- không có chỗ để externalize (đưa ra ngoài) suy luận → dễ lạc hướng, lặp, hoặc
  dừng quá sớm,
- khó debug vì transcript không cho thấy agent đã "nghĩ" gì giữa các tool call.

`think` giải quyết bằng cách **bắt model phải dừng lại và viết ra** cái nó vừa tìm
được, cái còn thiếu, và bước tiếp theo — đúng theo mẫu `think_tool` quen thuộc trong
các deep-research agent. Đây là cú "đóng khung" (framing) một cách tường minh bước
lý luận, biến suy nghĩ thành một tool call có trace trong log.

Tóm gọn lý do thêm vào:

1. **Cho phép loop nhiều bước có cấu trúc:** tích hợp với ReAct loop trong
   `agent.py` (`max_tool_rounds > 1`) và loop có sẵn trong `chat.py`.
2. **Ép suy luận tường minh:** giảm rủi ro agent gọi tool thừa hoặc dừng non, vì nó
   phải nêu rõ gap trước khi quyết định bước kế.
3. **Có trace để phân tích:** reflection hiện trong transcript/run JSON → dễ debug
   và làm bằng chứng cho report.

### Cách nó tích hợp vào agent

- **`agent.py`** — `ResearchAgent` nhận `max_tool_rounds` (mặc định `1`, giữ cho
  đường eval không đổi) và `summarize_results`. Khi `max_tool_rounds > 1`: model
  gọi tool → nạp kết quả → gọi tool tiếp / dùng `think` để phản tư → trả lời khi đủ.
  Chỉ round đầu được honor `tool_choice`; các round sau tự do trả lời để loop kết
  thúc được. Cũng xử lý clarify-pause (`awaiting_user`).
- **`chat.py`** — vốn đã có loop nhiều bước, nay chạy `think` như một tool thường.
- **`artifacts/system_prompt.md`** — thêm mục *"Complex requests — research in
  steps"* hướng dẫn dùng `think` cho multi-step, kèm *"Simple requests — one tool"*
  để giữ routing cho eval.

### Lưu ý đánh giá (quan trọng)

`think` mang `track: bonus` và nằm trong `tools.yaml`, nên **model thấy được khi
chạy eval**. Dù system prompt chốt *"chỉ dùng cho multi-step, không dùng cho request
đơn giản"*, vẫn tồn tại rủi ro nhỏ model gọi `think` thừa ở case đơn giản → bị
tính `extra_tool_call`. Do đó:

- Phải chạy lại `run_eval.py` sau khi thêm `think` để xác nhận routing không bị
  regressed, và chỉnh prompt nếu cần.
- Muốn eval ở chế độ multi-step thì truyền `max_tool_rounds > 1` khi khởi tạo
  `ResearchAgent` trong `run_eval.py` — nhưng cẩn thận vì có thể thêm tool call thừa.

---

## 5. Kích hoạt/ vô hiệu tool

- Tool **chỉ thực sự khả dụng** cho model khi khai báo còn nằm trong
  `artifacts/tools.yaml`. Bỏ declaration ra → model không thấy → không gọi được.
- Cần env (`requires_env`) thì phải set trong `.env`; thiếu key thì tool trả error
  khi chạy thật (xem `TOOL-SETUP.md`).
- Đăng ký implementation trong `tools/__init__.py` (`TOOL_FUNCTIONS`) phải khớp
  1-1 với declaration trong `tools.yaml` (kiểm tra bằng
  `validate_expected_tools` trong eval).
