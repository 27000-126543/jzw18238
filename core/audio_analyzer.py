import numpy as np
from typing import Optional, Dict, Any, Tuple


class AudioAnalyzer:
    @staticmethod
    def analyze(data: Optional[np.ndarray], sample_rate: int,
                silence_threshold_db: float = -50.0) -> Dict[str, Any]:
        result = {
            "has_data": False,
            "duration": 0.0,
            "peak": 0.0,
            "peak_db": -float("inf"),
            "rms": 0.0,
            "rms_db": -float("inf"),
            "silence_ratio": 1.0,
            "waveform": np.array([]),
            "sample_rate": sample_rate,
            "channels": 0,
            "is_silent": True,
        }

        if data is None or len(data) == 0:
            return result

        mono = data
        if data.ndim > 1:
            mono = np.mean(data, axis=1)

        result["has_data"] = True
        result["channels"] = data.shape[1] if data.ndim > 1 else 1
        result["duration"] = len(mono) / sample_rate

        peak = np.max(np.abs(mono))
        result["peak"] = float(peak)
        result["peak_db"] = float(20 * np.log10(max(peak, 1e-10)))

        rms = np.sqrt(np.mean(mono ** 2))
        result["rms"] = float(rms)
        result["rms_db"] = float(20 * np.log10(max(rms, 1e-10)))

        frame_size = int(sample_rate * 0.02)
        if frame_size < 64:
            frame_size = 64
        n_frames = len(mono) // frame_size
        if n_frames > 0:
            frames = mono[:n_frames * frame_size].reshape(n_frames, frame_size)
            frame_rms = np.sqrt(np.mean(frames ** 2, axis=1))
            frame_db = 20 * np.log10(np.maximum(frame_rms, 1e-10))
            silent_frames = np.sum(frame_db < silence_threshold_db)
            result["silence_ratio"] = float(silent_frames / n_frames)
        else:
            result["silence_ratio"] = 1.0 if rms < 10 ** (silence_threshold_db / 20) else 0.0

        result["is_silent"] = result["silence_ratio"] > 0.95

        waveform_points = 400
        if len(mono) > waveform_points:
            step = len(mono) // waveform_points
            indices = np.arange(0, len(mono), step)
            waveform = np.abs(mono[indices[:waveform_points]])
            result["waveform"] = waveform
        else:
            result["waveform"] = np.abs(mono)

        return result

    @staticmethod
    def format_db(value_db: float) -> str:
        if value_db <= -100:
            return "-∞ dB"
        return f"{value_db:.1f} dB"

    @staticmethod
    def status_label(analysis: Dict[str, Any]) -> Tuple[str, str]:
        if not analysis["has_data"]:
            return ("❌ 未采集到数据", "error")
        if analysis["is_silent"]:
            return ("⚠️ 几乎全静音", "warning")
        if analysis["silence_ratio"] > 0.5:
            return ("⚠️ 大部分静音", "warning")
        if analysis["peak_db"] > -6:
            return ("✅ 正常 (峰值高)", "good")
        if analysis["peak_db"] > -20:
            return ("✅ 正常", "good")
        return ("📊 音量偏低", "warning")
