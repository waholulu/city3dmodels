from pathlib import Path

from src.validator import validate_output_files


def _write_minimal_obj_mtl(tmp_path: Path, obj_name: str = "model.obj", mtl_name: str = "model.mtl") -> tuple[str, str]:
    mtl_path = tmp_path / mtl_name
    mtl_path.write_text("newmtl mat_roof\nKd 0.8 0.8 0.8\n", encoding="utf-8")

    obj_path = tmp_path / obj_name
    obj_body = "\n".join(
        [
            f"mtllib {mtl_name}",
            "usemtl mat_roof",
            "v 0.0 0.0 0.0",
            "v 0.1 0.0 0.0",
            "v 0.0 0.1 0.0",
            "f 1 2 3",
        ]
    )
    padding = "\n".join(["# filler line" for _ in range(1200)])
    obj_path.write_text(obj_body + "\n" + padding + "\n", encoding="utf-8")
    return str(obj_path), str(mtl_path)


def test_validator_print_scale_message_uses_runtime_scale_10000(tmp_path: Path):
    obj_path, mtl_path = _write_minimal_obj_mtl(tmp_path)
    report = validate_output_files(obj_path, mtl_path, radius_m=1000, is_tile=False, scale=10000)

    assert any("1:10000" in err for err in report.errors)


def test_validator_print_scale_message_uses_runtime_scale_50000(tmp_path: Path):
    obj_path, mtl_path = _write_minimal_obj_mtl(tmp_path)
    report = validate_output_files(obj_path, mtl_path, radius_m=1000, is_tile=False, scale=50000)

    assert any("1:50000" in err for err in report.errors)
