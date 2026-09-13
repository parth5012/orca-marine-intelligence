"""
Unit tests for backend/core/bhashini.py — Bhashini Dhruva translation client.

Owner: M-A (Agents & Orchestration) — unit tests with mocked HTTP
Module: tests/test_bhashini.py
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from backend.core.bhashini import (
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
    """Mocked 500 x 3 -> translated=False, retry called 3x."""
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
                assert mock_post.call_count == 3
                assert mock_sleep.call_count == 2  # Sleeps between 3 attempts: attempt 1->sleep 1s, attempt 2->sleep 2s


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
