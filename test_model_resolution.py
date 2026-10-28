"""Self-check: a cached base.en counts as "base", so auto never picks a bigger model to download.
Run from the repo's parent: python -m openflow.test_model_resolution"""
from openflow.engine import hardware, model_manager as mm


def test_only_base_en_cached():
    real = mm.cached_path
    mm.cached_path = lambda name: "/fake/base.en" if name == "base.en" else None
    try:
        assert mm.variants("base") == ["base", "base.en"]
        assert mm.variants("parakeet") == ["parakeet"]
        assert mm.is_model_downloaded("base")
        assert not mm.is_model_downloaded("small")
        assert mm.list_downloaded_models() == ["base"]
        assert mm.any_cached_path("base") == "/fake/base.en"
        assert hardware.resolve({"model_size": "auto", "device": "cpu"})["model_size"] == "base"
    finally:
        mm.cached_path = real


if __name__ == "__main__":
    test_only_base_en_cached()
    print("ok")
