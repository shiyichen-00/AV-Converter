"""
版本 v1.0.1
本程序由耿浩完成于2025年8月12日。
音视频格式转换是一个常见的需求。然而，大多数格式转换工具依赖在线服务，存在数据安全风险。
为解决这一问题，本人开发了 AV Converter，一款高效、安全的本地音视频格式转换软件。
AV Converter  - 使用 PySideAV Converter6 和 ffmpeg 的 GUI 应用程序
功能：
- 从磁盘中选择音频/视频文件
- 显示元数据（文件大小、时长、音频采样率、视频帧率、流信息）- ffmpeg 和 ffprobe
- 选择输出格式（mp4、webm、mkv、mp3、wav、mov）
- 选择视频分辨率预设（1080p、4K、2K、720p、保持原分辨率、自定义）
- 选择视频编码器（libx264、libx265、vp9、复制）
- 选择音频编码器（aac、libmp3lame、opus、复制）
- 视频的 CRF/质量滑块（适用于 x264/x265/vp9）
- 音频比特率选择器
- 可选的缩放因子或目标分辨率
- 开始转换，显示进度和日志

要求：
- Python 3.8+
- 已安装 PySide6（通过 pip install PySide6 安装）
- ffmpeg 和 ffprobe 在 PATH 中可用

"""

import sys
import json
import shutil
import subprocess
import os
import math
from pathlib import Path
from typing import Optional, Dict

from PySide6.QtCore import (Qt, QThread, Signal, Slot)
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFileDialog, QComboBox, QTextEdit, QProgressBar, QSlider, QFormLayout,
    QSpinBox, QLineEdit, QMessageBox, QSizePolicy
)


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def run_cmd(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def probe_media(path: str) -> Dict:
    """Use ffprobe to get json metadata."""
    if not which("ffprobe"):
        raise FileNotFoundError("ffprobe not found in PATH. Please install ffmpeg.")
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path
    ]
    proc = run_cmd(cmd)
    if proc.returncode != 0:
        # raise with stderr
        raise RuntimeError(f"ffprobe failed: {proc.stderr}")
    return json.loads(proc.stdout)


def readable_size(n: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024.0:
            return f"{n:3.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


class FFmpegWorker(QThread):
    progress = Signal(float)       # 0..100
    log = Signal(str)
    finished = Signal(bool, str)  # success, output_path

    def __init__(self, ffmpeg_cmd: list, duration_seconds: Optional[float]):
        super().__init__()
        self.cmd = ffmpeg_cmd
        self.duration = duration_seconds
        self._stopped = False

    def run(self):
        # Run ffmpeg and parse progress from stderr
        self.log.emit('Running: ' + ' '.join(self.cmd))
        proc = subprocess.Popen(self.cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if proc.stderr is None:
            self.log.emit('ffmpeg started with no stderr')
            proc.wait()
            ok = proc.returncode == 0
            self.finished.emit(ok, '')
            return

        # parse lines
        output_path = ''
        last_percent = 0.0
        while True:
            line = proc.stderr.readline()
            if not line:
                break
            line = line.strip()
            self.log.emit(line)
            # Look for progress time=HH:MM:SS.msec
            if line.startswith('frame=') or 'time=' in line:
                # try to extract time=...
                parts = line.split()
                tpart = None
                for p in parts:
                    if p.startswith('time='):
                        tpart = p.split('=', 1)[1]
                        break
                if tpart and self.duration and self.duration > 0:
                    # parse time to seconds
                    try:
                        h, m, s = tpart.split(':')
                        s = float(s)
                        secs = int(h) * 3600 + int(m) * 60 + s
                        pct = min(100.0, max(0.0, (secs / self.duration) * 100.0))
                        # smooth
                        if pct - last_percent >= 0.5:
                            last_percent = pct
                            self.progress.emit(pct)
                    except Exception:
                        pass
            # capture output filename from command args (best-effort)
            # Not reliable here; we'll emit path via finished signal when done

        proc.wait()
        ok = proc.returncode == 0
        self.progress.emit(100.0)
        self.finished.emit(ok, '')


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('AV Converter')
        self.resize(600, 650)

        self.input_path: Optional[str] = None
        self.metadata: Optional[Dict] = None
        self.duration_seconds: Optional[float] = None

        # Top layout: file selection and metadata
        self.btn_select = QPushButton('选择文件')
        self.btn_select.clicked.connect(self.select_file)
        self.lbl_path = QLineEdit('')
        self.lbl_path.setReadOnly(True)

        top_h = QHBoxLayout()
        top_h.addWidget(self.btn_select)
        top_h.addWidget(self.lbl_path)

        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        self.meta_text.setMinimumHeight(200)

        # Conversion options
        form = QFormLayout()

        self.combo_outfmt = QComboBox()
        self.combo_outfmt.addItems(['mp4', 'mkv', 'webm', 'mov', 'mp3', 'wav', 'aac'])

        self.combo_vcodec = QComboBox()
        self.combo_vcodec.addItems(['libx264','libx265','vp9','copy'])

        self.combo_acodec = QComboBox()
        self.combo_acodec.addItems(['aac', 'libmp3lame', 'libopus','copy'])

        self.combo_res = QComboBox()
        self.combo_res.addItems([ '1920x1080 (1080p)','3840x2160 (4K)', '2560x1440 (2K)','1280x720 (720p)','keep','custom'])
        self.combo_res.currentIndexChanged.connect(self.on_res_change)
        self.custom_res = QLineEdit()
        self.custom_res.setPlaceholderText('非标准分辨率需保持原视频高宽比')
        self.custom_res.setEnabled(False)

        self.slider_crf = QSlider(Qt.Horizontal)
        self.slider_crf.setRange(0, 51)
        self.slider_crf.setValue(23)
        self.lbl_crf = QLabel('CRF: 23')
        self.slider_crf.valueChanged.connect(lambda v: self.lbl_crf.setText(f'CRF: {v}'))

        self.spin_abitrate = QSpinBox()
        self.spin_abitrate.setRange(32, 512)
        self.spin_abitrate.setValue(128)
        self.spin_abitrate.setSuffix(' kbps')

        self.combo_preset = QComboBox()
        self.combo_preset.addItems(['ultrafast','superfast','veryfast','faster','fast','medium','slow','veryslow'])
        self.combo_preset.setCurrentText('fast')

        form.addRow('输出格式', self.combo_outfmt)
        form.addRow('视频编码', self.combo_vcodec)
        form.addRow('音频编码', self.combo_acodec)
        form.addRow('分辨率', self.combo_res)
        form.addRow('自定义分辨率', self.custom_res)
        form.addRow(self.lbl_crf, self.slider_crf)
        form.addRow('编码预设', self.combo_preset)
        form.addRow('音频码率', self.spin_abitrate)

        # Controls
        self.btn_start = QPushButton('开始转换')
        self.btn_start.clicked.connect(self.start_conversion)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        controls_h = QHBoxLayout()
        controls_h.addLayout(form)

        right_v = QVBoxLayout()
        right_v.addWidget(self.btn_start)
        right_v.addWidget(self.progress)
        right_v.addStretch()

        controls_h.addLayout(right_v)

        # Main layout
        layout = QVBoxLayout()
        layout.addLayout(top_h)
        layout.addWidget(QLabel('文件信息'))
        layout.addWidget(self.meta_text)
        layout.addLayout(controls_h)
        layout.addWidget(QLabel('日志 / ffmpeg 输出'))
        layout.addWidget(self.log_text)

        self.setLayout(layout)

        # Worker thread
        self.worker: Optional[FFmpegWorker] = None

    @Slot()
    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择音频或视频文件', str(Path.home()))
        if not path:
            return
        self.input_path = path
        self.lbl_path.setText(path)
        self.load_metadata()

    def load_metadata(self):
        try:
            md = probe_media(self.input_path)
        except Exception as e:
            QMessageBox.critical(self, '错误', f'读取文件信息失败：{e}')
            return
        self.metadata = md
        # parse useful info
        fmt = md.get('format', {})
        size = int(fmt.get('size', 0)) if fmt.get('size') else 0
        duration = float(fmt.get('duration')) if fmt.get('duration') else None
        self.duration_seconds = duration
        out = []
        out.append(f"文件: {self.input_path}")
        out.append(f"大小: {readable_size(size)} ({size} bytes)")
        if duration:
            out.append(f"时长: {duration:.3f} 秒")
        if fmt.get('bit_rate'):
            try:
                out.append(f"平均比特率: {int(fmt.get('bit_rate'))/1000:.1f} kbps")
            except Exception:
                pass
        streams = md.get('streams', [])
        for s in streams:
            t = s.get('codec_type')
            if t == 'video':
                out.append('-------------------- 视频流 --------------------')
                out.append(f"编码: {s.get('codec_name')}")
                out.append(f"分辨率: {s.get('width')}x{s.get('height')}")
                if s.get('r_frame_rate'):
                    # frame rate like 30000/1001
                    fr = s.get('r_frame_rate')
                    try:
                        num, den = fr.split('/')
                        fps = float(num) / float(den) if float(den) != 0 else 0
                        out.append(f"帧率: {fps:.3f} fps")
                    except Exception:
                        out.append(f"帧率: {fr}")
            elif t == 'audio':
                out.append('-------------------- 音频流 --------------------')
                out.append(f"编码: {s.get('codec_name')}")
                if s.get('sample_rate'):
                    out.append(f"采样率: {s.get('sample_rate')} Hz")
                if s.get('channels'):
                    out.append(f"声道: {s.get('channels')}")
        self.meta_text.setText('\n'.join(out))

    @Slot()
    def on_res_change(self, idx):
        text = self.combo_res.currentText()
        self.custom_res.setEnabled('custom' in text)

    @Slot()
    def start_conversion(self):
        if not self.input_path:
            QMessageBox.warning(self, '提示', '请先选择文件')
            return
        outfmt = self.combo_outfmt.currentText()
        vcodec = self.combo_vcodec.currentText()
        acodec = self.combo_acodec.currentText()
        res_choice = self.combo_res.currentText()
        custom_res = self.custom_res.text().strip()
        crf = self.slider_crf.value()
        preset = self.combo_preset.currentText()
        abitrate = self.spin_abitrate.value()

        in_path = Path(self.input_path)
        # create output path next to input
        base = in_path.with_suffix('')
        out_ext = '.' + outfmt
        out_path = str(base) + '_converted' + out_ext

        # Build ffmpeg command
        if not which('ffmpeg'):
            QMessageBox.critical(self, '错误', 'ffmpeg 未安装或不在 PATH 中')
            return

        cmd = ['ffmpeg', '-y', '-i', str(in_path)]

        # Video handling
        has_video = any(s.get('codec_type') == 'video' for s in (self.metadata or {}).get('streams', []))
        if has_video:
            # resolution
            if res_choice != 'keep' and 'custom' not in res_choice:
                # extract like '1920x1080 (1080p)'
                target = res_choice.split()[0]
                cmd.extend(['-vf', f"scale={target.split('x')[0]}:{target.split('x')[1]}"])
            elif 'custom' in res_choice and custom_res:
                cmd.extend(['-vf', f"scale={custom_res}"])

            # video codec
            if vcodec != 'copy':
                cmd.extend(['-c:v', vcodec])
                # add crf for x264/x265/vp9
                if vcodec in ('libx264', 'libx265', 'vp9'):
                    cmd.extend(['-crf', str(crf), '-preset', preset])
            else:
                cmd.extend(['-c:v', 'copy'])
        else:
            # remove video stream for audio-only outputs
            if outfmt in ('mp3', 'wav', 'aac'):
                cmd.extend(['-vn'])

        # audio handling
        has_audio = any(s.get('codec_type') == 'audio' for s in (self.metadata or {}).get('streams', []))
        if has_audio:
            if acodec != 'copy':
                cmd.extend(['-c:a', acodec, '-b:a', f'{abitrate}k'])
            else:
                cmd.extend(['-c:a', 'copy'])
        else:
            # no audio stream, for audio outputs we need to handle differently
            if outfmt in ('mp3', 'wav', 'aac'):
                QMessageBox.critical(self, '错误', '所选文件没有音频流')
                return

        cmd.append(out_path)

        # clear logs
        self.log_text.clear()
        self.progress.setValue(0)

        # start worker thread
        self.worker = FFmpegWorker(cmd, self.duration_seconds)
        self.worker.progress.connect(lambda v: self.progress.setValue(int(v)))
        self.worker.log.connect(lambda s: self.append_log(s))
        self.worker.finished.connect(lambda ok, p: self.on_done(ok, out_path))
        self.worker.start()

    def append_log(self, s: str):
        self.log_text.append(s)
        # auto-scroll
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def on_done(self, ok: bool, out_path: str):
        if ok:
            QMessageBox.information(self, '完成', f'转换成功: {out_path}')
            # refresh metadata for output
        else:
            QMessageBox.critical(self, '失败', '转换过程中出现错误，请查看日志')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
