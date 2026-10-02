"""VIDEO-GEN 场景 synthetic 构造器与场景注册单测（V1 引擎预备）。"""

from app.core.model_registry.synthetic import BUILDERS, build_video_gen


def test_build_video_gen_with_final_id():
    assert build_video_gen({"_final_id": "fcw-1", "language": "zh-CN"}) == {
        "video_ref": "synthetic:video:fcw-1:zh-CN"
    }


def test_build_video_gen_other_language():
    assert build_video_gen({"_final_id": "fcw-1", "language": "en"}) == {
        "video_ref": "synthetic:video:fcw-1:en"
    }


def test_build_video_gen_without_final_id():
    # 无 final_id（无可用原料）时 video_ref 给空字符串。
    assert build_video_gen({"language": "zh-CN"}) == {"video_ref": ""}


def test_build_video_gen_default_language():
    assert build_video_gen({"_final_id": "fcw-1"}) == {
        "video_ref": "synthetic:video:fcw-1:zh-CN"
    }


def test_video_gen_registered_in_builders():
    assert BUILDERS["VIDEO-GEN"] is build_video_gen


def test_video_gen_in_scene_codes():
    from app.core.model_registry.seeds import all_scene_codes

    assert "VIDEO-GEN" in all_scene_codes()
