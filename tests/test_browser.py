from __future__ import annotations

import pytest

from clipagent.browser import FrameSample
from clipagent.browser_pipeline import detect_peaks


def _samples(values: list[float]) -> list[FrameSample]:
    return [FrameSample(timestamp=float(i * 60), motion=v, path=None) for i, v in enumerate(values)]


def test_detect_peaks_empty():
    assert detect_peaks([], count=5) == []


def test_detect_peaks_picks_most_active():
    samples = _samples([0.1, 0.2, 0.9, 0.2, 0.1])
    peaks = detect_peaks(samples, count=1, min_gap=60)
    assert len(peaks) == 1
    assert peaks[0].timestamp == 120.0


def test_detect_peaks_respects_min_gap():
    samples = _samples([0.9, 0.8, 0.85, 0.1])
    peaks = detect_peaks(samples, count=3, min_gap=200)
    timestamps = [p.timestamp for p in peaks]
    assert len(peaks) >= 1
    for i in range(len(peaks) - 1):
        assert timestamps[i + 1] - timestamps[i] >= 200


def test_detect_peaks_returns_sorted():
    samples = _samples([0.1, 0.5, 0.2, 0.9, 0.1])
    peaks = detect_peaks(samples, count=2, min_gap=60)
    assert [p.timestamp for p in peaks] == sorted(p.timestamp for p in peaks)


def test_detect_peaks_prefers_local_peak():
    # fin de séquence très active mais sans pic local (plateau) vs pic isolé
    samples = _samples([0.05, 0.8, 0.05, 0.8, 0.8, 0.8, 0.05])
    peaks = detect_peaks(samples, count=2, min_gap=60)
    assert peaks[0].timestamp == 60.0


def test_browser_module_exposes_js_and_class():
    from clipagent import browser

    assert hasattr(browser, "JS_STORYBOARD")
    assert hasattr(browser, "JS_CAPTURE")
    assert "captureStream" in browser.JS_CAPTURE
    assert "canPlayType" not in browser.JS_CAPTURE  # codecs gérés par le canal navigateur


def test_browser_pipeline_transcribe_media_requires_file(tmp_path):
    from clipagent.browser_pipeline import transcribe_media

    missing = tmp_path / "absent.webm"
    try:
        transcribe_media(missing, model_name="tiny")
    except FileNotFoundError:
        pass          # le média a bien été recherché (fichier absent)
    except Exception as exc:  # modèle Whisper indisponible (CI hors ligne)
        pytest.skip(f"Whisper indisponible : {exc.__class__.__name__}")
    else:
        pytest.fail("une transcription d'un fichier absent ne devrait pas réussir")
