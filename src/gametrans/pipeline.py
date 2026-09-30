"""Ties capture -> OCR -> layout -> tier 0/1(/2) translation -> store
together across the threads described in spec section 10:

  1. capture+ocr thread (single thread: OCR is the bottleneck and always
     wants "the latest frame", never a queue of stale ones)
  2. fast-translate thread (tier 1, batches, writes non-final store entries)
  3. refine thread (tier 2, optional -- only runs if a refine_translator is
     given; not exercised with a real LLM in this project, see DECISIONS.md
     phase 4)

All dependencies (capture backend, OCR function, translators, store) are
injectable via constructor kwargs so this module is unit-testable without
a GPU, a real screen, or a downloaded model -- production code just uses
the defaults, which wire up the real implementations.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from gametrans.layout import Block, OcrLine, merge_lines, track_blocks
from gametrans.ocr_post import clean_text
from gametrans.store import Store
from gametrans.textprep import prepare
from gametrans.guards import check_translation

logger = logging.getLogger("gametrans.pipeline")


@dataclass(frozen=True)
class TranslatedBlock:
    block: Block
    thai: str
    final: bool


@dataclass(frozen=True)
class FrameResult:
    frame_id: int
    blocks: tuple[TranslatedBlock, ...]
    capture_width: int
    capture_height: int
    ocr_ms: float = 0.0
    # The captured frame this OCR result came from (BGR numpy array, or
    # None if the caller doesn't need it -- mode A overlay doesn't, mode B
    # mirror does). Kept as a reference, not copied, per spec section 3A:
    # "แชร์ผ่าน reference/copy-on-write ไม่จับภาพซ้ำ". A consumer that
    # mutates it (e.g. drawing over it) MUST copy first.
    frame_image: Any = None


@dataclass(frozen=True)
class StatusUpdate:
    ocr_ms: float
    translate_ms: float
    block_count: int
    active_tier: str  # "1" or "1/2"


def _default_capture_factory(monitor, cfg: dict):
    from gametrans.capture import create_backend

    backend_name = cfg.get("capture", {}).get("backend", "auto")
    return create_backend(backend_name, monitor_index=monitor.index)


def _default_ocr_func(frame, cfg: dict) -> list[OcrLine]:
    from gametrans.ocr import run_ocr

    return run_ocr(frame, cfg)


def _default_translator_factory(cfg: dict):
    from gametrans.translate_fast import NllbCTranslator

    fast_cfg = cfg.get("fast", {})
    lang_cfg = cfg.get("language", {})
    return NllbCTranslator(
        model_dir=fast_cfg.get("model_dir", "models/fast/nllb200-600m-int8"),
        source_lang=lang_cfg.get("source", "en") if lang_cfg.get("source", "auto") != "auto" else "en",
        target_lang=lang_cfg.get("target", "th"),
        device=fast_cfg.get("device", "auto"),
        beam_size=int(fast_cfg.get("beam_size", 1)),
    )


class Pipeline:
    def __init__(
        self,
        cfg: dict,
        on_frame: Callable[[FrameResult], None],
        on_status: Callable[[StatusUpdate], None],
        *,
        store: Optional[Store] = None,
        capture_factory: Callable = _default_capture_factory,
        ocr_func: Callable = _default_ocr_func,
        fast_translator_factory: Callable = _default_translator_factory,
        refine_translator: Optional[Any] = None,
        watchdog: Optional[Any] = None,
    ) -> None:
        self.cfg = cfg
        self.on_frame = on_frame
        self.on_status = on_status
        if store is not None:
            # An injected store may already be loaded/configured (e.g. a
            # test that called set_override() before construction) --
            # calling .load() here would silently wipe that in-memory
            # state by reloading from disk. Only a store WE create needs
            # an initial load.
            self.store = store
        else:
            self.store = Store(
                overrides_path=cfg.get("text", {}).get("overrides_path", "overrides.json"),
                glossary_path=cfg.get("text", {}).get("glossary_path", "glossary.json"),
                cache_path=cfg.get("cache", {}).get("path", "translation_cache.json"),
                max_entries=int(cfg.get("cache", {}).get("max_entries", 8000)),
            )
            self.store.load()

        self._capture_factory = capture_factory
        self._ocr_func = ocr_func
        self._fast_translator_factory = fast_translator_factory
        self._refine_translator = refine_translator
        self._watchdog = watchdog

        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._translate_queue: "queue.Queue[str]" = queue.Queue()
        self._pending: set[str] = set()
        self._pending_lock = threading.Lock()

        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[FrameResult] = None
        self._frame_counter = 0

    # ------------------------------------------------------------- control

    def start(self, monitor) -> None:
        self._stop_event.clear()
        t1 = threading.Thread(target=self._capture_ocr_loop, args=(monitor,), name="capture-ocr", daemon=True)
        t2 = threading.Thread(target=self._fast_translate_loop, name="fast-translate", daemon=True)
        self._threads = [t1, t2]
        for t in self._threads:
            t.start()

    def stop(self, timeout_s: float = 3.0) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=timeout_s)
        self._threads = []
        self.store.save()

    def snapshot(self) -> Optional[FrameResult]:
        with self._frame_lock:
            return self._latest_frame

    # --------------------------------------------------------- capture+ocr

    def _capture_ocr_loop(self, monitor) -> None:
        try:
            backend = self._capture_factory(monitor, self.cfg)
        except Exception as exc:  # noqa: BLE001 - report, thread must exit cleanly
            logger.error("pipeline: capture backend failed to start: %s", exc)
            return

        glossary = self.store.get_glossary()
        prev_blocks: list[Block] = []
        try:
            while not self._stop_event.is_set():
                if self._watchdog is not None:
                    self._watchdog.heartbeat("capture_ocr")
                t0 = time.perf_counter()
                frame = backend.grab(monitor.left, monitor.top, monitor.width, monitor.height)
                if frame is None:
                    self._stop_event.wait(0.01)
                    continue

                try:
                    lines = self._ocr_func(frame, self.cfg)
                except Exception as exc:  # noqa: BLE001 - one bad frame must not kill the loop
                    logger.warning("pipeline: OCR failed on a frame (%s)", exc)
                    self._stop_event.wait(0.05)
                    continue
                ocr_ms = (time.perf_counter() - t0) * 1000

                cleaned = [
                    OcrLine(x1=ln.x1, y1=ln.y1, x2=ln.x2, y2=ln.y2, text=clean_text(ln.text), score=ln.score)
                    for ln in lines
                ]
                cur_blocks = merge_lines(cleaned, self.cfg)
                now = time.monotonic()
                prev_blocks = track_blocks(prev_blocks, cur_blocks, now, self.cfg)

                translated: list[TranslatedBlock] = []
                for block in prev_blocks:
                    entry = self.store.lookup(block.text)
                    if entry is not None:
                        translated.append(TranslatedBlock(block=block, thai=entry.thai, final=entry.final))
                        continue

                    prepared = prepare(block.text, glossary)
                    if prepared.skip:
                        # nothing translatable (pure numbers/symbols) -- show as-is, no queueing
                        self.store.put(block.text, block.text, tier=0, final=True)
                        translated.append(TranslatedBlock(block=block, thai=block.text, final=True))
                        continue

                    self._enqueue_translation(block.text)
                    translated.append(TranslatedBlock(block=block, thai=block.text, final=False))

                self._frame_counter += 1
                result = FrameResult(
                    frame_id=self._frame_counter,
                    blocks=tuple(translated),
                    capture_width=monitor.width,
                    capture_height=monitor.height,
                    ocr_ms=ocr_ms,
                    frame_image=frame,
                )
                with self._frame_lock:
                    self._latest_frame = result
                self.on_frame(result)
                self.on_status(StatusUpdate(ocr_ms=ocr_ms, translate_ms=0.0, block_count=len(prev_blocks), active_tier="1"))
        finally:
            backend.close()

    # ------------------------------------------------------- fast-translate

    def _enqueue_translation(self, text: str) -> None:
        with self._pending_lock:
            if text in self._pending:
                return
            self._pending.add(text)
        self._translate_queue.put(text)

    def _fast_translate_loop(self) -> None:
        try:
            translator = self._fast_translator_factory(self.cfg)
        except Exception as exc:  # noqa: BLE001 - tier 1 unavailable must not kill the app
            logger.error("pipeline: tier-1 translator failed to load: %s", exc)
            return

        max_batch = int(self.cfg.get("fast", {}).get("max_batch", 16))
        glossary = self.store.get_glossary()

        while not self._stop_event.is_set():
            if self._watchdog is not None:
                self._watchdog.heartbeat("fast_translate")
            try:
                text = self._translate_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            batch = [text]
            while len(batch) < max_batch:
                try:
                    batch.append(self._translate_queue.get_nowait())
                except queue.Empty:
                    break

            prepared_list = [prepare(t, glossary) for t in batch]
            try:
                raw_outputs = translator.translate([p.text for p in prepared_list])
            except Exception as exc:  # noqa: BLE001 - one failed batch must not kill the loop
                logger.warning("pipeline: tier-1 translate failed for a batch (%s)", exc)
                raw_outputs = None

            for i, t in enumerate(batch):
                with self._pending_lock:
                    self._pending.discard(t)
                if raw_outputs is None:
                    continue
                restored = prepared_list[i].restore(raw_outputs[i])
                result = check_translation(t, restored)
                if result.ok:
                    self.store.put(t, restored, tier=1, final=False)
                else:
                    logger.debug("pipeline: guard rejected tier-1 output for %r (%s)", t, result.reason)
                    # store the original text as a final fallback so we stop
                    # retrying every frame (spec section 8.6: never show junk)
                    self.store.put(t, t, tier=0, final=True)
