# Day 04 Lab v2 Report — Research Agent

> File này gồm 2 phần, deadline khác nhau:
>
> - **PHẦN A — Giới thiệu agent**: ngắn gọn 1 trang để team khác hiểu nhanh agent có tool gì, làm được gì, thử bằng câu hỏi nào. Xong trước 11:30 để làm tài liệu phụ trợ khi demo.
> - **PHẦN B — Chi tiết / Bằng chứng**: bảng đầy đủ (v0–v3, failure, eval, chat) dựa trên log thật. Có thể hoàn thiện sau buổi debate để nộp bài.

## Team

- Team: An - Châu - Ninh
- Members: Đinh Lê Bình An - 2A202601519, Nguyễn Khánh Bảo Châu - 2A202601221, Nguyễn Văn Ninh - 2A202601419
- Provider/model: OpenAI (gpt-4o-mini)

---

# PHẦN A — Giới thiệu agent

## A1. Agent này làm được gì

Research agent: tìm và tổng hợp thông tin từ nhiều nguồn (web news, social media, tài liệu nội bộ, academic papers) theo yêu cầu của người dùng. Agent có thể đọc URL, tìm bài đăng theo tài khoản/chủ đề, tra cứu quy định công ty, và trình bày kết quả thành digest có cấu trúc.

**Link dùng thử (truy cập được trong showdown):**

- Local: `streamlit run app.py` → `http://localhost:8501`
- UI có đầy đủ chat workspace, tool trace, transcript, và version evidence để demo improvement qua các version.

## A2. Tool agent có

| Tên tool     | Làm được gì                                                                      | Tool mới nhóm thêm? |
| ------------- | ------------------------------------------------------------------------------------- | ---------------------- |
| clarify       | Hỏi lại người dùng khi thiếu thông tin hoặc cần xác nhận yes/no            | không                 |
| timeline      | Lấy bài đăng CỦA MỘT TÀI KHOẢN cụ thể (Twitter/X)                           | không                 |
| social_search | Tìm bài đăng VỀ MỘT CHỦ ĐỀ/từ khóa trên mạng xã hội                    | không                 |
| lookup        | Tra cứu thông tin trên internet (general/news) với timeframe                      | không                 |
| fetch         | Lấy nội dung từ một địa chỉ URL cụ thể                                       | không                 |
| format        | Trình bày dữ liệu đã có thành văn bản digest có cấu trúc                 | không                 |
| think         | Ghi lại phản tư chiến lược giữa các bước nghiên cứu (chỉ cho multi-step) | có                    |
| send          | Gửi text lên Telegram channel (optional)                                            | không                 |
| policy        | Tra cứu QUY ĐỊNH NỘI BỘ của công ty theo mảng                                 | không                 |
| papers        | Tìm bài báo khoa học trên arXiv                                                  | không                 |
| paper_text    | Lấy nội dung text của một bài báo arXiv                                         | không                 |

## A3. Câu hỏi mẫu để thử

1. "Tin AI nổi bật hôm nay là gì? Tóm tắt 5 nguồn đáng chú ý."
2. "Tìm 5 bài đăng mới nhất của tài khoản karpathy."
3. "Đọc URL này và tóm tắt các luận điểm chính giúp tôi: https://openai.com/blog/hello"
4. "Tìm 3 paper mới về AI agents và nêu đóng góp chính."
5. "Quy định nội bộ của công ty về việc dùng tool tự động là gì?"

## A4. Kịch bản demo đã rehearse

| Scenario                                | Tool trace cần thấy                                               | Câu chuyện cải thiện version              | Fallback run/transcript |
| --------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------- | ----------------------- |
| **Social search**                 | `social_search` với đúng `query`, `search_type`, `limit` | v0→v1: fix arg extraction từ multi-turn     | G08                     |
| **Internal policy lookup**        | `policy` với đúng `policy_area=tool_usage`                   | v0→v1: fix arg value, tool routing OK        | G01                     |
| **No think on single-step**       | CHỈ MỘT tool call, KHÔNG có`think`                            | v0→v1: thêm luật think chỉ cho multi-step | G03                     |
| **Explicit authorization send**   | `send` với `confirmed: true` khi user đã duyệt              | v0→v1: fix boundary over-asking              | G04                     |
| **Out of scope financial advice** | KHÔNG GỌI TOOL, refuse with explanation                           | v0→v1: thêm luật out_of_scope              | G05                     |

---

# PHẦN B — Chi tiết / Bằng chứng

> Điều kiện metric hợp lệ: `provider_error_cases` phải bằng `0`; `measured_cases` phải bằng `total_cases`; và bất kỳ `tool_results` nào có error đều phải được review thủ công vì routing PASS không chứng minh tool execution đã đúng.

## B1. Version evidence

Fill from `artifacts/version_log.csv` and `runs/*.json`.

| Version | Prompt/tool change                                                 | Hypothesis                                                                  | Metric name           | Before | After | Run File                                     |
| ------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------- | --------------------- | -----: | ----: | -------------------------------------------- |
| v0      | baseline                                                           | —                                                                          | case_accuracy         |     — |   0.4 | v0_B_group_openai_20260729T110324639735.json |
| v1      | Cải thiện tool declaration trong`tools.yaml`                   | Rõ ràng hơn trong mô tả arg`policy_area`, `search_type`, `limit` | argument_accuracy     |    0.4 |   0.9 | v1_B_group_openai_20260729T110617194661.json |
| v2      | Thêm luật`think` chỉ cho multi-step vào `system_prompt.md` | Giảm unnecessary_tool cho single-step                                      | tool_routing_accuracy |    1.0 |   0.9 | v2_B_group_openai_20260729T110940184026.json |

## B2. Failure analysis

Use actual failures from `results[*].result.failures`.

| Case ID | Failure Type     | Actual Tool Calls                              | What Failed                                    | Fix                                                |
| ------- | ---------------- | ---------------------------------------------- | ---------------------------------------------- | -------------------------------------------------- |
| G01     | wrong_arg_value  | `policy(args={query: "tool usage"})`         | Thiếu`policy_area: "tool_usage"`            | v1: cải thiện description trong tools.yaml       |
| G03     | unnecessary_tool | `social_search` + `think`                  | `think` không nên dùng cho single-step    | v2: thêm luật think vào system_prompt.md        |
| G04     | wrong_boundary   | `clarify` thay vì `send(confirmed: true)` | Over-asking khi user đã xác nhận rõ ràng | v1: cải thiện description của`confirmed` arg  |
| G05     | out_of_scope     | `lookup` (called by agent)                   | Financial advice là out_of_scope              | v1: thêm luật out_of_scope vào system_prompt.md |

## B3. Team eval cases

List the 10 cases added to `data/eval_group.json`:

- 5 single-turn
- 5 multi-turn

This section is for the mandatory team-authored eval set. Optional built-ins do
not belong here.

File template để trống có chủ đích; nhóm phải tự thiết kế đủ 10 case.

| Case ID | What It Tests                                                       | Expected Tool/Behavior                                                   | Result  |
| ------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------- |
| G01     | Routing internal docs + arg`policy_area=tool_usage`               | `policy(args={policy_area: "tool_usage"})`                             | v1 PASS |
| G02     | Arg extraction:`max_results`, `timeframe=month`, `topic=news` | `lookup(args={max_results: 8, timeframe: "month", topic: "news"})`     | v1 PASS |
| G03     | No extra`think` on single-step                                    | CHỈ MỘT tool`social_search`, KHÔNG `think`                        | v2 PASS |
| G04     | Boundary: explicit authorization →`send(confirmed: true)`        | `send(args={confirmed: true})`                                         | v1 PASS |
| G05     | Out_of_scope: financial advice                                      | NO tool, refuse                                                          | v1 PASS |
| G06     | Multi-turn: still missing topic after clarification                 | `clarify(args={response_type: "text"})`                                | v0 PASS |
| G07     | Multi-turn: withdrawn send action                                   | NO tool, answer_without_tool                                             | v0 PASS |
| G08     | Multi-turn: accumulate 3 args (query, search_type, limit)           | `social_search(args={query: "Claude", search_type: "Top", limit: 8})`  | v1 PASS |
| G09     | Multi-turn: switch web→arxiv + sort_by                             | `papers(args={query: "mixture of experts", sort_by: "submittedDate"})` | v1 PASS |
| G10     | Multi-turn: reformat WITHOUT researching again                      | `format(args={template: "sections"})`                                  | v0 PASS |

## B4. Live chat evidence

Use `transcripts/*.transcript.json`.

| Scenario/Turn                                        | Version | Tool Calls + Args | Transcript/Run                | Outcome |
| ---------------------------------------------------- | ------- | ----------------- | ----------------------------- | ------- |
| (Optional) Thêm live chat transcript từ`chat.py` | v2      | —                | transcripts/*.transcript.json | —      |

## B5. Tool capability evidence

Phân loại rõ tool mới bắt buộc, optional built-in và tool đủ điều kiện bonus. Chỉ ghi Telegram/PDF nếu nhóm thực sự dùng; base report không cần chúng.

UI is core deliverable, not bonus. Do not list it here.

| Category                         | Evidence File            | What Worked                                                            | Risk / Guardrail                                  |
| -------------------------------- | ------------------------ | ---------------------------------------------------------------------- | ------------------------------------------------- |
| Must-have: tool mới đầu tiên | —                       | —                                                                     | —                                                |
| Optional built-in                | runs/v*_B_group_*.json | `send`, `policy`, `papers`, `paper_text` đều có declaration | Optional tools không được tính là must-have |
| Bonus: tool mới thứ 4 trở đi | —                       | —                                                                     | —                                                |

## B6. Reflection

- **Which fixes belonged in `system_prompt.md`?**

  - Luật `think` chỉ dùng cho multi-step research (v2)
  - Luật out_of_scope cho financial advice (v1)
  - Luật missing information: ask, do not guess (baseline)
- **Which fixes belonged in `tools.yaml`?**

  - Cải thiện description của `policy_area` arg trong tool `policy` (v1)
  - Cải thiện description của `search_type` và `limit` trong tool `social_search` (v1)
  - Cải thiện description của `confirmed` arg trong tool `send` (v1)
- **Which failure needed manual review instead of automatic grading?**

  - Không có case nào cần manual review vì `provider_error_cases = 0` và `measured_cases = total_cases`.
- **What would you improve next?**

  - Thêm version v3 với cải thiện thêm cho multi-turn accuracy (v2 có 0.8)
  - Thêm live chat transcript để demo UI
  - Cải thiện tool declaration thêm nữa để tăng argument accuracy lên 1.0
