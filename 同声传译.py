# -*- coding:utf-8 -*-
# 本人开发的灵犀播伴是一款基于人工智能和自然语言处理技术的实时翻译软件，专为跨境直播设计，
# 旨在打破语言壁垒，提升互动效率。它通过实时语音识别、精准翻译和弹幕自动回复功能，帮助主播与全球观众顺畅沟通，降低对专业翻译人员的需求，从而显著减少人力成本。
# 软件支持多语言互译，结合行业术语库和文化适配模块，减少翻译误解，确保产品信息准确传达，助力商家触达海外市场。
#版本v1.0.2
#耿浩 写于2025年4月13日
# -*- coding:utf-8 -*-
import sys
import os
import base64
import datetime
import hashlib
import hmac
import ssl
import time
import json
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time

import websocket  # pip install websocket-client
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTextEdit, QLabel, QMessageBox, QStatusBar,
                             QComboBox, QSpacerItem, QSizePolicy)
from PySide6.QtCore import QThread, QObject, Qt, QPoint,Signal  # Added QPoint
from PySide6.QtGui import QTextCursor, QScreen
import sounddevice as sd  # pip install sounddevice
import numpy as np  # pip install numpy
# --- 配置讯飞 API ---
APPID = '358b7131'  # 请替换为你的 APPID
APISecret = 'ZDRlYmJlYmZlZmU2ZTk0YWY4NGUwY2M4'  # 请替换为你的 APISecret
APIKey = 'b21f234130086485b19eefc7a327a936'  # 请替换为你的 APIKey
# --- 配置结束 ---

# --- 音频参数 ---
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 1280
# --- 音频参数结束 ---

# --- 讯飞 WebSocket 状态常量 ---
STATUS_FIRST_FRAME = 0
STATUS_CONTINUE_FRAME = 1
STATUS_LAST_FRAME = 2
# --- 状态常量结束 ---

# --- 文件保存路径 ---
OUTPUT_DIR = "output"
TEXT_DIR = os.path.join(OUTPUT_DIR, "text")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
ASR_FILE = os.path.join(TEXT_DIR, "asr.txt")
TRANS_FILE = os.path.join(TEXT_DIR, "trans.txt")
# --- 文件路径结束 ---

try:
    from tool.pcm2wav import pcm_2_wav

    PCM2WAV_AVAILABLE = True
except ImportError:
    PCM2WAV_AVAILABLE = False
    print("警告: 'tool.pcm2wav' 模块未找到或无法导入。PCM到WAV的转换功能将不可用。")


    def pcm_2_wav(pcm_path, wav_path):  # Placeholder
        print(f"错误: pcm_2_wav 函数未加载。无法将 {pcm_path} 转换为 {wav_path}。")


class TranslationWorker(QObject):  # No changes to this class
    translation_pair_received = Signal(str, str, bool)
    audio_chunk_received = Signal(bytes)
    status_update = Signal(str)
    error_occurred = Signal(str)
    finished = Signal()
    raw_audio_saved = Signal(str)
    wav_audio_saved = Signal(str)

    def __init__(self, appid, apisecret, apikey, from_lang="zh_cn", to_lang="en"):
        super().__init__()
        self.appid = appid
        self.apisecret = apisecret
        self.apikey = apikey
        self.from_lang_code = from_lang
        self.to_lang_code = to_lang
        self.host = "ws-api.xf-yun.com"
        self.request_uri = "/v1/private/simult_interpretation"
        self.url = "ws://" + self.host + self.request_uri
        self.ws = None
        self.audio_stream = None
        self.is_running = False
        self._status = STATUS_FIRST_FRAME
        self.sid = ""

        self.pcm_file_handle = None
        self.pcm_file_path = ""
        self.wav_file_path = ""

        self.api_from_lang_trans = "cn" if self.from_lang_code == "zh_cn" else "en"
        self.api_to_lang_trans = "en" if self.to_lang_code == "en" else "cn"
        self.api_vcn_tts = "x2_john" if self.api_to_lang_trans == "en" else "x2_xiaoguo"

        print(f"Worker Init: UI FromLang={self.from_lang_code}, UI ToLang={self.to_lang_code}")
        print(f"  ASR Params: ist.language=zh_cn (固定), ist.accent=mandarin (固定)")
        print(
            f"  Translation Params: streamtrans.from={self.api_from_lang_trans}, streamtrans.to={self.api_to_lang_trans}")
        print(f"  TTS Params: tts.vcn={self.api_vcn_tts}")

        os.makedirs(TEXT_DIR, exist_ok=True)
        os.makedirs(AUDIO_DIR, exist_ok=True)

    def setup_files(self):
        try:
            timestamp = datetime.datetime.now().strftime("%m%d_%H%M%S")
            base_filename = f"translation_output_{timestamp}"
            self.pcm_file_path = os.path.join(AUDIO_DIR, f"{base_filename}.pcm")
            self.wav_file_path = os.path.join(AUDIO_DIR, f"{base_filename}.wav")
            self.pcm_file_handle = open(self.pcm_file_path, "wb")
            print(f"PCM 音频输出文件已打开: {self.pcm_file_path}")
            return True
        except IOError as e:
            self.error_occurred.emit(f"无法打开输出文件: {e}")
            self.cleanup_files()
            return False

    def create_url(self):
        now = datetime.datetime.now()
        date = format_date_time(time.mktime(now.timetuple()))
        signature_origin = f"host: {self.host}\n"
        signature_origin += f"date: {date}\n"
        signature_origin += f"GET {self.request_uri} HTTP/1.1"
        signature_sha = hmac.new(self.apisecret.encode('utf-8'), signature_origin.encode('utf-8'),
                                 digestmod=hashlib.sha256).digest()
        signature_sha_base64 = base64.b64encode(signature_sha).decode(encoding='utf-8')
        authorization_origin = f'api_key="{self.apikey}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha_base64}"'
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
        v = {
            "authorization": authorization, "date": date, "host": self.host,
            "serviceId": "simult_interpretation"
        }
        return self.url + '?' + urlencode(v)

    def create_params(self, status, audio_data):
        param = {
            "header": {"app_id": self.appid, "status": status},
            "parameter": {
                "ist": {"accent": "mandarin", "domain": "ist_ed_open", "language": "zh_cn", "vto": 15000,
                        "eos": 150000},
                "streamtrans": {"from": self.api_from_lang_trans, "to": self.api_to_lang_trans},
                "tts": {
                    "vcn": self.api_vcn_tts,
                    "tts_results": {"encoding": "raw", "sample_rate": SAMPLE_RATE, "channels": CHANNELS,
                                    "bit_depth": 16, "frame_size": 0}
                }
            },
            "payload": {
                "data": {"audio": base64.b64encode(audio_data).decode('utf-8'), "encoding": "raw",
                         "sample_rate": SAMPLE_RATE, "seq": 1, "status": status}
            }
        }
        return json.dumps(param)

    def on_message(self, ws, message):
        try:
            msg = json.loads(message)
            header = msg.get("header", {})
            payload = msg.get("payload", {})
            code = header.get("code")
            xf_status = header.get("status", -1)
            self.sid = header.get("sid", self.sid)

            if code != 0:
                errMsg = f"讯飞 API 错误: code={code}, message={header.get('message', 'N/A')}, sid={self.sid}"
                print(errMsg);
                self.error_occurred.emit(errMsg)
                return

            if payload and "streamtrans_results" in payload:
                trans_res = payload.get("streamtrans_results", {})
                if trans_res and "text" in trans_res:
                    result_text_bytes = base64.b64decode(trans_res["text"])
                    result_text_str = result_text_bytes.decode('utf-8')
                    if result_text_str:
                        try:
                            inner_data = json.loads(result_text_str)
                            src = inner_data.get("src", "")
                            dst = inner_data.get("dst", "")
                            is_partial_segment = (xf_status != 2)
                            if src or dst:
                                self.translation_pair_received.emit(src, dst, is_partial_segment)
                        except json.JSONDecodeError:
                            print(f"警告: StreamTrans 内部结果不是预期的 JSON: {result_text_str}")
                        except Exception as e:
                            print(f"解析 StreamTrans 内部 JSON 时出错: {e}")

            if payload and "tts_results" in payload:
                tts_res = payload.get("tts_results", {})
                if tts_res and "audio" in tts_res:
                    audio_bytes = base64.b64decode(tts_res["audio"])
                    if audio_bytes:
                        self.audio_chunk_received.emit(audio_bytes)
                        if self.pcm_file_handle:
                            try:
                                self.pcm_file_handle.write(audio_bytes); self.pcm_file_handle.flush()
                            except Exception as e:
                                print(f"写入 PCM 音频数据时出错: {e}")
        except Exception as e:
            errMsg = f"处理消息时发生意外错误: {e}\n消息内容: {message}"
            print(errMsg);
            self.error_occurred.emit(errMsg)

    def on_error(self, ws, error):
        if isinstance(error, websocket.WebSocketConnectionClosedException):
            print(f"WebSocket 连接已关闭 (on_error): {error}")
        else:
            errMsg = f"WebSocket 错误 (on_error): {error}"; print(errMsg); self.error_occurred.emit(errMsg)
        self.is_running = False

    def on_close(self, ws, close_status_code, close_msg):
        msg = f"WebSocket 连接已关闭: code={close_status_code}, msg={close_msg}";
        print(msg)
        self.is_running = False;
        self.status_update.emit("连接已关闭")
        self.cleanup();
        self.finished.emit()

    def on_open(self, ws):
        self.status_update.emit("连接成功，正在初始化音频...");
        self.is_running = True;
        self._status = STATUS_FIRST_FRAME
        try:
            print("可用的输入设备:", sd.query_devices(kind='input'))
            self.audio_stream = sd.InputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, channels=CHANNELS,
                                               dtype='int16', callback=self.audio_callback)
            self.audio_stream.start();
            self.status_update.emit("麦克风已启动，正在录音和传输...")
        except Exception as e:
            errMsg = f"启动音频流失败: {e}. 请检查麦克风设备和权限。";
            print(errMsg);
            self.error_occurred.emit(errMsg)
            if self.ws:
                self.ws.close()
            else:
                self.cleanup(); self.finished.emit()

    def audio_callback(self, indata, frames, time_info, status_flags):
        if not self.is_running or not self.ws or not self.ws.sock or not self.ws.sock.connected: return
        if status_flags: print(f"音频回调状态警告: {status_flags}", file=sys.stderr)
        audio_data = indata.tobytes()
        try:
            params_json = self.create_params(self._status, audio_data);
            self.ws.send(params_json)
            if self._status == STATUS_FIRST_FRAME: self._status = STATUS_CONTINUE_FRAME
        except websocket.WebSocketConnectionClosedException:
            print("尝试发送音频数据时发现 WebSocket 已关闭。"); self.is_running = False
        except Exception as e:
            print(f"发送音频数据时出错: {e}")

    def run(self):
        if not all([self.appid, self.apikey, self.apisecret]) or \
                self.appid == 'YOUR_APPID' or self.apikey == 'YOUR_APIKEY' or self.apisecret == 'YOUR_APISECRET':
            self.error_occurred.emit("错误：请先在代码中正确配置讯飞 API 凭证！");
            self.finished.emit();
            return
        if not self.setup_files(): self.finished.emit(); return
        ws_url = self.create_url();
        self.status_update.emit(f"正在连接到 {self.host}...")
        self.ws = websocket.WebSocketApp(ws_url, on_message=self.on_message, on_error=self.on_error,
                                         on_close=self.on_close, on_open=self.on_open)
        try:
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        except Exception as e:
            self.error_occurred.emit(f"WebSocket run_forever 启动失败: {e}"); self.cleanup(); self.finished.emit()
        print("WebSocket run_forever 循环已结束。")

    def stop(self):
        if not self.is_running and not (self.ws and self.ws.sock and self.ws.sock.connected):
            print("停止请求，但 Worker 未运行或 WebSocket 已关闭。");
            if not self.is_running: self.cleanup(); return
        self.status_update.emit("正在停止录音和翻译...");
        self.is_running = False
        if self.audio_stream:
            try:
                if not self.audio_stream.stopped: self.audio_stream.stop()
                if not self.audio_stream.closed: self.audio_stream.close()
                print("音频流已停止并关闭。")
            except Exception as e:
                print(f"停止音频流时出错: {e}")
            self.audio_stream = None
        if self.ws and self.ws.sock and self.ws.sock.connected:
            try:
                self.ws.send(self.create_params(STATUS_LAST_FRAME, b'')); print("已发送最后一帧。")
            except Exception as e:
                print(f"发送最后一帧信号时出错: {e}")
            finally:
                try:
                    self.ws.close(); print("WebSocket 关闭请求已发送。")
                except Exception as e:
                    print(f"关闭 WebSocket 时出错: {e}"); self.cleanup()
        else:
            print("WebSocket 不可用或已关闭，跳过发送最后一帧。直接清理。"); self.cleanup()

    def cleanup_files(self):
        if self.pcm_file_handle:
            try:
                if not self.pcm_file_handle.closed: self.pcm_file_handle.close()
                print(f"PCM 音频文件已关闭: {self.pcm_file_path}")
                if os.path.exists(self.pcm_file_path) and os.path.getsize(self.pcm_file_path) > 0:
                    self.raw_audio_saved.emit(self.pcm_file_path)
                    if PCM2WAV_AVAILABLE:
                        print(f"正在将 {self.pcm_file_path} 转换为 {self.wav_file_path}...")
                        try:
                            pcm_2_wav(self.pcm_file_path, self.wav_file_path); print(
                                f"WAV 音频文件已成功生成: {self.wav_file_path}"); self.wav_audio_saved.emit(
                                self.wav_file_path)
                        except Exception as e_conv:
                            errMsg = f"PCM 到 WAV 转换失败: {e_conv}"; print(errMsg); self.error_occurred.emit(errMsg)
                    else:
                        print("PCM 到 WAV 转换工具不可用。")
                elif os.path.exists(self.pcm_file_path) and os.path.getsize(self.pcm_file_path) == 0:
                    print(f"PCM 文件 {self.pcm_file_path} 为空，跳过 WAV 转换。")
            except Exception as e:
                print(f"关闭 PCM 文件或转换 WAV 时出错: {e}")
            self.pcm_file_handle = None

    def cleanup(self):
        print("执行 Worker 清理...")
        if self.audio_stream:
            try:
                if not self.audio_stream.stopped: self.audio_stream.stop()
                if not self.audio_stream.closed: self.audio_stream.close()
            except Exception as e:
                print(f"清理音频流时出错: {e}")
            self.audio_stream = None
        self.ws = None;
        self.cleanup_files();
        self.is_running = False;
        print("Worker 清理完成。")


class OverlayWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # WA_TransparentForMouseEvents is NOT set, to allow dragging

        self._dragging = False
        self._offset = QPoint()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.source_overlay_label = QLabel("原文: 等待输入...")
        self.translation_overlay_label = QLabel("译文: 等待翻译...")

        label_style = """
            QLabel {
                background-color: rgba(0, 0, 0, 170);
                color: white;
                font-size: 16pt;
                padding: 8px;
                border-radius: 5px;
                min-height: 40px; 
            }
        """
        self.source_overlay_label.setStyleSheet(label_style)
        self.translation_overlay_label.setStyleSheet(label_style)

        self.source_overlay_label.setWordWrap(True)
        self.translation_overlay_label.setWordWrap(True)

        self.source_overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.translation_overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.source_overlay_label)
        layout.addWidget(self.translation_overlay_label)
        self.setLayout(layout)

        self.set_default_geometry_and_size()

    def set_default_geometry_and_size(self):
        primary_screen = QApplication.primaryScreen()
        if primary_screen:
            screen_geometry = primary_screen.geometry()
            overlay_width = int(screen_geometry.width() * 0.8)
            # Initial height, adjustSize might change it later based on content
            overlay_height = 150
            self.setFixedWidth(overlay_width)  # Set a fixed width
            self.setFixedHeight(overlay_height)  # Set an initial fixed height

            x = int((screen_geometry.width() - overlay_width) / 2)
            y = screen_geometry.height() - self.height() - 50  # Use self.height() after setting it
            self.move(x, y)
        else:
            self.resize(800, 150)
        self.adjustSize()  # Adjust height to content after setting width and initial text

    def update_text(self, source_text, translation_text):
        self.source_overlay_label.setText(f"原文: {source_text}" if source_text else "原文: ...")
        self.translation_overlay_label.setText(f"译文: {translation_text}" if translation_text else "译文: ...")
        self.adjustSize()  # Adjust height to fit content, width remains fixed

    def clear_text(self):
        self.source_overlay_label.setText("原文: ")
        self.translation_overlay_label.setText("译文: ")
        self.adjustSize()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            # event.globalPosition() is QPointF, self.pos() is QPoint
            self._offset = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()


class SimultaneousTranslatorApp(QWidget):  # No changes to this class other than Overlay interaction
    def __init__(self):
        super().__init__()
        self.setWindowTitle("同声传译")
        self.setGeometry(100, 100, 600, 400)

        self.language_combo = QComboBox()
        self.language_combo.addItems(["中文 -> 英文", "英文 -> 中文"])
        self.language_combo.currentIndexChanged.connect(self.update_labels_and_reset_session)

        self.start_button = QPushButton("开始录音和翻译")
        self.stop_button = QPushButton("停止");
        self.stop_button.setEnabled(False)
        self.play_button = QPushButton("播放译文");
        self.play_button.setEnabled(False)

        self.source_label = QLabel()
        self.source_text_edit = QTextEdit();
        self.source_text_edit.setReadOnly(True);
        self.source_text_edit.setMinimumHeight(180)
        self.translation_label = QLabel()
        self.translation_text_edit = QTextEdit();
        self.translation_text_edit.setReadOnly(True);
        self.translation_text_edit.setMinimumHeight(180)
        self.status_bar = QStatusBar();
        self.status_bar.showMessage("准备就绪")

        main_layout = QVBoxLayout()
        control_layout = QHBoxLayout();
        control_layout.addWidget(QLabel("翻译方向:"));
        control_layout.addWidget(self.language_combo)
        control_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        control_layout.addWidget(self.start_button);
        control_layout.addWidget(self.stop_button);
        control_layout.addWidget(self.play_button)

        text_boxes_layout = QHBoxLayout()
        source_v_layout = QVBoxLayout();
        source_v_layout.addWidget(self.source_label);
        source_v_layout.addWidget(self.source_text_edit)
        trans_v_layout = QVBoxLayout();
        trans_v_layout.addWidget(self.translation_label);
        trans_v_layout.addWidget(self.translation_text_edit)
        text_boxes_layout.addLayout(source_v_layout)
        text_boxes_layout.addLayout(trans_v_layout)

        main_layout.addLayout(control_layout)
        main_layout.addLayout(text_boxes_layout)
        main_layout.addWidget(self.status_bar)
        self.setLayout(main_layout)

        self.thread = None;
        self.worker = None
        self.accumulated_audio_for_playback = bytearray()
        self.is_playing_audio = False
        self.current_session_source_text = ""
        self.current_session_translation_text = ""

        self.overlay = OverlayWidget()

        self.start_button.clicked.connect(self.start_translation)
        self.stop_button.clicked.connect(self.stop_translation)
        self.play_button.clicked.connect(self.play_translation_audio)
        self.update_labels_and_reset_session()

    def update_labels_and_reset_session(self):
        self.update_labels()
        self.reset_session_data()

    def reset_session_data(self):
        self.accumulated_audio_for_playback.clear()
        self.play_button.setEnabled(False)
        self.current_session_source_text = ""
        self.current_session_translation_text = ""
        self.source_text_edit.clear()
        self.translation_text_edit.clear()
        self.overlay.clear_text()

    def update_labels(self):
        selected_direction = self.language_combo.currentText()
        if selected_direction == "中文 -> 英文":
            self.source_label.setText("识别原文 (中文输入):");
            self.translation_label.setText("翻译结果 (英文输出):")
        else:
            self.source_label.setText("识别原文 (固定中文识别):"); self.translation_label.setText(
                "翻译结果 (中文输出):")

    def start_translation(self):
        self.start_button.setEnabled(False);
        self.language_combo.setEnabled(False)
        self.stop_button.setEnabled(True);
        self.play_button.setEnabled(False)
        self.reset_session_data()
        self.status_bar.showMessage("正在初始化...")

        # self.overlay.set_default_geometry_and_size() # Reset position/size on start if desired
        self.overlay.clear_text()
        self.overlay.show()

        selected_direction = self.language_combo.currentText()
        from_lang_code = "zh_cn" if selected_direction == "中文 -> 英文" else "en_us"
        to_lang_code = "en" if selected_direction == "中文 -> 英文" else "cn"

        self.thread = QThread(self)
        self.worker = TranslationWorker(APPID, APISecret, APIKey, from_lang=from_lang_code, to_lang=to_lang_code)
        self.worker.moveToThread(self.thread)

        self.worker.translation_pair_received.connect(self.handle_translation_pair)
        self.worker.audio_chunk_received.connect(self.accumulate_audio_chunk_for_playback)
        self.worker.status_update.connect(self.update_status_bar)
        self.worker.error_occurred.connect(self.show_error_message_box)
        self.worker.finished.connect(self.on_worker_thread_finished)
        self.worker.raw_audio_saved.connect(lambda path: self.update_status_bar(f"PCM 音频: {os.path.basename(path)}"))
        self.worker.wav_audio_saved.connect(lambda path: self.update_status_bar(f"WAV 音频: {os.path.basename(path)}"))
        self.thread.started.connect(self.worker.run);
        self.thread.start()
        self.status_bar.showMessage("翻译线程已启动...")

    def stop_translation(self):
        if self.worker:
            self.stop_button.setEnabled(False); self.status_bar.showMessage("正在发送停止信号..."); self.worker.stop()
        else:
            self.reset_ui_after_stop()

    def handle_translation_pair(self, src_text, dst_text, is_partial):
        if src_text:
            self.current_session_source_text = src_text
            self.source_text_edit.setPlainText(self.current_session_source_text)
            self.source_text_edit.moveCursor(QTextCursor.MoveOperation.End)

        if dst_text:
            self.current_session_translation_text = dst_text
            self.translation_text_edit.setPlainText(self.current_session_translation_text)
            self.translation_text_edit.moveCursor(QTextCursor.MoveOperation.End)

        self.overlay.update_text(self.current_session_source_text, self.current_session_translation_text)

    def accumulate_audio_chunk_for_playback(self, audio_chunk):
        self.accumulated_audio_for_playback.extend(audio_chunk)
        if not self.play_button.isEnabled() and len(
                self.accumulated_audio_for_playback) > 0 and not self.is_playing_audio:
            self.play_button.setEnabled(True)

    def play_translation_audio(self):
        print("--- play_translation_audio called ---")
        if self.is_playing_audio: print("Audio already playing."); self.status_bar.showMessage(
            "音频正在播放中..."); return

        print(f"尝试播放的累积音频数据长度: {len(self.accumulated_audio_for_playback)} 字节")
        if not self.accumulated_audio_for_playback:
            print("No accumulated audio to play.");
            self.status_bar.showMessage("没有累积的译文音频可播放。");
            self.play_button.setEnabled(False);
            return

        self.is_playing_audio = True;
        self.play_button.setEnabled(False);
        self.status_bar.showMessage("正在播放译文音频...");
        print("Starting playback...")
        try:
            print("可用的输出设备 (sounddevice):")
            try:
                devices = sd.query_devices();
                output_devices = [d for d in devices if d['max_output_channels'] > 0]
                if not output_devices: print("  未找到输出设备!")
                for i, device in enumerate(output_devices): print(
                    f"  设备 {device['index']} ({device['name']}): 输出声道数={device['max_output_channels']}, 默认采样率={device['default_samplerate']}")
                default_output_idx = sd.default.device[1]
                if default_output_idx == -1:
                    print("  警告: sounddevice 报告没有默认输出设备 (-1).")
                else:
                    print(
                        f"  默认输出设备 ID: {default_output_idx}, 名称: {sd.query_devices(default_output_idx)['name']}")
            except Exception as e_dev:
                print(f"  查询音频设备时出错: {e_dev}")

            audio_data_np = np.frombuffer(bytes(self.accumulated_audio_for_playback), dtype=np.int16)
            print(f"Numpy 音频数据形状: {audio_data_np.shape}, 类型: {audio_data_np.dtype}")

            sd.play(audio_data_np, samplerate=SAMPLE_RATE, blocking=False,
                    finished_callback=self.audio_playback_finished_callback)

        except sd.PortAudioError as pae:
            errMsg = f"PortAudio 播放错误: {pae}\n请检查您的音频输出设备。"
            print(f"!!! PortAudioError: {errMsg}");
            QMessageBox.warning(self, "播放错误", errMsg)
            self.audio_playback_finished_callback()
        except Exception as e:
            errMsg = f"播放音频时发生未知错误: {e}"
            print(f"!!! Unknown playback error: {errMsg}");
            QMessageBox.warning(self, "播放错误", errMsg)
            self.audio_playback_finished_callback()

    def audio_playback_finished_callback(self):
        print(f"--- audio_playback_finished_callback called ---")
        Qt.QMetaObject.invokeMethod(self, "_playback_finished_gui_update", Qt.ConnectionType.QueuedConnection)

    def _playback_finished_gui_update(self):
        print("--- _playback_finished_gui_update (GUI thread) ---")
        self.is_playing_audio = False;
        self.status_bar.showMessage("译文音频播放结束。")
        if len(self.accumulated_audio_for_playback) > 0:
            self.play_button.setEnabled(True); print("Play button re-enabled.")
        else:
            self.play_button.setEnabled(False); print("Play button remains disabled (no audio).")

    def update_status_bar(self, message):
        self.status_bar.showMessage(message)

    def show_error_message_box(self, error_message):
        QMessageBox.critical(self, "发生错误", error_message);
        self.status_bar.showMessage(f"错误: {error_message[:70]}...")
        if self.worker and not self.worker.is_running:
            self.reset_ui_after_stop()
        elif not self.worker:
            self.reset_ui_after_stop()

    def on_worker_thread_finished(self):
        print("Worker 发出 finished 信号，准备清理线程...");
        self.status_bar.showMessage("翻译任务已完成或已中止。")
        if self.thread and self.thread.isRunning(): self.thread.quit();
        if self.thread and not self.thread.wait(3000): print("警告: QThread 未能在3秒内结束。")
        self.on_thread_finished_cleanup()

    def on_thread_finished_cleanup(self):
        print("QThread 已结束或超时，正在清理 Worker 和 Thread 对象...")
        if self.worker: self.worker.deleteLater(); self.worker = None
        if self.thread: self.thread.deleteLater(); self.thread = None
        print("Worker 和 Thread 对象已计划删除。");
        self.reset_ui_after_stop()

    def reset_ui_after_stop(self):
        self.start_button.setEnabled(True);
        self.language_combo.setEnabled(True);
        self.stop_button.setEnabled(False)
        if len(self.accumulated_audio_for_playback) > 0 and not self.is_playing_audio:
            self.play_button.setEnabled(True)
        else:
            self.play_button.setEnabled(False)
        current_msg = self.status_bar.currentMessage()
        if not self.is_playing_audio and not (self.worker and self.worker.is_running):
            if "错误" not in current_msg and "保存" not in current_msg: self.status_bar.showMessage(
                "已停止" if "停止" in current_msg or "完成" in current_msg else "准备就绪")
        self.overlay.hide()

    def closeEvent(self, event):
        print("接收到窗口关闭事件...")
        self.overlay.close()
        if self.worker and self.worker.is_running:
            reply = QMessageBox.question(self, '确认退出', '翻译仍在进行中，确定要退出吗？',
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                print("用户确认退出，正在停止翻译任务...");
                self.stop_translation()
                if self.thread and self.thread.isRunning(): self.thread.wait(500)
                event.accept()
            else:
                event.ignore()
        else:
            if self.thread and self.thread.isRunning(): print(
                "窗口关闭时，翻译线程仍在运行，尝试退出..."); self.thread.quit(); self.thread.wait(1000)
            if self.worker: self.worker.cleanup()
            event.accept()


if __name__ == "__main__":
    if APPID == 'YOUR_APPID' or APIKey == 'YOUR_APIKEY' or APISecret == 'YOUR_APISECRET' \
            or not APPID or not APIKey or not APISecret:
        try:
            app_check = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "AppName"])
        except RuntimeError:
            pass
        QMessageBox.critical(None, "API 配置错误", "请在 Python 脚本顶部配置讯飞 API 凭证！");
        sys.exit(1)

    app = QApplication(sys.argv)
    translator_app = SimultaneousTranslatorApp()
    translator_app.show()
    sys.exit(app.exec())