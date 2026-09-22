"""
Unit tests for backend/core/bhashini.py — Bhashini Dhruva translation client.

Owner: M-A (Agents & Orchestration) — unit tests with mocked HTTP
Module: tests/test_bhashini.py
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from backend.core.bhashini import (
    transcribe,
    TranscriptionResult,
    translate,
    translate_to_english,
    translate_from_english,
    TranslationResult,
)


@pytest.fixture
def mock_200_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "pipelineResponse": [
            {
                "output": [
                    {
                        "source": "കൊച്ചി",
                        "target": "Kochi",
                    }
                ]
            }
        ]
    }
    return resp


@pytest.mark.asyncio
async def test_translate_same_language_noop():
    """translate('hello', 'en', 'en') -> translated=False, text unchanged."""
    res = await translate("hello", "en", "en")
    assert isinstance(res, TranslationResult)
    assert res.text == "hello"
    assert res.source_lang == "en"
    assert res.target_lang == "en"
    assert res.translated is False
    assert res.cached is False


@pytest.mark.asyncio
async def test_translate_empty_text_noop():
    """Empty string -> translated=False, no HTTP call."""
    res = await translate("", "ml", "en")
    assert res.text == ""
    assert res.translated is False

    res_spaces = await translate("   ", "ml", "en")
    assert res_spaces.text == "   "
    assert res_spaces.translated is False


@pytest.mark.asyncio
async def test_translate_happy_path(mock_200_response):
    """Mocked 200 response -> translated=True, correct target text."""
    with patch.dict("os.environ", {"BHASHINI_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_200_response
            res = await translate("കൊച്ചി", "ml", "en")

            assert res.text == "Kochi"
            assert res.source_lang == "ml"
            assert res.target_lang == "en"
            assert res.translated is True
            assert res.cached is False
            assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_translate_no_api_key_fallback():
    """BHASHINI_API_KEY='' -> translated=False, no HTTP call made."""
    with patch.dict("os.environ", {"BHASHINI_API_KEY": ""}, clear=True):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = await translate("കൊച്ചി", "ml", "en")
            assert res.text == "കൊച്ചി"
            assert res.translated is False
            assert res.cached is False
            assert mock_post.call_count == 0


@pytest.mark.asyncio
async def test_translate_429_fallback():
    """Mocked 429 -> translated=False, original text returned, no retry."""
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.text = "Too Many Requests"

    with patch.dict("os.environ", {"BHASHINI_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp_429
            res = await translate("കൊച്ചി", "ml", "en")
            assert res.text == "കൊച്ചി"
            assert res.translated is False
            assert res.cached is False
            assert mock_post.call_count == 1  # No retries on 4xx


@pytest.mark.asyncio
async def test_translate_5xx_retries_then_fallback():
    """Mocked 500 x 4 -> translated=False, retry called 3x (4 total attempts)."""
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.text = "Internal Server Error"

    with patch.dict("os.environ", {"BHASHINI_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp_500
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                res = await translate("കൊച്ചി", "ml", "en")
                assert res.text == "കൊച്ചി"
                assert res.translated is False
                assert res.cached is False
                assert mock_post.call_count == 4
                assert [call.args[0] for call in mock_sleep.await_args_list] == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_translate_redis_cache_hit():
    """Redis returns cached bytes/str -> translated=True, cached=True, no HTTP call."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "Cached Translation"

    with patch.dict("os.environ", {"BHASHINI_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = await translate("കൊച്ചി", "ml", "en", redis_client=mock_redis)
            assert res.text == "Cached Translation"
            assert res.translated is True
            assert res.cached is True
            assert mock_post.call_count == 0


@pytest.mark.asyncio
async def test_translate_redis_error_still_calls_dhruva(mock_200_response):
    """Redis raises -> translation still attempted via Dhruva."""
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = Exception("Redis connection refused")
    mock_redis.set.side_effect = Exception("Redis write failed")

    with patch.dict("os.environ", {"BHASHINI_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_200_response
            res = await translate("കൊച്ചി", "ml", "en", redis_client=mock_redis)
            assert res.text == "Kochi"
            assert res.translated is True
            assert res.cached is False
            assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_translate_to_english_convenience(mock_200_response):
    """Calls translate() with target_lang='en'."""
    with patch.dict("os.environ", {"BHASHINI_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_200_response
            res = await translate_to_english("കൊച്ചി", "ml")
            assert res.text == "Kochi"
            assert res.source_lang == "ml"
            assert res.target_lang == "en"
            assert res.translated is True


@pytest.mark.asyncio
async def test_translate_from_english_convenience():
    """Calls translate() with source_lang='en'."""
    mock_ml_resp = MagicMock()
    mock_ml_resp.status_code = 200
    mock_ml_resp.json.return_value = {
        "pipelineResponse": [
            {
                "output": [
                    {
                        "source": "Kochi",
                        "target": "കൊച്ചി",
                    }
                ]
            }
        ]
    }
    with patch.dict("os.environ", {"BHASHINI_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_ml_resp
            res = await translate_from_english("Kochi", "ml")
            assert res.text == "കൊച്ചി"
            assert res.source_lang == "en"
            assert res.target_lang == "ml"
            assert res.translated is True


# ---------------------------------------------------------------------------
# ULCA ASR transcribe() — voice path (#194, contract per research #192)
# ---------------------------------------------------------------------------

ASR_ENV = {"BHASHINI_API_KEY": "test-key", "BHASHINI_ULCA_USER_ID": "test-user"}


def _config_200(service_id="svc-ml-test", infer_key="infer-test-key"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "pipelineResponseConfig": [
            {
                "taskType": "asr",
                "config": [{"serviceId": service_id, "language": {"sourceLanguage": "ml"}}],
            }
        ],
        "pipelineInferenceAPIEndPoint": {
            "callbackUrl": "https://dhruva-api.bhashini.gov.in/services/inference/pipeline",
            "inferenceApiKey": {"name": "Authorization", "value": infer_key},
        },
    }
    return resp


def _compute_200(text="എവിടെ മീൻ കിട്ടും"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "pipelineResponse": [{"taskType": "asr", "output": [{"source": text}]}]
    }
    return resp


@pytest.mark.asyncio
async def test_transcribe_success():
    """Config 200 + Compute 200 -> transcribed=True with ULCA contract shapes."""
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200(), _compute_200()]
            res = await transcribe(b"RIFF....WAVEfmt ...." + b"\x00" * 100, "ml")

            assert isinstance(res, TranscriptionResult)
            assert res.text == "എവിടെ മീൻ കിട്ടും"
            assert res.source_lang == "ml"
            assert res.transcribed is True
            assert res.cached is False
            assert mock_post.call_count == 2

            # Config call: ULCA headers + pipelineId
            config_kwargs = mock_post.call_args_list[0][1]
            assert config_kwargs["headers"]["userID"] == "test-user"
            assert config_kwargs["headers"]["ulcaApiKey"] == "test-key"
            assert config_kwargs["json"]["pipelineTasks"][0]["taskType"] == "asr"
            assert config_kwargs["json"]["pipelineTasks"][0]["config"]["language"] == {
                "sourceLanguage": "ml"
            }

            # Compute call: raw inference key (no Bearer), wav contract
            compute_kwargs = mock_post.call_args_list[1][1]
            assert compute_kwargs["headers"]["Authorization"] == "infer-test-key"
            cfg = compute_kwargs["json"]["pipelineTasks"][0]["config"]
            assert cfg["serviceId"] == "svc-ml-test"
            assert cfg["audioFormat"] == "wav"
            assert cfg["samplingRate"] == 16000
            assert compute_kwargs["json"]["inputData"]["audio"][0]["audioContent"]


@pytest.mark.asyncio
async def test_transcribe_lang_normalized():
    """ml-IN normalizes to ml for cache key + ULCA sourceLanguage."""
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200(), _compute_200()]
            res = await transcribe(b"\x01\x02", "ml-IN")
            assert res.transcribed is True
            assert res.source_lang == "ml"
            cfg = mock_post.call_args_list[1][1]["json"]["pipelineTasks"][0]["config"]
            assert cfg["language"] == {"sourceLanguage": "ml"}


@pytest.mark.asyncio
async def test_transcribe_empty_audio_noop():
    """Empty bytes -> transcribed=False, no HTTP call."""
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = await transcribe(b"", "ml")
            assert res.text == ""
            assert res.transcribed is False
            assert mock_post.call_count == 0


@pytest.mark.asyncio
async def test_transcribe_key_missing_fallback():
    """Missing BHASHINI_API_KEY or BHASHINI_ULCA_USER_ID -> transcribed=False, no HTTP."""
    for env in ({"BHASHINI_ULCA_USER_ID": "u"}, {"BHASHINI_API_KEY": "k"}, {}):
        with patch.dict("os.environ", env, clear=True):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                res = await transcribe(b"\x01\x02", "ml")
                assert res.text == ""
                assert res.transcribed is False
                assert res.cached is False
                assert mock_post.call_count == 0


@pytest.mark.asyncio
async def test_transcribe_redis_cache_hit():
    """Redis returns cached text -> transcribed=True, cached=True, no HTTP call."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "Cached transcription"

    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = await transcribe(b"\x01\x02", "ml", redis_client=mock_redis)
            assert res.text == "Cached transcription"
            assert res.transcribed is True
            assert res.cached is True
            assert mock_post.call_count == 0


@pytest.mark.asyncio
async def test_transcribe_caches_non_empty_only():
    """Success writes Redis; empty output (no speech) does not."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200(), _compute_200()]
            res = await transcribe(b"\x01\x02", "ml", redis_client=mock_redis)
            assert res.transcribed is True
            assert mock_redis.set.call_count == 1

    mock_redis2 = AsyncMock()
    mock_redis2.get.return_value = None
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200(), _compute_200("   ")]
            res = await transcribe(b"\x01\x02", "ml", redis_client=mock_redis2)
            assert res.transcribed is False
            assert mock_redis2.set.call_count == 0


@pytest.mark.asyncio
async def test_transcribe_config_4xx_no_retry():
    """Config 400 -> transcribed=False, single attempt (no 4xx retry)."""
    resp_400 = MagicMock()
    resp_400.status_code = 400
    resp_400.text = "Bad Request"

    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp_400
            res = await transcribe(b"\x01\x02", "ml")
            assert res.transcribed is False
            assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_transcribe_compute_401_no_retry():
    """Config 200 + Compute 401 -> transcribed=False, compute tried once."""
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.text = "Unauthorized"

    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200(), resp_401]
            res = await transcribe(b"\x01\x02", "ml")
            assert res.transcribed is False
            assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_transcribe_5xx_retries_then_fallback():
    """Config 500 x 4 -> transcribed=False, backoff 1s->2s->4s (4 attempts)."""
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.text = "Internal Server Error"

    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp_500
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                res = await transcribe(b"\x01\x02", "ml")
                assert res.transcribed is False
                assert mock_post.call_count == 4
                assert [call.args[0] for call in mock_sleep.await_args_list] == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_transcribe_network_error_never_raises():
    """httpx network errors exhaust retries -> transcribed=False, never raises."""
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("ULCA unreachable")
            with patch("asyncio.sleep", new_callable=AsyncMock):
                res = await transcribe(b"\x01\x02", "ml")
                assert res.transcribed is False
                assert mock_post.call_count == 4


@pytest.mark.asyncio
async def test_transcribe_top_level_endpoint_parsed():
    """Canonical ULCA shape (top-level pipelineInferenceAPIEndPoint with
    inferenceApiKey {name, value}) -> transcribed=True."""
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200(), _compute_200()]
            res = await transcribe(b"\x01\x02", "ml")
            assert res.transcribed is True
            assert res.text == "എവിടെ മീൻ കിട്ടും"
            compute_kwargs = mock_post.call_args_list[1][1]
            assert compute_kwargs["headers"]["Authorization"] == "infer-test-key"
            cfg = compute_kwargs["json"]["pipelineTasks"][0]["config"]
            assert cfg["serviceId"] == "svc-ml-test"


# ---------------------------------------------------------------------------
# US-VOICE-503: Detailed error codes, retryable flags, and telemetry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_empty_audio_error_contract():
    """Empty audio returns NO_SPEECH_DETECTED with retryable=False."""
    with patch.dict("os.environ", ASR_ENV):
        res = await transcribe(b"", "ml")
        assert res.transcribed is False
        assert res.error_code == "NO_SPEECH_DETECTED"
        assert res.error_detail == "Empty audio payload received."
        assert res.retryable is False


@pytest.mark.asyncio
async def test_transcribe_missing_credentials_contract(caplog):
    """Missing credentials returns ASR_CONFIG_MISSING with retryable=False and logs warning."""
    with patch.dict("os.environ", {}, clear=True):
        with caplog.at_level(logging.WARNING):
            res = await transcribe(b"\x01\x02", "ml")
            assert res.transcribed is False
            assert res.error_code == "ASR_CONFIG_MISSING"
            assert "unconfigured" in (res.error_detail or "").lower()
            assert res.retryable is False
            assert "Bhashini ASR credentials missing" in caplog.text


@pytest.mark.asyncio
async def test_transcribe_config_timeout():
    """Config timeout returns ASR_TIMEOUT with retryable=True."""
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Config timeout")
            with patch("asyncio.sleep", new_callable=AsyncMock):
                res = await transcribe(b"\x01\x02", "ml")
                assert res.transcribed is False
                assert res.error_code == "ASR_TIMEOUT"
                assert res.retryable is True


@pytest.mark.asyncio
async def test_transcribe_config_4xx_upstream_error():
    """Config 4xx returns BHASHINI_UPSTREAM_ERROR with retryable=False."""
    resp_400 = MagicMock()
    resp_400.status_code = 400
    resp_400.text = "Bad Request"
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp_400
            res = await transcribe(b"\x01\x02", "ml")
            assert res.transcribed is False
            assert res.error_code == "BHASHINI_UPSTREAM_ERROR"
            assert res.retryable is False


@pytest.mark.asyncio
async def test_transcribe_config_5xx_upstream_error():
    """Config 5xx returns BHASHINI_UPSTREAM_ERROR with retryable=True."""
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.text = "Internal Server Error"
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp_500
            with patch("asyncio.sleep", new_callable=AsyncMock):
                res = await transcribe(b"\x01\x02", "ml")
                assert res.transcribed is False
                assert res.error_code == "BHASHINI_UPSTREAM_ERROR"
                assert res.retryable is True


@pytest.mark.asyncio
async def test_transcribe_config_parse_failure():
    """Config response missing serviceId/inference_key returns BHASHINI_UPSTREAM_ERROR with retryable=False."""
    resp_bad = MagicMock()
    resp_bad.status_code = 200
    resp_bad.json.return_value = {"invalid": "shape"}
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp_bad
            res = await transcribe(b"\x01\x02", "ml")
            assert res.transcribed is False
            assert res.error_code == "BHASHINI_UPSTREAM_ERROR"
            assert res.retryable is False


@pytest.mark.asyncio
async def test_transcribe_compute_timeout():
    """Compute timeout returns ASR_TIMEOUT with retryable=True."""
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200()] + [httpx.TimeoutException("Compute timeout")] * 4
            with patch("asyncio.sleep", new_callable=AsyncMock):
                res = await transcribe(b"\x01\x02", "ml")
                assert res.transcribed is False
                assert res.error_code == "ASR_TIMEOUT"
                assert res.retryable is True


@pytest.mark.asyncio
async def test_transcribe_compute_4xx_upstream_error():
    """Compute 4xx returns BHASHINI_UPSTREAM_ERROR with retryable=False."""
    resp_403 = MagicMock()
    resp_403.status_code = 403
    resp_403.text = "Forbidden"
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200(), resp_403]
            res = await transcribe(b"\x01\x02", "ml")
            assert res.transcribed is False
            assert res.error_code == "BHASHINI_UPSTREAM_ERROR"
            assert res.retryable is False


@pytest.mark.asyncio
async def test_transcribe_compute_5xx_upstream_error():
    """Compute 5xx returns BHASHINI_UPSTREAM_ERROR with retryable=True."""
    resp_503 = MagicMock()
    resp_503.status_code = 503
    resp_503.text = "Service Unavailable"
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200()] + [resp_503] * 4
            with patch("asyncio.sleep", new_callable=AsyncMock):
                res = await transcribe(b"\x01\x02", "ml")
                assert res.transcribed is False
                assert res.error_code == "BHASHINI_UPSTREAM_ERROR"
                assert res.retryable is True


@pytest.mark.asyncio
async def test_transcribe_empty_transcription_no_speech():
    """Empty transcription from compute returns NO_SPEECH_DETECTED with retryable=False."""
    with patch.dict("os.environ", ASR_ENV):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [_config_200(), _compute_200("   ")]
            res = await transcribe(b"\x01\x02", "ml")
            assert res.transcribed is False
            assert res.error_code == "NO_SPEECH_DETECTED"
            assert res.error_detail == "No speech detected in audio."
            assert res.retryable is False

