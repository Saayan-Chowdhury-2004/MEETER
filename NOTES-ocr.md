> **Note:** `paddleocr` pulls PaddlePaddle. If the full OCR engine is too heavy for
> your machine or CI, the agent automatically falls back to a deterministic
> heuristic `FallbackOCRProvider` (regex over an image-derived text estimate), and
> you can run everything with `OCRProvider` mocks in tests.
