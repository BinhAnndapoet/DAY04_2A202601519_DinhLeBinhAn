
Đã thêm vào DAY04

1. Tool think (phản tư chiến lược)

- tools/think/tool.py + tools/think/TOOL.md — tool reflection (không truy xuất dữ liệu, trả lại reflection để agent suy nghĩ có chủ đích giữa các bước).
- Đăng ký đồng bộ 3 nơi: tools/__init__.py (TOOL_FUNCTIONS["think"]), artifacts/tools.yaml (khai báo schema). Đã verify declared == implemented,
  validate_expected_tools pass.

2. Vòng lặp nhiều bước (ReAct loop)

- agent.py — ResearchAgent giờ nhận max_tool_rounds (mặc định 1 để đường eval trong run_eval.py không đổi) và summarize_results. Khi max_tool_rounds>1: model
  gọi tool → feed kết quả về → gọi tool tiếp / dùng think để phản tư → trả lời khi đủ. Chỉ round đầu được honor tool_choice (các round sau tự do trả lời để loop
  có thể kết thúc). Xử lý clarify-pause (awaiting_user).
- AgentRun mở rộng thêm status, rounds (cho transcript) nhưng giữ nguyên text/tool_calls/tool_results để run_eval.py chạy không đổi.
- chat.py vốn đã có loop nhiều bước → giờ tự động chạy được think như tool thường.

3. Bước tóm tắt nội dung (content summarization)

- Helper chung summarize_tool_results() trong agent.py (gọi provider để nén raw content thành RESEARCH_NOTES). Chỉ kích hoạt khi nội dung đủ lớn (threshold
  1200 ký tự), bỏ qua think/clarify/format/send, lỗi thì trả None (fallback raw). Giống compress_research/summarize_webpage_content của deep_research.
- Đã wire vào cả 2: agent.py (khi summarize_results=True) và loop của chat.py (mỗi round).

4. System prompt

- Thêm mục "Simple requests — one tool" (giữ routing cho eval) + "Complex requests — research in steps" (hướng dẫn dùng think cho multi-step) + ghi chú
  summarize tự động.

  Verify

- py_compile OK; registry/yaml đồng bộ; test bằng provider giả chứng minh: loop 3 bước lookup → think → answer, summarize gọi đúng 1 lần sau lookup lớn, tắt
  summarize hoặc nội dung nhỏ → không gọi (gating đúng), clarify-pause đúng, single-step trả đúng first calls (eval-safe).
- Ruff: file mới sạch hoàn toàn; các warning còn lại (BLE001/DTZ005/I001/RUF010) đều là category pre-existing có sẵn ở file baseline chưa đụng (run_eval.py),
  tuân thủ convention except Exception của repo.

  Lưu ý quan trọng về eval

- Đường eval giữ nguyên hành vi (agent.py mặc định 1 bước, không summarize) → điểm số hiện tại không tự đổi.
- think giờ hiện trong tools.yaml nên model thấy được khi chạy eval. Mặc dù system prompt chốt "chỉ dùng cho multi-step, không dùng cho request đơn giản", vẫn
  tồn tại rủi ro nhỏ model gọi think thừa ở case đơn giản → bị extra_tool_call. Nên chạy lại eval (run_eval.py) để xác nhận routing không bị regressed, và
  chỉnh prompt nếu cần.
- Muốn chạy eval ở chế độ multi-step thì phải truyền max_tool_rounds>1 khi khởi tạo ResearchAgent trong run_eval.py — nhưng cẩn thận vì có thể thêm tool call
  thừa.

  Bạn có muốn tôi (a) chạy thử eval để kiểm tra routing sau khi thêm think, hay (b) thêm cờ CLI để bật/tắt multi-step + summarize cho cả eval lẫn chat?
